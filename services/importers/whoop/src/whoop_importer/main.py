"""Request-driven WHOOP FastAPI importer and NATS task consumer."""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import nats
import uvicorn
from fastapi import FastAPI

from whoop_importer.client import WhoopApiError, WhoopClient, WhoopUnauthorizedError
from whoop_importer.config import settings
from whoop_importer.transformer import transform_record

logger = logging.getLogger(__name__)
app = FastAPI(title="WHOOP Importer", docs_url=None, redoc_url=None)
active_syncs: set[str] = set()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "whoop-importer"}


async def credentials(tenant_id: str, request_id: str) -> tuple[str | None, str | None, dict[str, Any]]:
    headers = {"X-Tenant-ID": tenant_id, "X-Request-ID": request_id}
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/whoop/token"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data.get("status") == "active":
                return data.get("access_token"), data.get("source_id"), data.get("config") or {}
    except httpx.HTTPError as exc:
        logger.warning("[req_id=%s] Core credential request failed: %s", request_id, type(exc).__name__)
    return None, None, {}


async def sync(nc: Any, tenant_id: str, source_id: str, token: str, config: dict[str, Any], request_id: str) -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(config.get("lookback_days", 30)))
    js = nc.jetstream()
    count = 0
    async with WhoopClient(token, settings.WHOOP_API_BASE_URL) as client:
        for kind, records in (("cycle", client.cycles(start=start, end=end)), ("recovery", client.recoveries(start=start, end=end)), ("sleep", client.sleeps(start=start, end=end)), ("workout", client.workouts(start=start, end=end))):
            async for record in records:
                for point in transform_record(kind, record, tenant_id, source_id):
                    await js.publish("qs.ingest.whoop", json.dumps(point).encode())
                    count += 1
    logger.info("[req_id=%s] Published %d WHOOP metrics", request_id, count)


async def process_task_message(msg: Any, nc: Any) -> None:
    payload = json.loads(msg.data)
    tenant_id = payload.get("tenant_id")
    request_id = payload.get("request_id", "req_whoop_sync")
    if not tenant_id or tenant_id in active_syncs:
        await msg.ack()
        return
    active_syncs.add(tenant_id)
    try:
        token, source_id, config = await credentials(tenant_id, request_id)
        if token and source_id:
            await sync(nc, tenant_id, source_id, token, config, request_id)
    except (WhoopUnauthorizedError, WhoopApiError) as exc:
        logger.error("[req_id=%s] WHOOP sync failed: %s", request_id, exc)
    finally:
        active_syncs.discard(tenant_id)
        await msg.ack()


async def run() -> None:
    nc = await nats.connect(settings.NATS_URL)
    js = nc.jetstream()
    try:
        await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception:
        pass
    await js.subscribe("qs.task.sync.whoop", queue="whoop_importer_task_group", cb=lambda msg: process_task_message(msg, nc))
    server = uvicorn.Server(uvicorn.Config(app, host=settings.HEALTH_HOST, port=settings.HEALTH_PORT))
    try:
        await server.serve()
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(run())
