"""WHOOP Importer Main Service Entry Point.

Orchestrates task-driven polling of WHOOP API v2, transforms recovery, sleep,
strain, and workout records into standard DataPoints with SHA256 idempotency_keys,
and publishes to NATS subject 'qs.ingest.whoop'.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import nats

from whoop_importer.client import (
    WhoopApiError,
    WhoopClient,
    WhoopRateLimitError,
    WhoopUnauthorizedError,
)
from whoop_importer.config import settings
from whoop_importer.transformer import transform_whoop_records


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


async def report_sync_error_to_core(tenant_id: str, source_type: str, error_msg: str):
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_type}/status"
    headers = {"X-Tenant-ID": tenant_id}
    payload = {
        "sync_status": "error",
        "last_sync_message": error_msg,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=headers, json=payload)
        except Exception as e:
            logger.warning(f"Could not report sync error to Core: {e}")


async def get_connector_credentials_from_core(
    tenant_id: str, req_id: str = "req_importer_poll"
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted WHOOP OAuth access token & source_id from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/whoop/token"
    headers = {"X-Tenant-ID": tenant_id, "X-Request-ID": req_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    source_id = data.get("source_id") or str(
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:whoop")
                    )
                    return data["access_token"], source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None


async def fetch_and_publish(
    nc: nats.NATS, tenant_id: str, source_id: str, access_token: str, config: dict[str, Any]
):
    """Poll WHOOP API for cycles, recoveries, sleeps, workouts and publish to NATS."""
    logger.info(f"Polling WHOOP API for health metrics (tenant={tenant_id})...")
    base_url = config.get("base_url") or settings.WHOOP_API_BASE_URL
    lookback_days = config.get("lookback_days", settings.POLL_LOOKBACK_DAYS)

    client = WhoopClient(access_token=access_token, base_url=base_url)
    js = nc.jetstream()

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=lookback_days)

    try:
        cycles = await client.get_cycles(start=start_time, end=now)
        recoveries = await client.get_recoveries(start=start_time, end=now)
        sleeps = await client.get_sleeps(start=start_time, end=now)
        workouts = await client.get_workouts(start=start_time, end=now)

        all_points = []
        all_points.extend(transform_whoop_records("cycle", cycles, tenant_id, source_id))
        all_points.extend(transform_whoop_records("recovery", recoveries, tenant_id, source_id))
        all_points.extend(transform_whoop_records("sleep", sleeps, tenant_id, source_id))
        all_points.extend(transform_whoop_records("workout", workouts, tenant_id, source_id))

        published_count = 0
        for dp in all_points:
            payload = json.dumps(dp).encode("utf-8")
            await js.publish("qs.ingest.whoop", payload)
            published_count += 1

        logger.info(
            f"Successfully published {published_count} WHOOP DataPoints to NATS subject 'qs.ingest.whoop'."
        )
    except WhoopUnauthorizedError:
        err_msg = "HTTP 401 Unauthorized: Stored WHOOP OAuth Token is invalid or expired."
        logger.error(f"WHOOP API 401 Unauthorized for tenant {tenant_id}.")
        await report_sync_error_to_core(tenant_id, "whoop", err_msg)
    except (WhoopRateLimitError, WhoopApiError) as e:
        logger.error(f"Failed to fetch WHOOP metrics: {e}")


async def process_task_message(msg, nc: nats.NATS):
    try:
        payload = json.loads(msg.data.decode("utf-8"))
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            logger.warning("Missing tenant_id in task payload")
            await msg.ack()
            return

        if tenant_id in active_syncs:
            logger.info("Sync already in progress for tenant, skipping duplicate task")
            await msg.ack()
            return

        active_syncs.add(tenant_id)
        try:
            token, source_id, config = await get_connector_credentials_from_core(tenant_id)
            if not token or not source_id:
                logger.info(
                    f"No active WHOOP connector configured in Dashboard UI for tenant '{tenant_id}'. "
                    "Waiting for OAuth Token configuration via Dashboard UI..."
                )
                return

            config = config or {}
            await fetch_and_publish(nc, tenant_id, source_id, token, config)
        finally:
            active_syncs.discard(tenant_id)
            await msg.ack()
    except Exception as e:
        logger.error(f"Error processing task message: {e}")


async def main():
    logger.info(f"Starting WHOOP Importer Service (tenant={settings.TENANT_ID})...")
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

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping WHOOP Importer Service...")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
