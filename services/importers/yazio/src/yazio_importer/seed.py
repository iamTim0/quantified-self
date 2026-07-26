"""Yazio Importer Seed Data Generator.

Generates 30 days of realistic mock Yazio diary metrics (calories, protein, carbs, fat, fiber)
and publishes them to NATS subject 'qs.ingest.yazio'.

USAGE:
    python -m yazio_importer.seed
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, timezone

import nats

from yazio_importer.config import settings
from yazio_importer.transformer import transform_consumed_items

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def generate_mock_yazio_day(day_str: str) -> dict:
    """Generate mock Yazio consumed items document for a given date."""
    base_calories = random.randint(1800, 2500)
    protein = random.randint(100, 160)
    carbs = random.randint(180, 280)
    fat = random.randint(50, 85)
    fiber = random.randint(22, 38)

    breakfast_cal = int(base_calories * 0.25)
    lunch_cal = int(base_calories * 0.40)
    dinner_cal = int(base_calories * 0.25)
    snack_cal = base_calories - breakfast_cal - lunch_cal - dinner_cal

    return {
        "summary": {
            "calories": float(base_calories),
            "protein_g": float(protein),
            "carbs_g": float(carbs),
            "fat_g": float(fat),
            "fiber_g": float(fiber),
        },
        "meals": {
            "breakfast": {"calories": float(breakfast_cal)},
            "lunch": {"calories": float(lunch_cal)},
            "dinner": {"calories": float(dinner_cal)},
            "snack": {"calories": float(snack_cal)},
        },
        "items": [
            {
                "id": f"seed_b1_{day_str}",
                "name": "Oatmeal with Berries & Protein Powder",
                "category": "breakfast",
                "calories": float(breakfast_cal),
                "amount": 1,
                "unit": "bowl",
                "protein_g": 30.0,
                "carbs_g": 55.0,
                "fat_g": 8.0,
            },
            {
                "id": f"seed_l1_{day_str}",
                "name": "Chicken Rice Bowl",
                "category": "lunch",
                "calories": float(lunch_cal),
                "amount": 1,
                "unit": "serving",
                "protein_g": 50.0,
                "carbs_g": 70.0,
                "fat_g": 18.0,
            },
            {
                "id": f"seed_d1_{day_str}",
                "name": "Salmon Fillet with Sweet Potato",
                "category": "dinner",
                "calories": float(dinner_cal),
                "amount": 1,
                "unit": "plate",
                "protein_g": 40.0,
                "carbs_g": 45.0,
                "fat_g": 22.0,
            },
            {
                "id": f"seed_s1_{day_str}",
                "name": "Greek Yogurt Snack",
                "category": "snack",
                "calories": float(snack_cal),
                "amount": 150,
                "unit": "g",
                "protein_g": 15.0,
                "carbs_g": 10.0,
                "fat_g": 4.0,
            },
        ],
    }


async def main():
    logger.info("Connecting to NATS for seeding Yazio data...")
    nc = await nats.connect(settings.NATS_URL)
    js = nc.jetstream()

    now = datetime.now(timezone.utc)
    total_dps = 0

    for d in range(30):
        day_str = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        mock_data = generate_mock_yazio_day(day_str)
        data_points = transform_consumed_items(
            raw_data=mock_data,
            day=day_str,
            tenant_id=settings.TENANT_ID,
            source_id="yazio_mock_seed",
        )

        for dp in data_points:
            payload = json.dumps(dp).encode("utf-8")
            await js.publish("qs.ingest.yazio", payload)
            total_dps += 1

    logger.info(f"Successfully seeded {total_dps} Yazio DataPoints across 30 days.")
    await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
