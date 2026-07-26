"""Oura Ring Importer Main Service Entry Point.

Orchestrates periodic polling of Oura API v2 (daily_sleep, daily_readiness, daily_activity),
transforms raw JSON into standard DataPoints with deterministic SHA256 idempotency_keys,
and publishes IngestEvent payloads to NATS JetStream subject 'qs.ingest.oura'.

If no live Oura token is set, operates in fallback seed mode to support local dev testing.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import nats
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from oura_importer.client import (
    OuraApiError,
    OuraClient,
    OuraRateLimitError,
    OuraUnauthorizedError,
)
from oura_importer.config import settings
from oura_importer.seed import seed_data
from oura_importer.transformer import (
    transform_activity_data,
    transform_readiness_data,
    transform_sleep_data,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def fetch_and_publish(nc: nats.NATS):
    """Poll Oura API for sleep, readiness, and activity, and publish to NATS."""
    if not settings.OURA_ACCESS_TOKEN or settings.OURA_ACCESS_TOKEN.startswith("your_"):
        logger.warning("No valid OURA_ACCESS_TOKEN found in environment. Running seed data generator instead...")
        await seed_data(days=30)
        return

    logger.info("Polling Oura API v2 for daily metrics...")
    client = OuraClient()
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
