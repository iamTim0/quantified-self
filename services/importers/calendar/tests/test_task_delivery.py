"""Calendar task settlement when Core cannot receive a sync result."""

from __future__ import annotations

import json

import pytest
from calendar_importer import main as importer
from shared_schemas.core_status import CoreStatusUnavailable


class FakeMessage:
    def __init__(self) -> None:
        self.data = json.dumps(
            {
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "source_id": "22222222-2222-2222-2222-222222222222",
                "source_type": "calendar",
                "request_id": "req_lease_test",
                "sync_run_id": "run_lease_test",
            }
        ).encode()
        self.acks = 0

    async def ack(self) -> None:
        self.acks += 1

    async def in_progress(self) -> None:
        pass


@pytest.mark.asyncio
async def test_failed_success_callback_does_not_report_false_import_error(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: TaskAckAfterCompletion."""
    message = FakeMessage()
    statuses: list[str] = []

    async def sync(*_args, **_kwargs) -> int:
        return 1

    async def report(_task, *, status: str, **_kwargs) -> None:
        statuses.append(status)
        raise CoreStatusUnavailable("HTTP 503")

    monkeypatch.setattr(importer, "sync_calendar", sync)
    monkeypatch.setattr(importer, "report_sync_result_to_core", report)

    await importer.process(message, None)

    assert statuses == ["idle"]
    assert message.acks == 0
    assert not importer.active_syncs
