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


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

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
