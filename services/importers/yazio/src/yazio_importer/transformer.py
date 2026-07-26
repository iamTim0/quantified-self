"""Yazio API JSON Data Transformer.

Maps Yazio raw diary JSON documents into standardized DataPoint dictionaries.
Generates deterministic SHA256 idempotency_keys.
"""

import hashlib
from typing import Any

from yazio_importer.config import settings


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """Generate a deterministic 64-character SHA256 idempotency key."""
    raw_str = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def transform_consumed_items(
    raw_data: dict[str, Any],
    day: str,
    tenant_id: str = settings.TENANT_ID,
    source_id: str = settings.SOURCE_ID,
) -> list[dict[str, Any]]:
    """Transform Yazio consumed items document for a given date into DataPoints."""
    data_points = []
    timestamp = f"{day}T00:00:00Z"

    # 1. Daily macro summary totals
    summary = raw_data.get("summary", {})
    daily_metrics = {
        "calories": summary.get("calories"),
        "protein": summary.get("protein_g") or summary.get("protein"),
        "carbohydrates": summary.get("carbs_g") or summary.get("carbohydrates") or summary.get("carbs"),
        "fat": summary.get("fat_g") or summary.get("fat"),
        "fiber": summary.get("fiber_g") or summary.get("fiber"),
    }

    for metric_type, val in daily_metrics.items():
        if val is None:
            continue

        idempotency_key = generate_idempotency_key(
            tenant_id, source_id, metric_type, timestamp
        )

        dp = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": metric_type,
            "timestamp": timestamp,
            "value": float(val),
            "metadata": {
                "source_type": "yazio",
                "day": day,
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 2. Meal category aggregates
    meals = raw_data.get("meals", {})
    for meal_cat, meal_info in meals.items():
        if isinstance(meal_info, dict) and "calories" in meal_info:
            cal_val = meal_info["calories"]
            metric_type = f"{meal_cat}_calories"
            idempotency_key = generate_idempotency_key(
                tenant_id, source_id, metric_type, timestamp
            )
            dp = {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": metric_type,
                "timestamp": timestamp,
                "value": float(cal_val),
                "metadata": {
                    "source_type": "yazio",
                    "day": day,
                    "meal_category": meal_cat,
                },
                "idempotency_key": idempotency_key,
                "source_type": "yazio",
            }
            data_points.append(dp)

    # 3. Individual consumed food items
    items = raw_data.get("items", [])
    for idx, item in enumerate(items):
        item_cal = item.get("calories")
        if item_cal is None:
            continue

        item_id = item.get("id", f"idx_{idx}")
        metric_type = "consumed_item_calories"
        item_timestamp = f"{day}T00:00:00Z"
        item_source_id = f"{source_id}_{item_id}"

        idempotency_key = generate_idempotency_key(
            tenant_id, item_source_id, metric_type, item_timestamp
        )

        dp = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": metric_type,
            "timestamp": item_timestamp,
            "value": float(item_cal),
            "metadata": {
                "source_type": "yazio",
                "day": day,
                "item_id": str(item_id),
                "food_name": item.get("name", "Unknown Food"),
                "meal_category": item.get("category", "general"),
                "amount": item.get("amount"),
                "unit": item.get("unit"),
                "protein_g": item.get("protein_g"),
                "carbs_g": item.get("carbs_g"),
                "fat_g": item.get("fat_g"),
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    return data_points
