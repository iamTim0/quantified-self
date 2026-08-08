"""Core must serve HTTP whether or not NATS is reachable.

Ingestion depends on the broker. Queries, authentication and the dashboard do
not, and conflating the two turns a broker outage into a full outage.

This was not hypothetical: `nats.connect` retries sixty times two seconds apart
before raising, and the lifespan awaited it, so an unreachable broker held Core's
startup for two minutes with nothing answering `/health`. The surrounding
`except Exception: yield` was written to prevent precisely that and could not,
because the call blocks rather than raising. It surfaced as a CI job that timed
out with no obvious cause.

Maps to Fizzbee Invariants:
- ServiceDegradesRatherThanFails
"""

import asyncio
import time

import pytest
from core.events import consumer as consumer_module


@pytest.mark.asyncio
async def test_a_single_connect_attempt_does_not_retry_internally(monkeypatch):
    """start_consumer must fail fast; retrying is run_consumer_forever's job.

    Asserted on the arguments rather than by timing, so the test does not depend
    on how long a connection refusal takes on the machine running it.
    """
    captured: dict = {}

    async def fake_connect(url, **kwargs):
        captured.update(kwargs)
        raise OSError("Connection refused")

    monkeypatch.setattr(consumer_module.nats, "connect", fake_connect)

    with pytest.raises(OSError):
        await consumer_module.start_consumer()

    assert captured["max_reconnect_attempts"] == 0
    assert captured["allow_reconnect"] is False
    assert captured["connect_timeout"] == consumer_module.CONNECT_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_the_retry_loop_keeps_going_and_backs_off(monkeypatch):
    """A broker that is down must not stop the loop, and must not be hammered."""
    attempts = 0
    slept: list[float] = []

    async def flaky():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("Connection refused")
        return "connection"

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(consumer_module, "start_consumer", flaky)
    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    connected: list = []
    await consumer_module.run_consumer_forever(connected.append)

    assert attempts == 3
    assert connected == ["connection"]
    # Backs off rather than spinning: a tight loop against a restarting broker is
    # its own denial of service.
    assert slept == [1.0, 2.0]


@pytest.mark.asyncio
async def test_backoff_is_capped(monkeypatch):
    """Otherwise a long outage pushes the retry interval to hours."""
    slept: list[float] = []

    async def always_fails():
        raise OSError("Connection refused")

    async def fake_sleep(seconds):
        slept.append(seconds)
        if len(slept) >= 12:
            raise asyncio.CancelledError

    monkeypatch.setattr(consumer_module, "start_consumer", always_fails)
    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await consumer_module.run_consumer_forever()

    assert max(slept) == consumer_module.RECONNECT_MAX_DELAY


@pytest.mark.asyncio
async def test_the_app_starts_and_serves_while_the_broker_is_unreachable(monkeypatch):
    """The whole point: /health answers immediately with no broker.

    Runs the real lifespan with a NATS URL pointing at a closed port. If the
    consumer were awaited again, this would take minutes instead of a moment.
    """
    from core.main import app
    from httpx import ASGITransport, AsyncClient

    # A port nothing is listening on.
    monkeypatch.setattr(consumer_module.settings, "NATS_URL", "nats://127.0.0.1:14222")
    # Exercise the real lifespan, not the testing short-circuit.
    monkeypatch.setattr(app.state, "testing", False, raising=False)
    monkeypatch.setattr(
        __import__("core.config", fromlist=["settings"]).settings,
        "SCHEDULER_ENABLED",
        False,
    )

    started = time.monotonic()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as ac:
        response = await ac.get("/health")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    # Generous, but far below the two minutes the previous behaviour took.
    assert elapsed < 20, f"startup took {elapsed:.1f}s with the broker down"
