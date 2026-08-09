"""Request-driven Home Assistant importer publishing exclusively through JetStream."""
import asyncio
import json
import logging
from typing import Any

import httpx
import nats

from home_assistant_importer.client import HomeAssistantApiError, ProviderClient
from home_assistant_importer.config import settings
from home_assistant_importer.internal_auth import internal_headers
from home_assistant_importer.sync_task import SyncTask, parse_sync_task, resolve_window
from home_assistant_importer.transformer import transform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-home_assistant] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def credentials(
    tenant_id: str, request_id: str, source_ref: str | None = None
) -> dict[str, Any] | None:
    """Fetch this connector's credential from Core.

    Addressed by connector id when the sync task carries one: a tenant may hold
    several connectors of this type, and the type alone would hand back an
    arbitrary one of them.
    """
    reference = source_ref or "home_assistant"
    headers = internal_headers(request_id, tenant_id)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/token",
                headers=headers,
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.warning(f"[req_id={request_id}] Failed to fetch credentials for tenant {tenant_id}: {e}")
            return None


async def report_sync_result_to_core(
    task: SyncTask, *, status: str, message: str, points_received: int | None = None
) -> None:
    """Close out the sync run so Core can advance the adaptive resume point."""
    url = (
        f"{settings.CORE_SERVICE_URL}"
        f"/api/v1/internal/data/sources/{task.source_id or task.source_type}/status"
    )
    payload: dict[str, Any] = {
        "sync_status": status,
        "last_sync_message": message,
        "sync_run_id": task.sync_run_id,
    }
    if points_received is not None:
        payload["points_received"] = points_received
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            await client.post(
                url, headers=internal_headers(task.request_id, task.tenant_id), json=payload
            )
        except Exception as exc:
            logger.warning(f"Could not report sync result to Core: {exc}")


async def process(message: Any, connection: Any) -> None:
    task = None
    try:
        task = parse_sync_task(json.loads(message.data))
        if task is None:
            logger.warning("Missing tenant_id in home_assistant task payload; dropping.")
            return

        secret = await credentials(task.tenant_id, task.request_id, task.source_id)
        if not secret or secret.get("status") != "active" or not secret.get("access_token"):
            logger.info(
                "[req_id=%s] No active Home Assistant connector for tenant %s; staying idle.",
                task.request_id,
                task.tenant_id,
            )
            return

        config = secret.get("config") or {}
        base_url = config.get("base_url") or settings.API_BASE_URL
        source_id = secret.get("source_id")
        if not base_url or not source_id:
            return

        window_start, window_end = resolve_window(task, config)
        client = ProviderClient(
            base_url,
            secret["access_token"],
            entity_ids=config.get("entity_ids") or [],
        )

        logger.info(
            "[req_id=%s] Fetching Home Assistant history for tenant=%s window=%s..%s",
            task.request_id,
            task.tenant_id,
            window_start.isoformat(),
            window_end.isoformat(),
        )
        records = await client.fetch(
            start_time=window_start.isoformat(), end_time=window_end.isoformat()
        )

        published = 0
        stream = connection.jetstream()
        for event in transform(records, task.tenant_id, source_id):
            event["request_id"] = task.request_id
            if task.sync_run_id:
                event["sync_run_id"] = task.sync_run_id
            await stream.publish("qs.ingest.home_assistant", json.dumps(event).encode())
            published += 1

        logger.info(
            "[req_id=%s] Published %d home_assistant events to JetStream",
            task.request_id,
            published,
        )
        await report_sync_result_to_core(
            task,
            status="idle",
            message=f"{published} Home Assistant data point(s) published.",
            points_received=published,
        )

    except HomeAssistantApiError as exc:
        logger.error(
            "[req_id=%s] Home Assistant sync failed: %s", getattr(task, "request_id", "?"), exc
        )
        if task:
            await report_sync_result_to_core(task, status="error", message=str(exc)[:500])
    except Exception as exc:
        logger.error(f"Error processing home_assistant task: {exc}")
        if task:
            await report_sync_result_to_core(
                task, status="error", message=f"Unexpected error: {type(exc).__name__}"
            )
    finally:
        await message.ack()


async def main() -> None:
    logger.info("Starting Home Assistant Importer Service...")
    connection = await nats.connect(settings.NATS_URL)
    stream = connection.jetstream()
    try:
        await stream.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception:
        pass
    await stream.subscribe(
        "qs.task.sync.home_assistant",
        queue="home_assistant_importer_task_group",
        cb=lambda msg: process(msg, connection),
    )
    logger.info("Subscribed to NATS subject 'qs.task.sync.home_assistant'")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
