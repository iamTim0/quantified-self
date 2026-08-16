"""Transformer for Streak 2.0 Gym Log JSON into Standardized DataPoints.

The metrics moved from `workout_*` to `strength_*` when the shared registry
(packages/shared-schemas/src/shared_schemas/metrics.py) was introduced. They had
been sharing a prefix with Apple Health's and WHOOP's cardio-session aggregates
without sharing their meaning: `strength_set_heart_rate_max` is the peak pulse
within one set of an exercise, `workout_heart_rate_max` the peak across a whole
session, and the two reading as variants of each other is precisely the confusion
the registry exists to remove.

Three things this file gained when the workout detail view was built:

* **A session block.** Every point carries `session_id` (`shared_schemas.sessions`),
  derived from the workout id Streak already states. Before that, the only thing
  joining a session's rows was their timestamps, and a set is stamped a minute after
  the set before it -- so eighteen sets were eighteen unrelated events.
* **A canonical muscle group.** Streak's `exercise.category` *is* the muscle group,
  but it is Streak's word for it. It is kept verbatim in `exercise_category` and
  mapped onto this platform's own vocabulary in `muscle_group`, so a provider
  rename, a localised category list or a second strength source cannot silently
  split one group into two.
* **A field report.** This was the only importer without one, which meant every
  field Streak sends and we do not read vanished with no trace -- the exact outcome
  rule 19 forbids. It is also how we find out what Streak actually sends.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from shared_schemas import idempotency_key, provenance
from shared_schemas.field_report import FieldReportCollector
from shared_schemas.metrics import canonical_metric_type
from shared_schemas.muscles import MuscleGroup, resolve_muscle_group
from shared_schemas.sessions import session_metadata

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

#: Workout-level fields the transformer reads. Anything else Streak sends is named
#: in the field report instead of disappearing.
WORKOUT_READ_FIELDS = frozenset({"id", "title", "category", "createdAt", "deload", "notes", "sets"})

#: The same, per set.
SET_READ_FIELDS = frozenset(
    {"id", "setNumber", "weight", "reps", "maxPulse", "createdAt", "notes", "exercise"}
)

#: And per exercise.
EXERCISE_READ_FIELDS = frozenset({"title", "category"})


def _muscle_group(raw: str, report: FieldReportCollector | None) -> str:
    """Streak's category as one of ours, reporting anything we do not recognise.

    An unrecognised category still becomes a value -- `other` -- because dropping the
    set would be worse. What must not happen is it becoming `other` *quietly*: a
    provider that renames its category list would then look exactly like a user who
    logs uncategorised exercises, forever. So the raw string is named in the field
    report, where the Data Quality Center can show it.
    """
    resolved = resolve_muscle_group(raw)
    if resolved is not None:
        return resolved.value
    if raw and report is not None:
        report.unmapped("workouts[].sets[].exercise.category", raw)
    return MuscleGroup.OTHER.value


def report_mapped(
    report: FieldReportCollector | None, path: str, value: Any, metric_type: str
) -> None:
    """Name a field that *did* become a data point.

    Without this the Data Quality Center could say what Streak drops and nothing
    about what it keeps — half a report, and the half that reads as an accusation.
    Every other importer files both sides.
    """
    if report is not None:
        report.mapped(path, value, metric_type)


def _report_unread(
    report: FieldReportCollector | None, path: str, payload: dict[str, Any], known: frozenset[str]
) -> None:
    """Name every field at this level we did not look at."""
    if report is None:
        return
    for key, value in payload.items():
        if key not in known:
            report.unmapped(f"{path}.{key}", value)


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
    payload: dict[str, Any],
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector | None = None,
) -> list[dict[str, Any]]:
    """Transform Streak 2.0 REST export payload into standardized DataPoints."""
    data_points: list[dict[str, Any]] = []

    workouts = payload.get("workouts") or []
    if not isinstance(workouts, list):
        return data_points

    _report_unread(report, "payload", payload, frozenset({"workouts"}))

    for workout in workouts:
        if not isinstance(workout, dict):
            continue

        workout_id = str(workout.get("id") or "")
        workout_title = str(workout.get("title") or "Workout")
        workout_category = str(workout.get("category") or "")
        workout_ts = parse_timestamp(workout.get("createdAt"))
        if workout_ts is None:
            continue

        _report_unread(report, "workouts[]", workout, WORKOUT_READ_FIELDS)

        sets = workout.get("sets") or []
        if not isinstance(sets, list):
            sets = []

        # One session block for the whole workout, shared by every set and by the
        # summary points below. `workout.id` is Streak's own identifier, so the id
        # is stated rather than derived and stays stable across re-imports.
        #
        # No `end`. Streak does not state one, and the last set's timestamp -- the
        # obvious substitute -- would arrive in `session_end` looking exactly like a
        # figure the provider gave, on a block whose `session_origin` says
        # `provider`. The read path derives the same span from the session's own
        # rows, where it is visibly a derivation rather than a claim.
        session = session_metadata(
            source_type="streak",
            source_id=source_id,
            provider_session_id=workout_id or None,
            start=workout_ts,
            label=workout_title,
            derived_from=("createdAt", "title"),
        )

        total_workout_volume = 0.0
        total_workout_sets = 0

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

            _report_unread(report, "workouts[].sets[]", set_item, SET_READ_FIELDS)

            exercise = set_item.get("exercise") if isinstance(set_item.get("exercise"), dict) else {}
            _report_unread(report, "workouts[].sets[].exercise", exercise, EXERCISE_READ_FIELDS)
            exercise_title = str(exercise.get("title") or "Exercise")
            exercise_cat = str(exercise.get("category") or workout_category)

            base_metadata = {
                "source_type": "streak",
                "workout_id": workout_id,
                "workout_title": workout_title,
                "workout_category": workout_category,
                "exercise_title": exercise_title,
                # Both: the provider's own word, and ours. The first is evidence,
                # the second is what anything downstream may group on.
                "exercise_category": exercise_cat,
                "muscle_group": _muscle_group(exercise_cat, report),
                "set_id": set_id,
                "set_number": set_num,
                "notes": set_item.get("notes") or workout.get("notes"),
                "deload": bool(workout.get("deload", False)),
                **session,
            }
            idempotency_source_id = f"{source_id}_{set_id}"

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
                        tenant_id, idempotency_source_id, METRIC_SET_WEIGHT, set_ts
                    ),
                    "source_type": "streak",
                }
                report_mapped(report, "workouts[].sets[].weight", weight, METRIC_SET_WEIGHT)
                data_points.append(dp_weight)

            # 2. Reps metric
            if isinstance(reps, (int, float)) and not isinstance(reps, bool):
                reps_val = float(reps)
                # A set is a set once it has repetitions. This used to be counted
                # inside the weight branch below, so a bodyweight session -- pull-ups,
                # dips, an entire calisthenics workout -- reached the summary with
                # `total_workout_sets == 0` and emitted no session points at all.
                # The sets were stored; the session they belonged to was not.
                total_workout_sets += 1
                dp_reps = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "idempotency_source_id": f"{source_id}_{set_id}",
                    "metric_type": METRIC_SET_REPS,
                    "timestamp": set_ts,
                    "value": reps_val,
                    "metadata": {**base_metadata, **provenance(METRIC_SET_REPS, reps_val)},
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, idempotency_source_id, METRIC_SET_REPS, set_ts
                    ),
                    "source_type": "streak",
                }
                report_mapped(report, "workouts[].sets[].reps", reps, METRIC_SET_REPS)
                data_points.append(dp_reps)

                # Set Volume (weight * reps)
                if isinstance(weight, (int, float)) and not isinstance(weight, bool):
                    set_vol = float(weight) * reps_val
                    total_workout_volume += set_vol
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
                            # Two operands. Trivial here, stated anyway: the
                            # anti-pattern list names all three fields together,
                            # and a reader should not have to know which
                            # operations happen to make the count interesting.
                            "sample_count": 2,
                        },
                        "idempotency_key": generate_idempotency_key(
                            tenant_id, idempotency_source_id, METRIC_SET_VOLUME, set_ts
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
                        tenant_id, idempotency_source_id, METRIC_SET_HEART_RATE_MAX, set_ts
                    ),
                    "source_type": "streak",
                }
                report_mapped(
                    report, "workouts[].sets[].maxPulse", max_pulse, METRIC_SET_HEART_RATE_MAX
                )
                data_points.append(dp_pulse)

        # 4. Summary Workout Volume
        if total_workout_sets > 0:
            workout_summary_meta = {
                "source_type": "streak",
                "workout_id": workout_id,
                "workout_title": workout_title,
                "workout_category": workout_category,
                "muscle_group": _muscle_group(workout_category, report),
                "notes": workout.get("notes"),
                # The same block the sets carry, so the summary and the sets it
                # summarises are one session rather than two.
                **session,
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
