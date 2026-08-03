"""Transformer for Streak 2.0 Gym Log JSON into Standardized DataPoints."""

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


def parse_timestamp(date_str: Any) -> str:
    """Standardize input date string to UTC ISO-8601 format."""
    if not date_str:
        return datetime.now(timezone.utc).isoformat()

    date_str = str(date_str).strip()
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return date_str


def transform_streak_export_json(
    payload: dict[str, Any], tenant_id: str, source_id: str
) -> list[dict[str, Any]]:
    """Transform Streak 2.0 REST export payload into standardized DataPoints."""
    data_points: list[dict[str, Any]] = []

    workouts = payload.get("workouts") or []
    if not isinstance(workouts, list):
        return data_points

    for workout in workouts:
        if not isinstance(workout, dict):
            continue

        workout_id = str(workout.get("id") or "")
        workout_title = str(workout.get("title") or "Workout")
        workout_category = str(workout.get("category") or "")
        workout_ts = parse_timestamp(workout.get("createdAt"))

        sets = workout.get("sets") or []
        if not isinstance(sets, list):
            sets = []

        total_workout_volume = 0.0
        total_workout_sets = 0
        total_workout_reps = 0.0

        for set_item in sets:
            if not isinstance(set_item, dict):
                continue

            set_id = str(set_item.get("id") or "")
            set_num = set_item.get("setNumber") or 1
            weight = set_item.get("weight")
            reps = set_item.get("reps")
            max_pulse = set_item.get("maxPulse")
            set_ts = parse_timestamp(set_item.get("createdAt") or workout.get("createdAt"))

            exercise = set_item.get("exercise") if isinstance(set_item.get("exercise"), dict) else {}
            exercise_title = str(exercise.get("title") or "Exercise")
            exercise_cat = str(exercise.get("category") or workout_category)

            base_metadata = {
                "source_type": "streak",
                "workout_id": workout_id,
                "workout_title": workout_title,
                "workout_category": workout_category,
                "exercise_title": exercise_title,
                "exercise_category": exercise_cat,
                "set_id": set_id,
                "set_number": set_num,
                "notes": set_item.get("notes") or workout.get("notes"),
                "deload": bool(workout.get("deload", False)),
            }

            # 1. Weight metric (kg)
            if isinstance(weight, (int, float)) and not isinstance(weight, bool):
                weight_val = float(weight)
                dp_weight = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": "workout_set_weight_kg",
                    "timestamp": set_ts,
                    "value": weight_val,
                    "metadata": base_metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, f"workout_set_weight_kg_{set_id}", set_ts
                    ),
                    "source_type": "streak",
                }
                data_points.append(dp_weight)

            # 2. Reps metric
            if isinstance(reps, (int, float)) and not isinstance(reps, bool):
                reps_val = float(reps)
                total_workout_reps += reps_val
                dp_reps = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": "workout_set_reps",
                    "timestamp": set_ts,
                    "value": reps_val,
                    "metadata": base_metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, f"workout_set_reps_{set_id}", set_ts
                    ),
                    "source_type": "streak",
                }
                data_points.append(dp_reps)

                # Set Volume (weight * reps)
                if isinstance(weight, (int, float)) and not isinstance(weight, bool):
                    set_vol = float(weight) * reps_val
                    total_workout_volume += set_vol
                    total_workout_sets += 1
                    dp_vol = {
                        "tenant_id": tenant_id,
                        "source_id": source_id,
                        "metric_type": "workout_set_volume",
                        "timestamp": set_ts,
                        "value": set_vol,
                        "metadata": base_metadata,
                        "idempotency_key": generate_idempotency_key(
                            tenant_id, source_id, f"workout_set_volume_{set_id}", set_ts
                        ),
                        "source_type": "streak",
                    }
                    data_points.append(dp_vol)

            # 3. Max Pulse / Heart Rate
            if isinstance(max_pulse, (int, float)) and not isinstance(max_pulse, bool):
                dp_pulse = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": "workout_set_heart_rate_max",
                    "timestamp": set_ts,
                    "value": float(max_pulse),
                    "metadata": base_metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, f"workout_set_heart_rate_max_{set_id}", set_ts
                    ),
                    "source_type": "streak",
                }
                data_points.append(dp_pulse)

        # 4. Summary Workout Volume
        if total_workout_sets > 0:
            workout_summary_meta = {
                "source_type": "streak",
                "workout_id": workout_id,
                "workout_title": workout_title,
                "workout_category": workout_category,
                "notes": workout.get("notes"),
            }
            dp_w_vol = {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": "workout_total_volume",
                "timestamp": workout_ts,
                "value": total_workout_volume,
                "metadata": workout_summary_meta,
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, "workout_total_volume", workout_ts
                ),
                "source_type": "streak",
            }
            dp_w_sets = {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": "workout_total_sets",
                "timestamp": workout_ts,
                "value": float(total_workout_sets),
                "metadata": workout_summary_meta,
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, "workout_total_sets", workout_ts
                ),
                "source_type": "streak",
            }
            data_points.extend([dp_w_vol, dp_w_sets])

    return data_points
