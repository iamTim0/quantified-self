"""JetStream task ownership while a WHOOP sync is running."""

from __future__ import annotations

import asyncio
import json

import pytest
from shared_schemas.core_status import CoreStatusUnavailable
from whoop_importer import main as importer

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"


class FakeMessage:
    def __init__(self) -> None:
        self.data = json.dumps(
            {
                "tenant_id": TENANT,
                "source_id": SOURCE,
                "source_type": "whoop",
                "request_id": "req_lease_test",
                "sync_run_id": "run_lease_test",
            }
        ).encode()
        self.acks = 0
        self.naks: list[int] = []

    async def ack(self) -> None:
        self.acks += 1

    async def nak(self, *, delay: int) -> None:
        self.naks.append(delay)

    async def in_progress(self) -> None:
        pass


@pytest.mark.asyncio
async def test_busy_connector_defers_duplicate_delivery() -> None:
    """Verifies Fizzbee Invariant: BusyTaskRetainedUntilProcessed."""
    message = FakeMessage()
    lock_key = f"{TENANT}:{SOURCE}"
    importer.active_syncs.add(lock_key)
    try:
        await importer.process_task_message(message, None)
    finally:
        importer.active_syncs.discard(lock_key)

    assert message.naks == [30]
    assert message.acks == 0


@pytest.mark.asyncio
async def test_cancelled_sync_leaves_task_unacknowledged(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: TaskAckAfterCompletion."""
    message = FakeMessage()
    started = asyncio.Event()

    async def credentials(*_args, **_kwargs):
        return "test-token", SOURCE, {}

    async def long_sync(*_args, **_kwargs):
        started.set()
        await asyncio.sleep(10)

    monkeypatch.setattr(importer, "get_connector_credentials_from_core", credentials)
    monkeypatch.setattr(importer, "fetch_and_publish", long_sync)

    running = asyncio.create_task(importer.process_task_message(message, None))
    await asyncio.wait_for(started.wait(), timeout=1)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert message.acks == 0
    assert f"{TENANT}:{SOURCE}" not in importer.active_syncs


@pytest.mark.asyncio
async def test_unavailable_core_leaves_task_unacknowledged(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: TaskAckAfterCompletion."""
    message = FakeMessage()

    async def credentials(*_args, **_kwargs):
        return "test-token", SOURCE, {}

    async def unavailable_core(*_args, **_kwargs):
        raise CoreStatusUnavailable("HTTP 503")

    monkeypatch.setattr(importer, "get_connector_credentials_from_core", credentials)
    monkeypatch.setattr(importer, "fetch_and_publish", unavailable_core)

    await importer.process_task_message(message, None)

    assert message.acks == 0
    assert f"{TENANT}:{SOURCE}" not in importer.active_syncs
