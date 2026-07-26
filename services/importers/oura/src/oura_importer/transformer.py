"""Oura Ring API v2 JSON Data Transformer.

Maps Oura raw JSON documents into standardized DataPoint dictionaries.
Generates deterministic SHA256 idempotency_keys to guarantee exact-once storage semantics.

Maps to Fizzbee Invariants:
- IdempotencyKeyDeterministic
- UniqueKeyMapping
"""

import hashlib
from typing import Any, Dict, List
from oura_importer.config import settings


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """Generate a deterministic 64-character SHA256 idempotency key.

    Formula: SHA256(tenant_id:source_id:metric_type:timestamp)
    """
    raw_str = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def transform_sleep_data(
    raw_data: Dict[str, Any],
    tenant_id: str = settings.TENANT_ID,
    source_id: str = settings.SOURCE_ID,
) -> List[Dict[str, Any]]:
    """Transform Oura v2 daily_sleep document array into DataPoints."""
    data_points = []

    for item in raw_data.get("data", []):
        day = item.get("day")
        if not day:
            continue

        # ISO timestamp normalized to UTC midnight for the daily log
        timestamp = f"{day}T00:00:00Z"

        # Extracted metrics
        metrics = {
            "sleep_score": item.get("score"),
            "total_sleep_duration": item.get("total_sleep_duration"),
            "deep_sleep_duration": item.get("deep_sleep_duration"),
            "rem_sleep_duration": item.get("rem_sleep_duration"),
            "efficiency": item.get("efficiency"),
        }

        for metric_type, val in metrics.items():
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
                    "source_type": "oura",
                    "day": day,
                    "contributors": item.get("contributors", {}),
                },
                "idempotency_key": idempotency_key,
                "source_type": "oura",
            }
            data_points.append(dp)

    return data_points


def transform_readiness_data(
    raw_data: Dict[str, Any],
    tenant_id: str = settings.TENANT_ID,
    source_id: str = settings.SOURCE_ID,
) -> List[Dict[str, Any]]:
    """Transform Oura v2 daily_readiness document array into DataPoints."""
    data_points = []

    for item in raw_data.get("data", []):
        day = item.get("day")
        if not day:
            continue

        timestamp = f"{day}T00:00:00Z"

        metrics = {
            "readiness_score": item.get("score"),
            "resting_hr": item.get("resting_heart_rate"),
            "hrv_balance": item.get("hrv_balance"),
        }

        for metric_type, val in metrics.items():
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
                    "source_type": "oura",
                    "day": day,
                    "contributors": item.get("contributors", {}),
                },
                "idempotency_key": idempotency_key,
                "source_type": "oura",
            }
            data_points.append(dp)

    return data_points


def transform_activity_data(
    raw_data: Dict[str, Any],
    tenant_id: str = settings.TENANT_ID,
    source_id: str = settings.SOURCE_ID,
) -> List[Dict[str, Any]]:
    """Transform Oura v2 daily_activity document array into DataPoints."""
    data_points = []

    for item in raw_data.get("data", []):
        day = item.get("day")
        if not day:
            continue

        timestamp = f"{day}T00:00:00Z"

        metrics = {
            "activity_score": item.get("score"),
            "steps": item.get("steps"),
            "active_calories": item.get("active_calories"),
            "total_calories": item.get("total_calories"),
        }

        for metric_type, val in metrics.items():
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
                    "source_type": "oura",
                    "day": day,
                    "contributors": item.get("contributors", {}),
                },
                "idempotency_key": idempotency_key,
                "source_type": "oura",
            }
            data_points.append(dp)

    return data_points
