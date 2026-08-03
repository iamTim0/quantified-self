"""Transformer for WHOOP Metrics into Standardized DataPoints."""

import hashlib
from typing import Any


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """Generate deterministic SHA256 idempotency key per Rule 4."""
    raw = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


METRICS: dict[str, dict[str, tuple[str, str]]] = {
    "cycle": {
        "strain": ("score", "strain"),
        "cycle_kilojoule": ("score", "kilojoule"),
        "cycle_average_heart_rate": ("score", "average_heart_rate"),
    },
    "recovery": {
        "recovery_score": ("score", "recovery_score"),
        "resting_heart_rate": ("score", "resting_heart_rate"),
        "hrv_rmssd_milli": ("score", "hrv_rmssd_milli"),
        "spo2_percentage": ("score", "spo2_percentage"),
        "skin_temp_celsius": ("score", "skin_temp_celsius"),
    },
    "sleep": {
        "sleep_performance_percentage": ("score", "sleep_performance_percentage"),
        "sleep_efficiency_percentage": ("score", "sleep_efficiency_percentage"),
        "respiratory_rate": ("score", "respiratory_rate"),
    },
    "workout": {
        "workout_strain": ("score", "strain"),
        "workout_kilojoule": ("score", "kilojoule"),
        "workout_average_heart_rate": ("score", "average_heart_rate"),
        "workout_distance_meter": ("score", "distance_meter"),
    },
}


def transform_whoop_records(
    kind: str,
    records: list[dict[str, Any]],
    tenant_id: str,
    source_id: str,
) -> list[dict[str, Any]]:
    """Transform WHOOP records into standard DataPoints."""
    data_points: list[dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("score_state") != "SCORED":
            continue

        ts = str(record.get("start") or record.get("created_at") or "")
        if not ts:
            continue

        whoop_id = str(record.get("id") or record.get("cycle_id") or "")
        metadata = {
            "source_type": "whoop",
            "whoop_id": whoop_id,
            "kind": kind,
        }

        metric_map = METRICS.get(kind, {})
        for metric_type, (section, field) in metric_map.items():
            val = (record.get(section) or {}).get(field)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                dp = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": metric_type,
                    "timestamp": ts,
                    "value": float(val),
                    "metadata": metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, metric_type, ts
                    ),
                }
                data_points.append(dp)

    return data_points
