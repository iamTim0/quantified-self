"""Request-driven weather importer publishing exclusively through JetStream."""
import asyncio
import json
import logging
from typing import Any

import httpx
import nats
from shared_schemas import HealthServer, health_payload

from weather_importer.client import (
    DEFAULT_BASE_URL,
    DEFAULT_HOURLY_VARIABLES,
    ProviderClient,
    WeatherApiError,
)
from weather_importer.config import settings
from weather_importer.internal_auth import internal_headers
from weather_importer.sync_task import SyncTask, parse_sync_task, resolve_window
from weather_importer.transformer import transform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-weather] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
nc_client: nats.NATS | None = None


def _health_payload() -> dict[str, Any]:
    connected = nc_client is not None and nc_client.is_connected
    return health_payload(
        settings.SERVICE_NAME,
        status="ok" if connected else "degraded",
        nats_connected=connected,
    )


async def credentials(
    tenant_id: str, request_id: str, source_ref: str | None = None
) -> dict[str, Any] | None:
    """Fetch this connector's credential from Core.

    Addressed by connector id when the sync task carries one: a tenant may hold
    several connectors of this type, and the type alone would hand back an
    arbitrary one of them.
    """
    reference = source_ref or "weather"
    headers = internal_headers(request_id, tenant_id)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/token",
                headers=headers,
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not report sync result to Core: {exc}")


async def process(message: Any, connection: Any) -> None:
    task = None
    try:
        task = parse_sync_task(json.loads(message.data))
        if task is None:
            logger.warning("Missing tenant_id in weather task payload; dropping.")
            return

        secret = await credentials(task.tenant_id, task.request_id, task.source_id)
        if not secret or secret.get("status") != "active":
            logger.info(
                "[req_id=%s] No active weather connector for tenant %s; staying idle.",
                task.request_id,
                task.tenant_id,
            )
            return

        config = secret.get("config") or {}
        # Open-Meteo is what a connector reaches with nothing configured, so a
        # missing base_url is a default rather than a failure. It used to be a
        # silent `return`: the connector reported neither an import nor an error,
        # and looked simply idle forever.
        base_url = config.get("base_url") or settings.API_BASE_URL or DEFAULT_BASE_URL
        source_id = secret.get("source_id")
        if not source_id:
            logger.warning(
                "[req_id=%s] Core returned no source_id for tenant %s; cannot key data points.",
                task.request_id,
                task.tenant_id,
            )
            await report_sync_result_to_core(
                task, status="error", message="Connector has no source_id."
            )
            return

        window_start, window_end = resolve_window(task, config)
        variables = config.get("hourly_variables")
        client = ProviderClient(
            base_url,
            # Open-Meteo needs no credential; only send one if configured.
            secret.get("access_token"),
            latitude=config.get("latitude"),
            longitude=config.get("longitude"),
            variables=tuple(variables) if variables else DEFAULT_HOURLY_VARIABLES,
            # Expert mode: the user supplied a complete URL, query included, and it
            # is used as written rather than rebuilt from a location.
            request_url=config.get("request_url"),
        )

        logger.info(
            "[req_id=%s] Fetching weather for tenant=%s window=%s..%s",
            task.request_id,
            task.tenant_id,
            window_start.date().isoformat(),
            window_end.date().isoformat(),
        )
        records = await client.fetch(
            start_date=window_start.date().isoformat(),
            end_date=window_end.date().isoformat(),
        )

        published = 0
        stream = connection.jetstream()
        for event in transform(records, task.tenant_id, source_id):
            event["request_id"] = task.request_id
            if task.sync_run_id:
                event["sync_run_id"] = task.sync_run_id
            await stream.publish("qs.ingest.weather", json.dumps(event).encode())
            published += 1

        logger.info(
            "[req_id=%s] Published %d weather events to JetStream", task.request_id, published
        )
        await report_sync_result_to_core(
            task,
            status="idle",
            message=f"{published} weather data point(s) published.",
            points_received=published,
        )

    except WeatherApiError as exc:
        logger.error("[req_id=%s] Weather sync failed: %s", getattr(task, "request_id", "?"), exc)
        if task:
            await report_sync_result_to_core(task, status="error", message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001
        logger.error(f"Error processing weather task: {exc}")
        if task:
            await report_sync_result_to_core(
                task, status="error", message=f"Unexpected error: {type(exc).__name__}"
            )
    finally:
        await message.ack()


async def main() -> None:
    global nc_client
    logger.info("Starting Weather Importer Service...")
    health_server = HealthServer(settings.HEALTH_PORT, _health_payload)
    await health_server.start()
    nc_client = await nats.connect(settings.NATS_URL)
    try:
        stream = nc_client.jetstream()
        try:
            await stream.add_stream(name="tasks", subjects=["qs.task.sync.>"])
        except Exception:  # noqa: BLE001, S110
            pass
        await stream.subscribe(
            "qs.task.sync.weather",
            queue="weather_importer_task_group",
            cb=lambda msg: process(msg, nc_client),
        )
        logger.info("Subscribed to NATS subject 'qs.task.sync.weather'")
        await asyncio.Event().wait()
    finally:
        if nc_client is not None and not nc_client.is_closed:
            await nc_client.close()
        nc_client = None
        await health_server.close()


if __name__ == "__main__":
    asyncio.run(main())
