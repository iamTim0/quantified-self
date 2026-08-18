import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from core.config import settings
from core.events.consumer import (
    INGESTION_RESET_GATE_SUBJECT,
    INGESTION_SUBJECT,
    IngestionConsumerController,
    IngestionResetError,
    ingestion_retention_warning,
)
from core.main import app
from httpx import ASGITransport, AsyncClient
from nats.js.api import RetentionPolicy, StreamConfig

from tests.db_helpers import (
    as_platform_tenant,
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
)


class _FakeJetStream:
    def __init__(
        self,
        counts: list[tuple[int, int]],
        *,
        gate_reached: asyncio.Event | None = None,
        allow_delete: asyncio.Event | None = None,
    ) -> None:
        self.config = StreamConfig(
            name="ingestion",
            subjects=[INGESTION_SUBJECT],
            retention=RetentionPolicy.LIMITS,
            max_age=7 * 24 * 60 * 60,
            max_bytes=4 * 1024 * 1024 * 1024,
        )
        self.counts = list(counts)
        self.updated_subjects: list[list[str] | None] = []
        self.deleted = False
        self.gate_reached = gate_reached
        self.allow_delete = allow_delete

    async def consumer_info(self, _stream: str, _consumer: str) -> Any:
        pending, ack_pending = self.counts.pop(0) if self.counts else (0, 0)
        return SimpleNamespace(num_pending=pending, num_ack_pending=ack_pending)

    async def stream_info(self, _stream: str) -> Any:
        return SimpleNamespace(config=self.config)

    async def update_stream(self, config: StreamConfig) -> Any:
        self.config = config
        self.updated_subjects.append(config.subjects)
        if config.subjects == [INGESTION_RESET_GATE_SUBJECT] and self.gate_reached:
            self.gate_reached.set()
        return SimpleNamespace(config=config)

    async def delete_stream(self, _stream: str) -> bool:
        if self.allow_delete:
            await self.allow_delete.wait()
        self.deleted = True
        return True


class _FakeConnection:
    def __init__(self, jetstream: _FakeJetStream) -> None:
        self.jetstream_context = jetstream
        self.is_connected = True
        self.closed = False

    def jetstream(self) -> _FakeJetStream:
        return self.jetstream_context

    async def close(self) -> None:
        self.closed = True
        self.is_connected = False


@pytest.mark.asyncio
async def test_pending_counts_refuse_without_gating_or_deleting() -> None:
    """Verifies Fizzbee Invariant: DeleteOnlyWhenDrained."""
    controller = IngestionConsumerController()
    jetstream = _FakeJetStream([(3, 2)])
    connection = _FakeConnection(jetstream)
    controller.connected(connection, asyncio.Event())

    with pytest.raises(IngestionResetError) as caught:
        await controller.reset()

    assert caught.value.code == "ingestion_reset_pending_events"
    assert caught.value.num_pending == 3
    assert caught.value.num_ack_pending == 2
    assert jetstream.updated_subjects == []
    assert jetstream.deleted is False


@pytest.mark.asyncio
async def test_retention_warning_carries_live_counts_without_claiming_gate_active() -> None:
    """Verifies Fizzbee Invariants: RetentionMismatchIsVisible, PublishGateOnlyDuringReset."""
    jetstream = _FakeJetStream([(5, 2)])
    connection = _FakeConnection(jetstream)

    warning = await ingestion_retention_warning(connection)

    assert warning is not None
    assert warning.code == "ingestion_stream_retention_mismatch"
    assert warning.params == {
        "actual_retention": "limits",
        "expected_retention": "workqueue",
        "owner_only": "true",
        "num_pending": "5",
        "num_ack_pending": "2",
    }
    assert "gated" not in warning.detail.lower()


@pytest.mark.asyncio
async def test_gate_final_check_catches_a_publish_race_and_restores_subjects() -> None:
    """Verifies Fizzbee Invariants: PublishGatePrecedesFinalDrainCheck, DeleteOnlyWhenDrained."""
    controller = IngestionConsumerController()
    jetstream = _FakeJetStream([(0, 0), (4, 1)])
    connection = _FakeConnection(jetstream)
    controller.connected(connection, asyncio.Event())

    with pytest.raises(IngestionResetError) as caught:
        await controller.reset()

    assert caught.value.code == "ingestion_reset_pending_events"
    assert caught.value.num_pending == 4
    assert caught.value.num_ack_pending == 1
    assert jetstream.deleted is False
    assert jetstream.updated_subjects == [[INGESTION_RESET_GATE_SUBJECT], [INGESTION_SUBJECT]]


@pytest.mark.asyncio
async def test_reset_waits_for_a_new_ready_consumer_generation() -> None:
    """Verifies Fizzbee Invariant: SuccessfulResetHasActiveConsumer."""
    controller = IngestionConsumerController()
    old_jetstream = _FakeJetStream([(0, 0), (0, 0)])
    old_connection = _FakeConnection(old_jetstream)
    old_lost = asyncio.Event()
    controller.connected(old_connection, old_lost)
    initial_generation = controller.generation

    async def supervisor() -> None:
        await old_lost.wait()
        new_connection = _FakeConnection(_FakeJetStream([]))
        controller.connected(new_connection, asyncio.Event())

    supervisor_task = asyncio.create_task(supervisor())
    result = await controller.reset()
    await supervisor_task

    assert result["code"] == "ingestion_stream_reset"
    assert controller.generation > initial_generation
    assert controller.status == "connected"
    assert controller.client is not old_connection
    assert old_connection.closed is True
    assert old_jetstream.deleted is True


@pytest.mark.asyncio
async def test_concurrent_reset_is_serialized() -> None:
    """Verifies Fizzbee Invariant: AtMostOneResetInProgress."""
    gate_reached = asyncio.Event()
    allow_delete = asyncio.Event()
    controller = IngestionConsumerController()
    jetstream = _FakeJetStream(
        [(0, 0), (0, 0)],
        gate_reached=gate_reached,
        allow_delete=allow_delete,
    )
    connection = _FakeConnection(jetstream)
    lost = asyncio.Event()
    controller.connected(connection, lost)

    async def reconnect() -> None:
        await lost.wait()
        controller.connected(_FakeConnection(_FakeJetStream([])), asyncio.Event())

    reset_task = asyncio.create_task(controller.reset())
    await gate_reached.wait()
    with pytest.raises(IngestionResetError) as caught:
        await controller.reset()
    assert caught.value.code == "ingestion_reset_busy"

    allow_delete.set()
    await asyncio.gather(reset_task, reconnect())


@pytest.mark.asyncio
async def test_cancelled_reset_restores_the_temporary_publish_gate() -> None:
    """Verifies Fizzbee Invariant: FailedResetNeverReportsSuccess."""
    gate_reached = asyncio.Event()
    controller = IngestionConsumerController()
    jetstream = _FakeJetStream(
        [(0, 0), (0, 0)],
        gate_reached=gate_reached,
        allow_delete=asyncio.Event(),
    )
    connection = _FakeConnection(jetstream)
    controller.connected(connection, asyncio.Event())

    reset_task = asyncio.create_task(controller.reset())
    await gate_reached.wait()
    reset_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await reset_task

    assert jetstream.deleted is False
    assert jetstream.updated_subjects == [[INGESTION_RESET_GATE_SUBJECT], [INGESTION_SUBJECT]]
    assert controller._reset_in_progress is False


@pytest.mark.asyncio
async def test_reset_endpoint_is_owner_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifies Fizzbee Invariant: OnlyOperatorCanReset."""
    tenant_id = await create_test_tenant()
    try:
        # Resetting the stream discards every tenant's pending events, so it is a
        # deployment operation and needs the deployment's workspace.
        as_platform_tenant(monkeypatch, tenant_id)

        class _Controller:
            async def reset(self) -> dict[str, str]:
                return {"code": "ingestion_stream_reset", "status": "recreated"}

        monkeypatch.setattr(settings, "CORE_ROLE", "ingest")
        monkeypatch.setattr(app.state, "ingestion_controller", _Controller(), raising=False)
        app.state.testing = True
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="https://testserver") as client:
            member = await client.post(
                "/api/v1/data/system/ingestion/reset",
                headers=auth_headers(tenant_id, role="member"),
            )
            owner = await client.post(
                "/api/v1/data/system/ingestion/reset",
                headers=auth_headers(tenant_id, role="owner"),
            )

        assert member.status_code == 403
        assert owner.status_code == 200
        assert owner.json()["code"] == "ingestion_stream_reset"
    finally:
        await cleanup_test_tenant(tenant_id)
