"""Regression tests for the import-task lease lifecycle."""

from __future__ import annotations

import asyncio

import pytest
from shared_schemas.core_status import CoreStatusUnavailable
from shared_schemas.task_lease import (
    finish_task_delivery,
    should_ack_task,
    start_task_heartbeat,
)


class FakeMessage:
    def __init__(self) -> None:
        self.progress = 0
        self.acks = 0

    async def in_progress(self) -> None:
        self.progress += 1

    async def ack(self) -> None:
        self.acks += 1


@pytest.mark.asyncio
async def test_heartbeat_renews_until_the_task_finishes() -> None:
    """Verifies Fizzbee Invariant: ProgressDoesNotCompleteTask."""
    message = FakeMessage()
    heartbeat = start_task_heartbeat(message, "req_test", interval_seconds=0.01)
    await asyncio.sleep(0.035)
    assert message.progress >= 2
    assert message.acks == 0

    await finish_task_delivery(message, heartbeat)
    progress_at_finish = message.progress
    await asyncio.sleep(0.025)
    assert message.progress == progress_at_finish
    assert message.acks == 1


@pytest.mark.asyncio
async def test_cancelled_import_is_not_acknowledged() -> None:
    """Verifies Fizzbee Invariant: TaskAckAfterCompletion."""
    message = FakeMessage()

    async def importer() -> None:
        heartbeat = start_task_heartbeat(message, "req_test", interval_seconds=0.01)
        try:
            await asyncio.sleep(10)
        finally:
            await finish_task_delivery(message, heartbeat)

    task = asyncio.create_task(importer())
    await asyncio.sleep(0.025)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert message.acks == 0


@pytest.mark.asyncio
async def test_status_callback_failure_is_not_acknowledged() -> None:
    """Verifies Fizzbee Invariant: TaskAckAfterCompletion."""
    message = FakeMessage()
    heartbeat = start_task_heartbeat(message, "req_test", interval_seconds=0.01)
    with pytest.raises(CoreStatusUnavailable):
        try:
            raise CoreStatusUnavailable("HTTP 503")
        finally:
            await finish_task_delivery(message, heartbeat, acknowledge=should_ack_task())
    assert message.acks == 0
