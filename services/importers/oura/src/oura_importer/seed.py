"""Mock Data Seed Generator for Oura Ring.

Generates 30 days of realistic time-series metrics (Sleep Score, HRV, Daily Steps, Readiness, Activity Score)
and publishes them to NATS JetStream subject 'qs.ingest.oura'.

Used for local development, UI dashboard testing, and integration verification
without requiring live Oura Ring API tokens.
"""

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
import nats

from oura_importer.config import settings
from oura_importer.transformer import generate_idempotency_key

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def seed_data(days: int = 30, tenant_id: str = settings.TENANT_ID, source_id: str = settings.SOURCE_ID):
    logger.info(f"Connecting to NATS JetStream at {settings.NATS_URL}...")
    nc = await nats.connect(settings.NATS_URL)
    js = nc.jetstream()

    # Ensure stream & purge old invalid messages
    try:
        await js.add_stream(name="ingestion", subjects=["qs.ingest.>"])
        await js.purge_stream("ingestion")
        logger.info("JetStream 'ingestion' stream initialized and purged.")
    except Exception as e:
        logger.info(f"Stream check: {e}")

    now = datetime.now(timezone.utc)
    published_count = 0

    logger.info(f"Generating {days} days of realistic Oura time-series data for tenant={tenant_id}...")

    for i in range(days, -1, -1):
        target_date = now - timedelta(days=i)
        day_str = target_date.strftime("%Y-%m-%d")
        timestamp_iso = f"{day_str}T00:00:00Z"

        # Realistic correlated metrics
        sleep_score = round(random.uniform(72.0, 94.0), 1)
        readiness_score = round(random.uniform(70.0, 95.0), 1)
        activity_score = round(random.uniform(65.0, 92.0), 1)
        steps = random.randint(5500, 14500)
        resting_hr = round(random.uniform(52.0, 64.0), 1)
        hrv_balance = round(random.uniform(45.0, 85.0), 1)
        total_sleep_sec = random.randint(23400, 29800)  # 6.5 - 8.2 hours
        deep_sleep_sec = random.randint(4500, 9000)
        rem_sleep_sec = random.randint(5400, 10800)
        active_cal = random.randint(350, 850)

        daily_metrics = {
            "sleep_score": sleep_score,
            "readiness_score": readiness_score,
            "activity_score": activity_score,
            "steps": steps,
            "resting_hr": resting_hr,
            "hrv_balance": hrv_balance,
            "total_sleep_duration": total_sleep_sec,
            "deep_sleep_duration": deep_sleep_sec,
            "rem_sleep_duration": rem_sleep_sec,
            "active_calories": active_cal,
        }

        for metric_type, value in daily_metrics.items():
            key = generate_idempotency_key(tenant_id, source_id, metric_type, timestamp_iso)
            
            event = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": metric_type,
                "timestamp": timestamp_iso,
                "value": float(value),
                "metadata": {
                    "source_type": "oura",
                    "day": day_str,
                    "is_simulated": True,
                },
                "idempotency_key": key,
                "source_type": "oura",
            }

            payload = json.dumps(event).encode("utf-8")
            await js.publish("qs.ingest.oura", payload)
            published_count += 1

    logger.info(f"Successfully published {published_count} IngestEvent metrics to NATS subject 'qs.ingest.oura'.")
    await nc.close()

if __name__ == "__main__":
    asyncio.run(seed_data(days=30))
