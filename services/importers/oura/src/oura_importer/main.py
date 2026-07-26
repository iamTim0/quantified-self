"""Oura Ring Importer Main Service Entry Point.

Orchestrates periodic polling of Oura API v2 (daily_sleep, daily_readiness, daily_activity),
transforms raw JSON into standard DataPoints with deterministic SHA256 idempotency_keys,
and publishes IngestEvent payloads to NATS JetStream subject 'qs.ingest.oura'.

NOTE: Access tokens are fetched dynamically from Core Data Service DB (configured via Dashboard UI),
never hardcoded in .env files. Zero auto-seed fallback.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

import httpx
import nats

from oura_importer.client import (
    OuraApiError,
    OuraClient,
    OuraRateLimitError,
    OuraUnauthorizedError,
)
from oura_importer.config import settings
from oura_importer.transformer import (
    transform_activity_data,
    transform_readiness_data,
    transform_sleep_data,
)

def _setup_importer_logging():
    """Configure rotating file log handlers for the Oura importer service.

    Registers three handlers on the root logger:
    - stdout StreamHandler for live console output
    - RotatingFileHandler for service-specific log file (logs/qs-importer-oura.log)
    - RotatingFileHandler for aggregated platform log (logs/qs-platform.log)
    """
    os.makedirs('logs', exist_ok=True)
    log_format = '%(asctime)s [qs-importer-oura] [%(levelname)s] %(message)s'
    formatter = logging.Formatter(log_format, datefmt='%Y-%m-%d %H:%M:%S')

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)

    service_handler = RotatingFileHandler('logs/qs-importer-oura.log', maxBytes=10*1024*1024, backupCount=5)
    service_handler.setFormatter(formatter)

    platform_handler = RotatingFileHandler('logs/qs-platform.log', maxBytes=10*1024*1024, backupCount=5)
    platform_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stdout_handler, service_handler, platform_handler]
    root.setLevel(logging.INFO)


_setup_importer_logging()
logger = logging.getLogger(__name__)

active_syncs: set[str] = set()


async def get_connector_token_from_core(tenant_id: str, req_id: str = "req_importer_poll") -> tuple[str | None, dict | None]:
    """Fetch decrypted access token for Oura connector from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/oura/token"
    headers = {"X-Tenant-ID": tenant_id, "X-Request-ID": req_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    return data["access_token"], data.get("config", {})
            return None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None


async def fetch_and_publish(nc: nats.NATS, tenant_id: str, token: str, lookback_days: int):
    """Poll Oura API for sleep, readiness, and activity, and publish to NATS."""
    logger.info(f"Polling Oura API v2 for daily metrics (tenant={tenant_id})...")
    client = OuraClient(access_token=token)
    js = nc.jetstream()

    # Poll lookback window configured in settings to ensure temporal overlap and backfill missing data
    start_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    data_points = []

    try:
        sleep_data = await client.get_daily_sleep(start_date=start_date)
        data_points.extend(transform_sleep_data(sleep_data))
    except (OuraUnauthorizedError, OuraRateLimitError, OuraApiError) as e:
        logger.error(f"Failed to fetch Oura sleep data: {e}")

    try:
        readiness_data = await client.get_daily_readiness(start_date=start_date)
        data_points.extend(transform_readiness_data(readiness_data))
    except (OuraUnauthorizedError, OuraRateLimitError, OuraApiError) as e:
        logger.error(f"Failed to fetch Oura readiness data: {e}")

    try:
        activity_data = await client.get_daily_activity(start_date=start_date)
        data_points.extend(transform_activity_data(activity_data))
    except (OuraUnauthorizedError, OuraRateLimitError, OuraApiError) as e:
        logger.error(f"Failed to fetch Oura activity data: {e}")

    published_count = 0
    for dp in data_points:
        payload = json.dumps(dp).encode("utf-8")
        await js.publish("qs.ingest.oura", payload)
        published_count += 1

    logger.info(f"Successfully published {published_count} data points to NATS subject 'qs.ingest.oura'.")


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
            token, config = await get_connector_token_from_core(tenant_id)
            if not token:
                logger.info(
                    f"No active Oura connector configured in Dashboard UI for tenant '{tenant_id}'. "
                    "Waiting for token configuration via Dashboard UI..."
                )
                return

            config = config or {}
            lookback_days = config.get("lookback_days", settings.POLL_LOOKBACK_DAYS)
            await fetch_and_publish(nc, tenant_id, token, lookback_days)
        finally:
            active_syncs.discard(tenant_id)
            await msg.ack()
    except Exception as e:
        logger.error(f"Error processing task message: {e}")


async def main():
    logger.info(f"Starting Oura Ring Importer Service (tenant={settings.TENANT_ID})...")
    nc = await nats.connect(settings.NATS_URL)
    logger.info(f"Connected to NATS at {settings.NATS_URL}")

    js = nc.jetstream()
    try:
        await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception as e:
        logger.info(f"Stream 'tasks' check: {e}")

    await js.subscribe("qs.task.sync.oura", queue="oura_importer_task_group", cb=lambda msg: process_task_message(msg, nc))
    logger.info("Subscribed to NATS subject 'qs.task.sync.oura' (queue group: 'oura_importer_task_group')")

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping Oura Importer Service...")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
