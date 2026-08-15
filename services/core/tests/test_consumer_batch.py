"""Tests for the bounded ingest envelope and its acknowledgement contract."""

import json
from typing import Any

import pytest
from core.events import consumer


class _EnvelopeMessage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.data = json.dumps(payload).encode()
        self.ack_count = 0

    async def ack(self) -> None:
        self.ack_count += 1


class _Savepoint:
    """What `session.begin_nested()` hands back, counting its own outcome."""

    def __init__(self, session: "_Session") -> None:
        self._session = session

    async def commit(self) -> None:
        self._session.savepoint_commits += 1

    async def rollback(self) -> None:
        self._session.savepoint_rollbacks += 1


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.savepoint_commits = 0
        self.savepoint_rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def begin_nested(self) -> _Savepoint:
        return _Savepoint(self)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.mark.asyncio
async def test_batch_ack_waits_for_all_children(monkeypatch):
    """Verifies Fizzbee Invariant: AckAfterBatchCommit."""
    processed: list[dict[str, Any]] = []

    async def fake_process(message, **_kwargs):
        processed.append(json.loads(message.data))

    monkeypatch.setattr(consumer, "process_message", fake_process)
    session = _Session()
    monkeypatch.setattr(consumer, "async_session_maker", lambda: session)
    message = _EnvelopeMessage(
        {
            "schema_version": 2,
            "batch_id": "batch-1",
            "tenant_id": "tenant-a",
            "source_id": "source-a",
            "events": [{"metric_type": "steps"}, {"metric_type": "distance"}],
        }
    )

    await consumer._process_batch_message(message, json.loads(message.data))

    assert message.ack_count == 1
    assert len(processed) == 2
    assert session.commits == 1
    assert session.rollbacks == 0
    assert all(event["tenant_id"] == "tenant-a" for event in processed)
    assert all(event["source_id"] == "source-a" for event in processed)


@pytest.mark.asyncio
async def test_transient_batch_child_leaves_envelope_for_redelivery(monkeypatch):
    """Verifies Fizzbee Invariants: BatchRedeliveryDoesNotDoubleCount and AckAfterBatchCommit."""
    failed = False

    async def fake_process(message, **_kwargs):
        nonlocal failed
        if not failed:
            failed = True
            message.failed = True

    retried = 0

    async def fake_retry(message):
        nonlocal retried
        retried += 1

    monkeypatch.setattr(consumer, "process_message", fake_process)
    monkeypatch.setattr(consumer, "_retry_or_give_up", fake_retry)
    session = _Session()
    monkeypatch.setattr(consumer, "async_session_maker", lambda: session)
    message = _EnvelopeMessage(
        {
            "schema_version": 2,
            "batch_id": "batch-1",
            "tenant_id": "tenant-a",
            "source_id": "source-a",
            "events": [{"metric_type": "steps"}],
        }
    )

    await consumer._process_batch_message(message, json.loads(message.data))

    assert message.ack_count == 0
    assert retried == 1
    assert session.commits == 0
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_one_unstorable_child_does_not_discard_its_thousand_siblings(monkeypatch):
    """A permanent child failure is dropped; the rest of the envelope still commits.

    Verifies Fizzbee Invariant: AckAfterBatchCommit.

    The single-event path has acknowledged constraint violations since a wiped
    database produced them in bulk — a retry cannot store a point whose foreign key
    names a row that does not exist. The batch path had no savepoint, so its only
    option was to fail the whole envelope, which JetStream then redelivered five
    times before discarding all thousand events, the storable ones included.
    """
    seen: list[str] = []

    async def fake_process(message, **_kwargs):
        payload = json.loads(message.data)
        seen.append(payload["metric_type"])
        if payload["metric_type"] == "poison":
            message.failed = True
            message.permanent = True

    retried = 0

    async def fake_retry(message):
        nonlocal retried
        retried += 1

    monkeypatch.setattr(consumer, "process_message", fake_process)
    monkeypatch.setattr(consumer, "_retry_or_give_up", fake_retry)
    session = _Session()
    monkeypatch.setattr(consumer, "async_session_maker", lambda: session)
    message = _EnvelopeMessage(
        {
            "schema_version": 2,
            "batch_id": "batch-poison",
            "tenant_id": "tenant-a",
            "source_id": "source-a",
            "events": [
                {"metric_type": "steps"},
                {"metric_type": "poison"},
                {"metric_type": "distance"},
            ],
        }
    )

    await consumer._process_batch_message(message, json.loads(message.data))

    # Every child was attempted: the poison one did not stop the walk.
    assert seen == ["steps", "poison", "distance"]
    # Only the poison child's savepoint was rolled back; the siblings kept theirs.
    assert session.savepoint_rollbacks == 1
    assert session.savepoint_commits == 2
    # The envelope is committed and acknowledged, not redelivered.
    assert session.commits == 1
    assert session.rollbacks == 0
    assert message.ack_count == 1
    assert retried == 0
