
async def report_sync_error_to_core(tenant_id: str, source_type: str, error_msg: str):
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_type}/status"
    headers = internal_headers("req_importer_status", tenant_id)
    payload = {
        "sync_status": "error",
        "last_sync_message": error_msg,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=headers, json=payload)
        except Exception as e:
            logger.warning(f"Could not report sync error to Core: {e}")
"""Dawarich Importer Main Service Entry Point.

Orchestrates task-driven polling of Dawarich API, transforms GPS points into standard
DataPoints with SHA256 idempotency_keys, and publishes to NATS subject 'qs.ingest.dawarich'.
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

from dawarich_importer.client import (
    DawarichApiError,
    DawarichClient,
    DawarichRateLimitError,
    DawarichUnauthorizedError,
)
from dawarich_importer.config import settings
from dawarich_importer.internal_auth import internal_headers
from dawarich_importer.transformer import transform_dawarich_points


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
    """Configure log output for Dawarich importer service."""
    _log_dir = _get_log_dir()

    log_format = "%(asctime)s [qs-importer-dawarich] [%(levelname)s] %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stdout_handler]
    root.setLevel(logging.INFO)


_setup_importer_logging()
logger = logging.getLogger(__name__)

active_syncs: set[str] = set()


async def get_connector_credentials_from_core(
    tenant_id: str, req_id: str = "req_importer_poll"
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted API key & source_id for Dawarich connector from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/dawarich/token"
    headers = internal_headers(req_id, tenant_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    source_id = data.get("source_id") or str(
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:dawarich")
                    )
                    return data["access_token"], source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None


async def fetch_and_publish(
    nc: nats.NATS, tenant_id: str, source_id: str, api_key: str, config: dict[str, Any]
):
    """Poll Dawarich API for location points and publish to NATS."""
    logger.info(f"Polling Dawarich API for location points (tenant={tenant_id})...")
    base_url = config.get("base_url") or config.get("dawarich_url") or settings.DAWARICH_API_BASE_URL
    lookback_days = config.get("lookback_days", settings.POLL_LOOKBACK_DAYS)

    client = DawarichClient(api_key=api_key, base_url=base_url)
    js = nc.jetstream()

    now = datetime.now(timezone.utc)
    start_time = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_time = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        raw_points = await client.get_points(start_at=start_time, end_at=end_time)
        data_points = transform_dawarich_points(raw_points, tenant_id=tenant_id, source_id=source_id)

        published_count = 0
        for dp in data_points:
            payload = json.dumps(dp).encode("utf-8")
            await js.publish("qs.ingest.dawarich", payload)
            published_count += 1

        logger.info(
            f"Successfully published {published_count} location DataPoints to NATS subject 'qs.ingest.dawarich'."
        )
    except DawarichUnauthorizedError:
        err_msg = "HTTP 401 Unauthorized: Stored API Key is invalid or expired."
        logger.error(f"Dawarich API 401 Unauthorized for tenant {tenant_id}.")
        await report_sync_error_to_core(tenant_id, "dawarich", err_msg)
    except (DawarichRateLimitError, DawarichApiError) as e:
        logger.error(f"Failed to fetch Dawarich location points: {e}")


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
            api_key, source_id, config = await get_connector_credentials_from_core(tenant_id)
            if not api_key or not source_id:
                logger.info(
                    f"No active Dawarich connector configured in Dashboard UI for tenant '{tenant_id}'. "
                    "Waiting for API Key configuration via Dashboard UI..."
                )
                return

            config = config or {}
            await fetch_and_publish(nc, tenant_id, source_id, api_key, config)
        finally:
            active_syncs.discard(tenant_id)
            await msg.ack()
    except Exception as e:
        logger.error(f"Error processing task message: {e}")


async def main():
    logger.info(f"Starting Dawarich Importer Service (tenant={settings.TENANT_ID})...")
    nc = await nats.connect(settings.NATS_URL)
    logger.info(f"Connected to NATS at {settings.NATS_URL}")

    js = nc.jetstream()
    try:
        await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception as e:
        logger.info(f"Stream 'tasks' check: {e}")

    await js.subscribe(
        "qs.task.sync.dawarich",
        queue="dawarich_importer_task_group",
        cb=lambda msg: process_task_message(msg, nc),
    )
    logger.info(
        "Subscribed to NATS subject 'qs.task.sync.dawarich' (queue group: 'dawarich_importer_task_group')"
    )

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping Dawarich Importer Service...")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
