"""Tests for tenant-scoped final sync status reporting."""

from __future__ import annotations

from typing import Any, Self

import pytest
from apple_health_importer import client as client_module


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _AsyncClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, _url: str, *, headers: dict[str, str], json: dict[str, Any]) -> Any:
        self.calls.append({"headers": headers, "json": json})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


@pytest.mark.asyncio
async def test_final_status_retries_server_failure_and_checks_success(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: TerminalRunStatusIsRetriedAndCorrelated."""
    fake = _AsyncClient([_Response(503), _Response(200)])
    monkeypatch.setattr(client_module.httpx, "AsyncClient", lambda **_kwargs: fake)
    monkeypatch.setattr(client_module.asyncio, "sleep", lambda _delay: _done())

    result = await client_module.close_sync_run(
        "tenant-a",
        "source-a",
        "run-a",
        req_id="req-a",
        status="error",
        message="safe error",
        code="payload_unrecognized",
        params={"section": "metrics"},
    )

    assert result is True
    assert len(fake.calls) == 2
    assert fake.calls[0]["json"]["sync_run_id"] == "run-a"
    assert fake.calls[0]["json"]["code"] == "payload_unrecognized"
    assert fake.calls[0]["json"]["params"] == {"section": "metrics"}
    assert fake.calls[0]["headers"]["X-Tenant-ID"] == "tenant-a"
    assert fake.calls[0]["headers"]["X-Request-ID"] == "req-a"


@pytest.mark.asyncio
async def test_final_status_returns_failure_after_transport_retries(monkeypatch) -> None:
    """A dead Core must be visible to the caller rather than acknowledged as closed."""
    fake = _AsyncClient([RuntimeError("transport") for _ in range(client_module.STATUS_REPORT_ATTEMPTS)])
    monkeypatch.setattr(client_module.httpx, "AsyncClient", lambda **_kwargs: fake)
    monkeypatch.setattr(client_module.asyncio, "sleep", lambda _delay: _done())

    result = await client_module.close_sync_run(
        "tenant-a",
        "source-a",
        "run-a",
        req_id="req-a",
        status="error",
        message="safe error",
    )

    assert result is False
    assert len(fake.calls) == client_module.STATUS_REPORT_ATTEMPTS


async def _done() -> None:
    return None
