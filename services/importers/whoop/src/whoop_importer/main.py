"""WHOOP Importer Main Service Entry Point.

Orchestrates task-driven polling of WHOOP API v2, transforms recovery, sleep,
strain, and workout records into standard DataPoints with SHA256 idempotency_keys,
and publishes to NATS subject 'qs.ingest.whoop'.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import nats
import uvicorn

from whoop_importer.client import (
    WhoopApiError,
    WhoopClient,
    WhoopRateLimitError,
    WhoopUnauthorizedError,
)
from whoop_importer.config import settings
from whoop_importer.internal_auth import internal_headers
from whoop_importer.sync_task import SyncTask, parse_sync_task, resolve_window
from whoop_importer.transformer import transform_whoop_records
from whoop_importer.web import app as web_app


def _get_log_dir() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "logs").is_dir() or ((parent / "pyproject.toml").exists() and parent.name == "quantified-self"):
            log_dir = parent / "logs"
            log_dir.mkdir(exist_ok=True)
            return log_dir
    log_dir = Path.cwd() / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def _setup_importer_logging():
    """Configure log output for WHOOP importer service."""
    _log_dir = _get_log_dir()

    log_format = "%(asctime)s [qs-importer-whoop] [%(levelname)s] %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stdout_handler]
    root.setLevel(logging.INFO)


_setup_importer_logging()
logger = logging.getLogger(__name__)

active_syncs: set[str] = set()


async def report_sync_result_to_core(
    task: SyncTask,
    *,
    status: str,
    message: str,
    points_received: int | None = None,
):
    """Close out the sync run in Core.

    Only a run Core sees reach success moves the adaptive-window resume point
    forward, so reporting the outcome is what keeps the next window correct.
    """
    url = (
        f"{settings.CORE_SERVICE_URL}"
        f"/api/v1/internal/data/sources/{task.source_id or task.source_type}/status"
    )
    headers = internal_headers(task.request_id, task.tenant_id)
    payload: dict[str, Any] = {
        "sync_status": status,
        "last_sync_message": message,
        "sync_run_id": task.sync_run_id,
    }
    if points_received is not None:
        payload["points_received"] = points_received

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=headers, json=payload)
        except Exception as e:
            logger.warning(f"Could not report sync result to Core: {e}")


async def get_connector_credentials_from_core(
    tenant_id: str,
    req_id: str = "req_importer_poll",
    source_ref: str | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted WHOOP OAuth access token & source_id from Core Data Service DB."""
    # Addressed by connector id when the sync task carries one: a tenant may
    # hold several connectors of this type, and the bare type would hand back
    # an arbitrary one of them.
    reference = source_ref or "whoop"
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/token"
    headers = internal_headers(req_id, tenant_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    # No synthetic fallback. It used to be
                    # `uuid5(NAMESPACE_DNS, f"{tenant_id}:<type>")`, which collapsed
                    # every instance of a type onto one id -- and that id is the
                    # second component of every idempotency key, so two connectors
                    # would have written into a single indistinguishable series.
                    source_id = data.get("source_id")
                    if not source_id:
                        logger.warning(
                            "Core returned no source_id for tenant %s; refusing to guess one.",
                            tenant_id,
                        )
                        return None, None, None
                    return data["access_token"], source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None


async def fetch_and_publish(
    nc: nats.NATS,
    task: SyncTask,
    source_id: str,
    access_token: str,
    config: dict[str, Any],
):
    """Poll the WHOOP API over the window Core chose and publish to NATS."""
    tenant_id = task.tenant_id
    base_url = config.get("base_url") or settings.WHOOP_API_BASE_URL
    start_time, end_time = resolve_window(task, config)

    logger.info(
        "[req_id=%s] Polling WHOOP for tenant=%s window=%s..%s mode=%s",
        task.request_id,
        tenant_id,
        start_time.isoformat(),
        end_time.isoformat(),
        task.mode,
    )

    client = WhoopClient(access_token=access_token, base_url=base_url)
    js = nc.jetstream()

    try:
        cycles = await client.get_cycles(start=start_time, end=end_time)
        recoveries = await client.get_recoveries(start=start_time, end=end_time)
        sleeps = await client.get_sleeps(start=start_time, end=end_time)
        workouts = await client.get_workouts(start=start_time, end=end_time)

        all_points = []
        all_points.extend(transform_whoop_records("cycle", cycles, tenant_id, source_id))
        all_points.extend(transform_whoop_records("recovery", recoveries, tenant_id, source_id))
        all_points.extend(transform_whoop_records("sleep", sleeps, tenant_id, source_id))
        all_points.extend(transform_whoop_records("workout", workouts, tenant_id, source_id))

        published_count = 0
        for dp in all_points:
            # Correlation and run attribution travel with the event so Core can
            # tally accepted/duplicate against the run that asked for this data.
            dp["request_id"] = task.request_id
            dp["source_type"] = "whoop"
            if task.sync_run_id:
                dp["sync_run_id"] = task.sync_run_id
            await js.publish("qs.ingest.whoop", json.dumps(dp).encode("utf-8"))
            published_count += 1

        logger.info(
            "[req_id=%s] Published %d WHOOP DataPoints to 'qs.ingest.whoop'.",
            task.request_id,
            published_count,
        )
        await report_sync_result_to_core(
            task,
            status="idle",
            message=f"{published_count} data point(s) published from WHOOP.",
            points_received=published_count,
        )
    except WhoopUnauthorizedError:
        err_msg = "HTTP 401 Unauthorized: Stored WHOOP OAuth Token is invalid or expired."
        logger.error("[req_id=%s] WHOOP API 401 for tenant %s.", task.request_id, tenant_id)
        await report_sync_result_to_core(task, status="error", message=err_msg)
    except (WhoopRateLimitError, WhoopApiError) as e:
        logger.error("[req_id=%s] Failed to fetch WHOOP metrics: %s", task.request_id, e)
        await report_sync_result_to_core(
            task, status="error", message=f"WHOOP API error: {e}"[:500]
        )


async def process_task_message(msg, nc: nats.NATS):
    try:
        task = parse_sync_task(json.loads(msg.data.decode("utf-8")))
        if task is None:
            logger.warning("Missing tenant_id in task payload; dropping.")
            await msg.ack()
            return

        tenant_id = task.tenant_id
        # Keyed on the connector instance, not the tenant. Keyed on the tenant,
        # a user's second connector of this type had its task discarded as a
        # "duplicate" whenever the first was still running.
        lock_key = f"{tenant_id}:{task.source_id or task.source_type}"
        if lock_key in active_syncs:
            logger.info("Sync already in progress for tenant, skipping duplicate task")
            await msg.ack()
            return

        active_syncs.add(lock_key)
        try:
            token, source_id, config = await get_connector_credentials_from_core(
                tenant_id, req_id=task.request_id, source_ref=task.source_id
            )
            if not token or not source_id:
                logger.info(
                    f"No active WHOOP connector configured in Dashboard UI for tenant '{tenant_id}'. "
                    "Waiting for OAuth Token configuration via Dashboard UI..."
                )
                return

            await fetch_and_publish(nc, task, source_id, token, config or {})
        finally:
            active_syncs.discard(lock_key)
            await msg.ack()
    except Exception as e:
        logger.error(f"Error processing task message: {e}")


async def main():
    logger.info("Starting WHOOP Importer Service; awaiting sync tasks on NATS...")
    nc = await nats.connect(settings.NATS_URL)
    logger.info(f"Connected to NATS at {settings.NATS_URL}")

    js = nc.jetstream()
    try:
        await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception as e:
        logger.info(f"Stream 'tasks' check: {e}")

    await js.subscribe(
        "qs.task.sync.whoop",
        queue="whoop_importer_task_group",
        cb=lambda msg: process_task_message(msg, nc),
    )
    logger.info(
        "Subscribed to NATS subject 'qs.task.sync.whoop' (queue group: 'whoop_importer_task_group')"
    )

    # One process, one NATS client, two ways in: tasks arrive on the broker, export
    # archives arrive over HTTP. Serving the upload endpoint replaces the idle wait
    # that used to keep this service alive doing nothing.
    web_app.state.nats_client = nc
    server = uvicorn.Server(
        uvicorn.Config(web_app, host="0.0.0.0", port=settings.PORT, log_config=None)
    )
    logger.info(f"Serving the export upload endpoint on port {settings.PORT}")

    try:
        await server.serve()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping WHOOP Importer Service...")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
