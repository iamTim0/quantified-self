import asyncio

import pytest
from shared_schemas.health_server import HealthServer
from shared_schemas.service_metadata import (
    health_payload,
    service_version,
    source_commit,
)


def test_service_metadata_uses_development_defaults(monkeypatch):
    monkeypatch.delenv("QS_SERVICE_VERSION", raising=False)
    monkeypatch.delenv("QS_SOURCE_COMMIT", raising=False)

    assert service_version() == "dev"
    assert source_commit() == "unknown"


def test_empty_metadata_environment_values_use_development_defaults(monkeypatch):
    monkeypatch.setenv("QS_SERVICE_VERSION", "")
    monkeypatch.setenv("QS_SOURCE_COMMIT", "")

    assert service_version() == "dev"
    assert source_commit() == "unknown"


def test_health_payload_contains_release_metadata(monkeypatch):
    monkeypatch.setenv("QS_SERVICE_VERSION", "0.3.0")
    monkeypatch.setenv("QS_SOURCE_COMMIT", "abc123")

    assert health_payload("qs-example", components={"nats": "ok"}) == {
        "status": "ok",
        "service": "qs-example",
        "version": "0.3.0",
        "commit": "abc123",
        "components": {"nats": "ok"},
    }


@pytest.mark.asyncio
async def test_worker_health_server_returns_uncached_json():
    server = HealthServer(
        0,
        lambda: {
            "status": "degraded",
            "service": "qs-worker",
            "version": "dev",
            "commit": "unknown",
        },
        host="127.0.0.1",
    )
    await server.start()
    assert server._server is not None
    port = server._server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    await server.close()

    assert b"503 Service Unavailable" in response
    assert b"Cache-Control: no-store" in response
    assert b'"service":"qs-worker"' in response
