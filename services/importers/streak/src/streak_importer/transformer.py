"""Transformer for Streak 2.0 Gym Log JSON into Standardized DataPoints.

The metrics moved from `workout_*` to `strength_*` when the shared registry
(packages/shared-schemas/src/shared_schemas/metrics.py) was introduced. They had
been sharing a prefix with Apple Health's and WHOOP's cardio-session aggregates
without sharing their meaning: `strength_set_heart_rate_max` is the peak pulse
within one set of an exercise, `workout_heart_rate_max` the peak across a whole
session, and the two reading as variants of each other is precisely the confusion
the registry exists to remove.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from shared_schemas import idempotency_key, provenance
from shared_schemas.metrics import canonical_metric_type

logger = logging.getLogger(__name__)


#: SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4, defined once
#: in `shared_schemas`. An alias rather than a wrapper: a wrapper would be a fifth
#: identical docstring to keep in step, and its `timestamp: str` annotation would hide
#: that the shared function also takes a `datetime`.
generate_idempotency_key = idempotency_key

METRIC_SET_WEIGHT = canonical_metric_type("strength_set_weight")
METRIC_SET_REPS = canonical_metric_type("strength_set_reps")
METRIC_SET_VOLUME = canonical_metric_type("strength_set_volume")
METRIC_SET_HEART_RATE_MAX = canonical_metric_type("strength_set_heart_rate_max")
METRIC_SESSION_VOLUME = canonical_metric_type("strength_session_volume")
METRIC_SESSION_SETS = canonical_metric_type("strength_session_sets")


def parse_timestamp(date_str: Any) -> str | None:
    """Standardize input date string to UTC ISO-8601 format, or `None`.

    `None` rather than `datetime.now()`, and rather than the unparsed string. The
    timestamp is hashed into the `idempotency_key`, so a substituted *now* is a fresh key
    on every poll: the same set inserts a new row each sync, forever, and nothing fails
    because `ON CONFLICT DO NOTHING` has nothing to conflict with.

    A set whose timestamp cannot be understood cannot be deduplicated, so the caller skips
    it — the same choice the weather and Home Assistant transformers make.
    """
    if not date_str:
        return None

    date_str = str(date_str).strip()
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        logger.warning("streak: unparseable timestamp %r, skipping the entry", date_str)
        return None


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
        if workout_ts is None:
            continue

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
            if set_ts is None:
                continue

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
                    "idempotency_source_id": f"{source_id}_{set_id}",
                    "metric_type": METRIC_SET_WEIGHT,
                    "timestamp": set_ts,
                    "value": weight_val,
                    "metadata": {
                        **base_metadata,
                        **provenance(METRIC_SET_WEIGHT, weight_val),
                    },
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, f"{METRIC_SET_WEIGHT}_{set_id}", set_ts
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
                    "idempotency_source_id": f"{source_id}_{set_id}",
                    "metric_type": METRIC_SET_REPS,
                    "timestamp": set_ts,
                    "value": reps_val,
                    "metadata": {**base_metadata, **provenance(METRIC_SET_REPS, reps_val)},
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, f"{METRIC_SET_REPS}_{set_id}", set_ts
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
                        "idempotency_source_id": f"{source_id}_{set_id}",
                        "metric_type": METRIC_SET_VOLUME,
                        "timestamp": set_ts,
                        "value": set_vol,
                        # Streak never sent this number: it is weight times reps, and
                        # rule 19 wants a computed figure to say so rather than pass for
                        # a reading.
                        "metadata": {
                            **base_metadata,
                            **provenance(METRIC_SET_VOLUME, set_vol),
                            "derived_from": ["weight", "reps"],
                            "derived_by": "product",
                        },
                        "idempotency_key": generate_idempotency_key(
                            tenant_id, source_id, f"{METRIC_SET_VOLUME}_{set_id}", set_ts
                        ),
                        "source_type": "streak",
                    }
                    data_points.append(dp_vol)

            # 3. Max Pulse / Heart Rate
            if isinstance(max_pulse, (int, float)) and not isinstance(max_pulse, bool):
                dp_pulse = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "idempotency_source_id": f"{source_id}_{set_id}",
                    "metric_type": METRIC_SET_HEART_RATE_MAX,
                    "timestamp": set_ts,
                    "value": float(max_pulse),
                    "metadata": {
                        **base_metadata,
                        **provenance(METRIC_SET_HEART_RATE_MAX, float(max_pulse)),
                    },
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, f"{METRIC_SET_HEART_RATE_MAX}_{set_id}", set_ts
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
                "metric_type": METRIC_SESSION_VOLUME,
                "timestamp": workout_ts,
                "value": total_workout_volume,
                "metadata": {
                    **workout_summary_meta,
                    **provenance(METRIC_SESSION_VOLUME, total_workout_volume),
                    "derived_from": ["sets[].weight", "sets[].reps"],
                    "derived_by": "sum",
                    "sample_count": total_workout_sets,
                },
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, METRIC_SESSION_VOLUME, workout_ts
                ),
                "source_type": "streak",
            }
            dp_w_sets = {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": METRIC_SESSION_SETS,
                "timestamp": workout_ts,
                "value": float(total_workout_sets),
                "metadata": {
                    **workout_summary_meta,
                    **provenance(METRIC_SESSION_SETS, float(total_workout_sets)),
                    "derived_from": ["sets[]"],
                    "derived_by": "count",
                },
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, METRIC_SESSION_SETS, workout_ts
                ),
                "source_type": "streak",
            }
            data_points.extend([dp_w_vol, dp_w_sets])

    return data_points
