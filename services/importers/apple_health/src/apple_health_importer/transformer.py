"""Transformer for Health Auto Export (Apple Health) JSON into Standardized DataPoints."""

import hashlib
from datetime import datetime, timezone
from typing import Any


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """Generate deterministic SHA256 idempotency key per Rule 4.

    Format: SHA256(tenant_id:source_id:metric_type:timestamp)
    """
    raw = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_timestamp(date_str: str) -> str:
    """Standardize input date string to UTC ISO-8601 format."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()

    date_str = str(date_str).strip()

    # Try common Health Auto Export date formats:
    # 1) "2026-08-03 14:00:00 +0000" or "+0200"
    # 2) "2026-08-03T14:00:00Z" / ISO format
    try:
        if " +0" in date_str or " -0" in date_str:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")
            return dt.astimezone(timezone.utc).isoformat()
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return date_str


METRIC_NAME_MAP: dict[str, str] = {
    "step_count": "step_count",
    "steps": "step_count",
    "active_energy": "active_energy",
    "active_energy_burned": "active_energy",
    "basal_energy_burned": "resting_energy",
    "resting_energy": "resting_energy",
    "heart_rate": "heart_rate",
    "resting_heart_rate": "resting_heart_rate",
    "heart_rate_variability_sdnn": "hrv_sdnn",
    "hrv": "hrv_sdnn",
    "sleep_analysis": "sleep_duration",
    "sleep": "sleep_duration",
    "blood_oxygen": "spo2_percentage",
    "oxygen_saturation": "spo2_percentage",
    "respiratory_rate": "respiratory_rate",
    "body_mass": "body_mass",
    "weight": "body_mass",
    "body_fat_percentage": "body_fat_percentage",
    "vo2_max": "vo2_max",
    "apple_exercise_time": "apple_exercise_time",
    "apple_stand_time": "apple_stand_time",
    "walking_heart_rate_average": "walking_heart_rate_average",
    "dietary_energy_consumed": "calories_consumed",
}


def _extract_numeric_value(val: Any) -> float | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, dict):
        q = val.get("qty") or val.get("value") or val.get("avg")
        if isinstance(q, (int, float)) and not isinstance(q, bool):
            return float(q)
    return None


def transform_health_auto_export_json(
    payload: dict[str, Any], tenant_id: str, source_id: str
) -> list[dict[str, Any]]:
    """Transform Health Auto Export JSON structure into standardized DataPoints."""
    data_points: list[dict[str, Any]] = []

    # Support payloads with root 'data' key or direct metrics/workouts keys
    data_content = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    metrics_list = data_content.get("metrics") or []
    workouts_list = data_content.get("workouts") or []

    # 1. Transform Metrics
    for metric_obj in metrics_list:
        if not isinstance(metric_obj, dict):
            continue

        raw_name = str(metric_obj.get("name") or "").lower().strip()
        units = str(metric_obj.get("units") or "")
        metric_type = METRIC_NAME_MAP.get(raw_name, raw_name or "apple_health_metric")

        data_entries = metric_obj.get("data") or []
        for entry in data_entries:
            if not isinstance(entry, dict):
                continue

            raw_date = entry.get("date") or entry.get("startDate") or entry.get("timestamp")
            if not raw_date:
                continue

            ts = parse_timestamp(str(raw_date))
            val = _extract_numeric_value(entry.get("qty"))
            if val is None:
                val = _extract_numeric_value(entry.get("avg"))
            if val is None:
                val = _extract_numeric_value(entry.get("value"))

            if val is not None:
                metadata = {
                    "source_type": "apple_health",
                    "original_metric_name": raw_name,
                    "units": units,
                }
                if "source" in entry:
                    metadata["device_source"] = entry["source"]

                dp = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": metric_type,
                    "timestamp": ts,
                    "value": val,
                    "metadata": metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, metric_type, ts
                    ),
                    "source_type": "apple_health",
                }
                data_points.append(dp)

            # Extra handling for sleep stages sub-fields if present
            if raw_name in ("sleep_analysis", "sleep"):
                for stage in ("deep", "rem", "core", "awake", "inBed", "asleep"):
                    stage_val = _extract_numeric_value(entry.get(stage))
                    if stage_val is not None:
                        stage_metric_type = f"sleep_{stage.lower()}_duration"
                        dp_stage = {
                            "tenant_id": tenant_id,
                            "source_id": source_id,
                            "metric_type": stage_metric_type,
                            "timestamp": ts,
                            "value": stage_val,
                            "metadata": {
                                "source_type": "apple_health",
                                "parent_metric": raw_name,
                                "stage": stage,
                                "units": units,
                            },
                            "idempotency_key": generate_idempotency_key(
                                tenant_id, source_id, stage_metric_type, ts
                            ),
                            "source_type": "apple_health",
                        }
                        data_points.append(dp_stage)

    # 2. Transform Workouts
    for workout in workouts_list:
        if not isinstance(workout, dict):
            continue

        raw_start = workout.get("start") or workout.get("startDate")
        if not raw_start:
            continue

        ts = parse_timestamp(str(raw_start))
        workout_name = str(workout.get("name") or workout.get("workoutName") or "Workout")

        workout_metadata = {
            "source_type": "apple_health",
            "workout_name": workout_name,
            "end_time": parse_timestamp(str(workout.get("end") or workout.get("endDate") or "")),
        }

        # Workout Metrics mapping
        workout_fields = [
            ("activeEnergy", "workout_active_energy"),
            ("totalDistance", "workout_distance"),
            ("duration", "workout_duration"),
            ("avgHeartRate", "workout_avg_heart_rate"),
            ("maxHeartRate", "workout_max_heart_rate"),
        ]

        for field_key, w_metric_type in workout_fields:
            val = _extract_numeric_value(workout.get(field_key))
            if val is not None:
                dp_w = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": w_metric_type,
                    "timestamp": ts,
                    "value": val,
                    "metadata": workout_metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, w_metric_type, ts
                    ),
                    "source_type": "apple_health",
                }
                data_points.append(dp_w)

    return data_points
