import json
import math
from datetime import datetime, timezone

import pytest
from core.events.consumer import (
    MAX_DELIVERY_ATTEMPTS,
    MAX_INGEST_EVENT_BYTES,
    event_idempotency_key_matches,
    process_message,
)
from shared_schemas import idempotency_key
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
    timestamp = datetime.now(timezone.utc).isoformat()
    tenant_id = "11111111-1111-1111-1111-111111111111"
    source_id = "22222222-2222-2222-2222-222222222222"
    return {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "metric_type": "steps",
        "timestamp": timestamp,
        "value": 1200,
        "idempotency_key": idempotency_key(tenant_id, source_id, "steps", timestamp),
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
async def test_rejects_a_key_that_does_not_match_the_event(monkeypatch):
    """Verifies Fizzbee Invariant: NoDuplicateData."""

    async def fail_session_maker():  # pragma: no cover - must never be entered
        raise AssertionError("database session should not open for an invalid key")

    monkeypatch.setattr("core.events.consumer.async_session_maker", fail_session_maker)
    event = _event()
    event["idempotency_key"] = "not-the-event-key"

    msg = DummyMsg(event)
    await process_message(msg)

    assert msg.acked is True


def test_idempotency_key_check_uses_the_canonical_name_for_known_metrics():
    """Aliases cannot enter storage under a key derived from the alias."""
    tenant_id = "11111111-1111-1111-1111-111111111111"
    source_id = "22222222-2222-2222-2222-222222222222"
    timestamp = "2026-08-11T12:00:00+00:00"
    canonical_key = idempotency_key(tenant_id, source_id, "steps", timestamp)

    assert event_idempotency_key_matches(
        tenant_id, source_id, "step_count", "steps", timestamp, canonical_key
    )
    assert not event_idempotency_key_matches(
        tenant_id, source_id, "step_count", "steps", timestamp, "alias-key"
    )


def test_idempotency_key_check_accepts_a_connector_scoped_child_identity():
    """Child records may share a timestamp without weakening connector isolation."""
    tenant_id = "11111111-1111-1111-1111-111111111111"
    source_id = "22222222-2222-2222-2222-222222222222"
    child_id = f"{source_id}_meal_dinner"
    timestamp = "2026-08-11T12:00:00+00:00"
    child_key = idempotency_key(tenant_id, child_id, "nutrition_meal_energy", timestamp)

    assert event_idempotency_key_matches(
        tenant_id, source_id, "nutrition_meal_energy", "nutrition_meal_energy",
        timestamp, child_key, child_id
    )
    assert not event_idempotency_key_matches(
        tenant_id, source_id, "nutrition_meal_energy", "nutrition_meal_energy",
        timestamp, child_key
    )


def test_invalid_metadata_keeps_only_provenance():
    """Non-finite JSON values cannot poison the database or force raw metadata storage."""
    from core.events.consumer import bounded_point_metadata

    assert bounded_point_metadata({"bad": math.nan}, 12) == {
        "provider_value": 12,
        "units": None,
        "metadata_truncated": True,
    }


@pytest.mark.asyncio
async def test_rejects_an_oversized_event_before_opening_the_database(monkeypatch):
    """A broker payload cap prevents quarantine from becoming a storage DoS."""

    async def fail_session_maker():  # pragma: no cover - must never be entered
        raise AssertionError("database session should not open for an oversized event")

    monkeypatch.setattr("core.events.consumer.async_session_maker", fail_session_maker)
    msg = DummyMsg({})
    msg.data = b"x" * (MAX_INGEST_EVENT_BYTES + 1)

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
