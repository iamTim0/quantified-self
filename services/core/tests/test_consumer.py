import json
from datetime import datetime, timezone

import pytest
from core.events.consumer import MAX_DELIVERY_ATTEMPTS, process_message
from sqlalchemy.exc import IntegrityError


class DummyMsg:
    def __init__(self, payload: dict, *, num_delivered: int = 1):
        self.data = json.dumps(payload).encode("utf-8")
        self.acked = False
        self.terminated = False
        self.metadata = type("Meta", (), {"num_delivered": num_delivered})()

    async def ack(self):
        self.acked = True

    async def term(self):
        self.terminated = True


def _event() -> dict:
    return {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "source_id": "22222222-2222-2222-2222-222222222222",
        "metric_type": "steps",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "value": 1200,
        "idempotency_key": "k",
    }


class _SessionRaising:
    """A session whose insert fails, as a stand-in for the database refusing the row."""

    def __init__(self, error: Exception):
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, *args, **kwargs):
        raise self._error

    async def commit(self):  # pragma: no cover - never reached
        raise AssertionError("commit must not follow a failed insert")


def _session_raising(error: Exception):
    return lambda: _SessionRaising(error)


@pytest.mark.asyncio
async def test_rejects_missing_idempotency_key(monkeypatch):
    """Verifies Fizzbee Invariant: NoDuplicateData."""

    async def fail_session_maker():  # pragma: no cover - must never be entered
        raise AssertionError("database session should not open for invalid events")

    monkeypatch.setattr("core.events.consumer.async_session_maker", fail_session_maker)
    msg = DummyMsg({"tenant_id": "tenant-1", "timestamp": datetime.now(timezone.utc).isoformat()})

    await process_message(msg)

    assert msg.acked is True


@pytest.mark.asyncio
async def test_an_event_the_schema_refuses_is_acked(monkeypatch):
    """A foreign key naming a tenant that no longer exists cannot be fixed by waiting.

    Left unacked it holds one of the consumer's finite ack slots and is redelivered
    forever. In bulk -- a database wiped while the stream kept its events -- that stops
    ingestion for every tenant, which is how 1.8 million events came to block a million
    more behind them.
    """
    error = IntegrityError("INSERT", {}, Exception("data_points_source_id_fkey"))
    monkeypatch.setattr("core.events.consumer.async_session_maker", _session_raising(error))
    msg = DummyMsg(_event())

    await process_message(msg)

    assert msg.acked is True
    assert msg.terminated is False


@pytest.mark.asyncio
async def test_a_failure_that_might_pass_next_time_is_redelivered(monkeypatch):
    """A database that is merely restarting must not cost the event."""
    monkeypatch.setattr(
        "core.events.consumer.async_session_maker",
        _session_raising(RuntimeError("connection refused")),
    )
    msg = DummyMsg(_event(), num_delivered=1)

    await process_message(msg)

    assert msg.acked is False
    assert msg.terminated is False


@pytest.mark.asyncio
async def test_a_failure_that_keeps_recurring_is_given_up_on(monkeypatch):
    """`max_deliver` defaults to unlimited, and unlimited redelivery of a message that
    always fails is a consumer that never advances."""
    monkeypatch.setattr(
        "core.events.consumer.async_session_maker",
        _session_raising(RuntimeError("connection refused")),
    )
    msg = DummyMsg(_event(), num_delivered=MAX_DELIVERY_ATTEMPTS)

    await process_message(msg)

    assert msg.terminated is True
    assert msg.acked is False
