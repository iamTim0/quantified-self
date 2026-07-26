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
from datetime import datetime, timedelta, timezone

import httpx
import nats
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def get_connector_token_from_core(tenant_id: str, req_id: str = "req_importer_poll") -> str | None:
    """Fetch decrypted access token for Oura connector from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/oura/token"
    headers = {"X-Tenant-ID": tenant_id, "X-Request-ID": req_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active" and data.get("access_token"):
                    return data["access_token"]
            return None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None


async def fetch_and_publish(nc: nats.NATS):
    """Poll Oura API for sleep, readiness, and activity, and publish to NATS."""
    token = await get_connector_token_from_core(settings.TENANT_ID)

    if not token:
        logger.info(
            f"No active Oura connector configured in Dashboard UI for tenant '{settings.TENANT_ID}'. "
            "Waiting for token configuration via Dashboard UI..."
        )
        return

    logger.info(f"Polling Oura API v2 for daily metrics (tenant={settings.TENANT_ID})...")
    client = OuraClient(access_token=token)
    js = nc.jetstream()

    # Poll lookback window configured in settings to ensure temporal overlap and backfill missing data
    start_date = (datetime.now(timezone.utc) - timedelta(days=settings.POLL_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

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


async def main():
    logger.info(f"Starting Oura Ring Importer Service (tenant={settings.TENANT_ID})...")
    nc = await nats.connect(settings.NATS_URL)
    logger.info(f"Connected to NATS at {settings.NATS_URL}")

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        fetch_and_publish,
        "interval",
        seconds=settings.POLL_INTERVAL_SECONDS,
        args=[nc],
    )
    scheduler.start()
    logger.info(f"Started scheduler (interval: {settings.POLL_INTERVAL_SECONDS}s).")

    # Trigger immediate sync on service startup
    await fetch_and_publish(nc)

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping Oura Importer Service...")
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
