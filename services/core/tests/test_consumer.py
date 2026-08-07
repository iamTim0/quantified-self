import json
from datetime import datetime, timezone

import pytest
from core.events.consumer import process_message


class DummyMsg:
    def __init__(self, payload: dict):
        self.data = json.dumps(payload).encode("utf-8")
        self.acked = False

    async def ack(self):
        self.acked = True


@pytest.mark.asyncio
async def test_rejects_missing_idempotency_key(monkeypatch):
    """Verifies Fizzbee Invariant: NoDuplicateData."""

    async def fail_session_maker():  # pragma: no cover - must never be entered
        raise AssertionError("database session should not open for invalid events")

    monkeypatch.setattr("core.events.consumer.async_session_maker", fail_session_maker)
    msg = DummyMsg({"tenant_id": "tenant-1", "timestamp": datetime.now(timezone.utc).isoformat()})

    await process_message(msg)

    assert msg.acked is True
