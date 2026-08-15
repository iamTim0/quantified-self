"""Small dependency-free HTTP server for worker health endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any

HealthPayload = Callable[[], Mapping[str, Any]]


class HealthServer:
    """Serve a local, unauthenticated JSON health endpoint.

    This is intentionally smaller than adding an HTTP framework to a NATS-only
    worker. The endpoint has no application routes and never reads tenant or
    provider state. A ``degraded`` payload becomes HTTP 503 so Docker and the
    Gateway can distinguish a live process from a worker that cannot reach NATS.
    """

    def __init__(self, port: int, payload: HealthPayload, *, host: str = "0.0.0.0") -> None:
        self._host = host
        self._port = port
        self._payload = payload
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Start listening for local health probes."""
        self._server = await asyncio.start_server(self._handle, self._host, self._port)

    async def close(self) -> None:
        """Stop accepting probes and release the listening socket."""
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=2.0)
            method, path, *_ = request_line.decode("ascii", errors="replace").split()
            route = path.split("?", 1)[0]
            if route != "/health" or method not in {"GET", "HEAD"}:
                self._write_response(writer, 404, {"status": "not_found"})
                return

            payload = dict(self._payload())
            status_code = 200 if payload.get("status") == "ok" else 503
            self._write_response(writer, status_code, payload, head=method == "HEAD")
        except (asyncio.TimeoutError, UnicodeError, ValueError):
            self._write_response(writer, 400, {"status": "bad_request"})
        finally:
            try:
                await writer.drain()
            except (ConnectionError, RuntimeError):
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, RuntimeError):
                pass

    @staticmethod
    def _write_response(
        writer: asyncio.StreamWriter,
        status_code: int,
        payload: Mapping[str, Any],
        *,
        head: bool = False,
    ) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 503: "Service Unavailable"}[status_code]
        headers = (
            f"HTTP/1.1 {status_code} {reason}\r\n"
            "Content-Type: application/json\r\n"
            "Cache-Control: no-store\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        writer.write(headers if head else headers + body)
