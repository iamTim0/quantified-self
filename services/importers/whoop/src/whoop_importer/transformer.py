"""Map WHOOP records to the platform's idempotent DataPoint contract."""

import hashlib
from typing import Any


def _point(tenant_id: str, source_id: str, metric: str, timestamp: str, value: float, record: dict[str, Any]) -> dict[str, Any]:
    raw = f"{tenant_id}:{source_id}:{metric}:{timestamp}"
    return {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "metric_type": metric,
        "timestamp": timestamp,
        "value": value,
        "metadata": {"source_type": "whoop", "whoop_id": str(record.get("id") or record.get("cycle_id") or "")},
        "idempotency_key": hashlib.sha256(raw.encode()).hexdigest(),
    }


METRICS: dict[str, dict[str, tuple[str, str]]] = {
    "cycle": {"strain": ("score", "strain"), "cycle_kilojoule": ("score", "kilojoule"), "cycle_average_heart_rate": ("score", "average_heart_rate")},
    "recovery": {"recovery_score": ("score", "recovery_score"), "resting_heart_rate": ("score", "resting_heart_rate"), "hrv_rmssd_milli": ("score", "hrv_rmssd_milli"), "spo2_percentage": ("score", "spo2_percentage"), "skin_temp_celsius": ("score", "skin_temp_celsius")},
    "sleep": {"sleep_performance_percentage": ("score", "sleep_performance_percentage"), "sleep_efficiency_percentage": ("score", "sleep_efficiency_percentage"), "respiratory_rate": ("score", "respiratory_rate")},
    "workout": {"workout_strain": ("score", "strain"), "workout_kilojoule": ("score", "kilojoule"), "workout_average_heart_rate": ("score", "average_heart_rate"), "workout_distance_meter": ("score", "distance_meter")},
}


def transform_record(kind: str, record: dict[str, Any], tenant_id: str, source_id: str) -> list[dict[str, Any]]:
    """Transform only scored, numeric measurements; pending records are safe to retry later."""
    if record.get("score_state") != "SCORED":
        return []
    timestamp = str(record.get("start") or record.get("created_at") or "")
    if not timestamp:
        return []
    points = []
    for metric, (section, field) in METRICS[kind].items():
        value = (record.get(section) or {}).get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            points.append(_point(tenant_id, source_id, metric, timestamp, float(value), record))
    return points
