"""Core status callback retries preserve sync-run visibility."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from shared_schemas.core_status import CoreStatusUnavailable, post_status_with_retry


@dataclass
class Response:
    status_code: int


@pytest.mark.asyncio
async def test_transient_status_failure_is_retried(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: ImportCompletionAfterCoreProcessing."""

    async def no_wait(_seconds: int) -> None:
        pass

    monkeypatch.setattr("shared_schemas.core_status.asyncio.sleep", no_wait)
    responses = iter([Response(503), Response(200)])
    calls = 0

    async def send() -> Response:
        nonlocal calls
        calls += 1
        return next(responses)

    assert await post_status_with_retry(send, "req_test") is True
    assert calls == 2


@pytest.mark.asyncio
async def test_permanent_rejection_is_not_retried() -> None:
    """Verifies Fizzbee Invariant: ImportCompletionAfterCoreProcessing."""
    calls = 0

    async def send() -> Response:
        nonlocal calls
        calls += 1
        return Response(403)

    assert await post_status_with_retry(send, "req_test") is False
    assert calls == 1


@pytest.mark.asyncio
async def test_transport_error_is_retried(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: ImportCompletionAfterCoreProcessing."""

    async def no_wait(_seconds: int) -> None:
        pass

    monkeypatch.setattr("shared_schemas.core_status.asyncio.sleep", no_wait)
    calls = 0

    async def send() -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("connection closed")
        return Response(200)

    assert await post_status_with_retry(send, "req_test") is True
    assert calls == 2


@pytest.mark.asyncio
async def test_exhausted_transient_retries_leave_task_open(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: TaskAckAfterCompletion."""

    async def no_wait(_seconds: int) -> None:
        pass

    monkeypatch.setattr("shared_schemas.core_status.asyncio.sleep", no_wait)
    calls = 0

    async def send() -> Response:
        nonlocal calls
        calls += 1
        return Response(503)

    with pytest.raises(CoreStatusUnavailable):
        await post_status_with_retry(send, "req_test")
    assert calls == 3
