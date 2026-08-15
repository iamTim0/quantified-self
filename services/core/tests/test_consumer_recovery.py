import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import pytest
from core.events import consumer as consumer_module


class _FakeConnection:
    def __init__(self, connection_lost: asyncio.Event):
        self.connection_lost = connection_lost
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeJetStream:
    def __init__(self):
        self.streams: list[Any] = []
        self.subscriptions: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def add_stream(self, stream: Any) -> None:
        self.streams.append(stream)

    async def subscribe(self, *args: Any, **kwargs: Any) -> None:
        self.subscriptions.append((args, kwargs))


class _ConnectedFake:
    def __init__(self):
        self.jetstream_context = _FakeJetStream()
        self.closed = False

    def jetstream(self) -> _FakeJetStream:
        return self.jetstream_context

    async def close(self) -> None:
        self.closed = True


async def _wait_until(predicate: Callable[[], bool]) -> None:
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


@pytest.mark.asyncio
async def test_start_consumer_signals_disconnect_and_close(monkeypatch):
    """Verifies Fizzbee Invariant: EventualConsistency.

    The supervisor must receive both terminal connection signals so it can
    recreate the durable subscription after a broker interruption.
    """
    captured: dict[str, Any] = {}
    connection = _ConnectedFake()

    async def fake_connect(_url, **kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(consumer_module.nats, "connect", fake_connect)
    connection_lost = asyncio.Event()

    result = await consumer_module.start_consumer(connection_lost=connection_lost)

    assert result is connection
    assert captured["allow_reconnect"] is False
    assert captured["max_reconnect_attempts"] == 0
    subscription_args, subscription_kwargs = (
        connection.jetstream_context.subscriptions[0]
    )
    assert subscription_args[:2] == ("qs.ingest.>", "core_data_service_group")
    assert subscription_kwargs["cb"] is consumer_module.process_message

    await captured["disconnected_cb"]()
    assert connection_lost.is_set()

    connection_lost.clear()
    await captured["closed_cb"]()
    assert connection_lost.is_set()


@pytest.mark.asyncio
async def test_supervisor_recreates_subscription_after_connection_loss(monkeypatch):
    """Verifies Fizzbee Invariants: EventualConsistency and NoDuplicateData.

    A connection loss must cause a fresh durable subscription to be created,
    while the existing connected callback is notified for every connection.
    The stable callback and durable consumer preserve Core's idempotency path
    across redelivery.
    """
    monkeypatch.setattr(consumer_module, "RECONNECT_INITIAL_DELAY", 0)
    connections: list[_FakeConnection] = []

    async def fake_start_consumer(*, connection_lost):
        connection = _FakeConnection(connection_lost)
        connections.append(connection)
        return connection

    monkeypatch.setattr(consumer_module, "start_consumer", fake_start_consumer)
    connected: list[Any] = []
    task = asyncio.create_task(
        consumer_module.run_consumer_forever(connected.append)
    )

    try:
        await _wait_until(lambda: len(connections) == 1)
        connections[0].connection_lost.set()
        await _wait_until(lambda: len(connections) == 2)

        assert connections[0].closed is True
        assert connected == connections
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_reconnect_failures_use_bounded_exponential_backoff(monkeypatch):
    """Verifies Fizzbee Invariant: EventualConsistency.

    Repeated broker failures must continue retrying without an unbounded or
    tight loop after an established connection has been lost.
    """
    monkeypatch.setattr(consumer_module, "RECONNECT_INITIAL_DELAY", 1)
    monkeypatch.setattr(consumer_module, "RECONNECT_MAX_DELAY", 4)
    attempts: list[asyncio.Event] = []
    sleeps: list[float] = []

    async def fake_start_consumer(*, connection_lost):
        attempts.append(connection_lost)
        if len(attempts) == 1:
            connection_lost.set()
            return _FakeConnection(connection_lost)
        raise OSError("connection refused")

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(consumer_module, "start_consumer", fake_start_consumer)
    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await consumer_module.run_consumer_forever()

    assert sleeps == [1, 2, 4, 4]
    assert max(sleeps) == 4
