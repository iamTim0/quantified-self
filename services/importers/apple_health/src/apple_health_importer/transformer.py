"""Transformer for Health Auto Export (Apple Health) JSON into Standardized DataPoints.

Names and units come from the shared registry
(packages/shared-schemas/src/shared_schemas/metrics.py). Three things this transformer
used to do that the registry makes unnecessary:

* It emitted ``workout_avg_heart_rate`` where WHOOP emitted
  ``workout_average_heart_rate`` for the same quantity, so the two never met.
* It ignored the ``units`` string Health Auto Export ships alongside every metric and
  stored the number raw. Sleep therefore arrived in hours on one phone and minutes on
  another, under one metric name, and distance in miles or kilometres by locale. The
  declared unit is now read and the value converted to the registry's unit.
* Any name it did not recognise became a metric verbatim
  (``METRIC_NAME_MAP.get(raw_name, raw_name)``), which handed the naming of the
  platform's metric space to whatever HealthKit type a phone happened to record.
  Unrecognised names now land under the ``apple_health_`` namespace, where they are
  storable and searchable without claiming a canonical name.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from shared_schemas import FieldReportCollector, idempotency_key, provenance
from shared_schemas.metrics import (
    METRIC_CATALOG,
    MetricUnit,
    UnsupportedConversionError,
    canonical_metric_type,
    convert,
)

logger = logging.getLogger(__name__)

#: Prefix for HealthKit types the catalog does not know. Registered as a dynamic
#: namespace in the registry, so these are legal without being catalogued.
NAMESPACE = "apple_health_"


#: SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4, defined once
#: in `shared_schemas`. An alias rather than a wrapper: a wrapper would be a fifth
#: identical docstring to keep in step, and its `timestamp: str` annotation would hide
#: that the shared function also takes a `datetime`.
generate_idempotency_key = idempotency_key


def parse_timestamp(date_str: str) -> str | None:
    """Standardize input date string to UTC ISO-8601 format, or `None`.

    `None` rather than `datetime.now()`, and rather than the unparsed string. The
    timestamp is hashed into the `idempotency_key`, so a substituted *now* is a fresh key
    on every poll: the same reading inserts a new row each sync, forever, and nothing
    fails because `ON CONFLICT DO NOTHING` has nothing to conflict with. Returning the
    raw string had the same effect whenever the provider varied its formatting.

    A reading whose timestamp cannot be understood cannot be deduplicated, so the caller
    skips it. That is what the weather and Home Assistant transformers already do.
    """
    if not date_str:
        return None

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
    except ValueError:
        logger.warning("apple_health: unparseable timestamp %r, skipping the reading", date_str)
        return None


#: HealthKit / Health Auto Export metric name -> canonical registry key.
METRIC_NAME_MAP: dict[str, str] = {
    "step_count": "steps",
    "steps": "steps",
    "distance_walking_running": "distance",
    "walking_running_distance": "distance",
    "active_energy": "energy_active",
    "active_energy_burned": "energy_active",
    "basal_energy_burned": "energy_resting",
    "resting_energy": "energy_resting",
    "heart_rate": "heart_rate",
    "resting_heart_rate": "heart_rate_resting",
    "heart_rate_variability_sdnn": "hrv_sdnn",
    "hrv": "hrv_sdnn",
    "sleep_analysis": "sleep_duration",
    "sleep": "sleep_duration",
    "blood_oxygen": "blood_oxygen",
    "oxygen_saturation": "blood_oxygen",
    "respiratory_rate": "respiratory_rate",
    "body_mass": "body_weight",
    "weight": "body_weight",
    "body_fat_percentage": "body_fat",
    "vo2_max": "vo2_max",
    "apple_exercise_time": "exercise_duration",
    "apple_stand_time": "stand_duration",
    "flights_climbed": "flights_climbed",
    "walking_heart_rate_average": "heart_rate_walking_average",
    "dietary_energy_consumed": "nutrition_energy",
}

#: Apple's sleep stage key -> canonical registry key. Apple calls light sleep "Core",
#: and its "asleep" is total sleep time -- the same quantity as the entry's own `qty`,
#: which is why it maps to `sleep_duration` rather than a stage of its own.
#: ``totalSleep`` is the current spelling of the same total, and it is why a night could
#: arrive with every stage stored and no sleep duration at all: the v2 sleep entry has no
#: ``qty`` and no ``asleep``, so nothing produced `sleep_duration`. Both are listed and
#: only the first present is emitted, because two points for one metric at one timestamp
#: share an idempotency key and the second is a duplicate Core discards.
SLEEP_STAGE_MAP: dict[str, str] = {
    "deep": "sleep_duration_deep",
    "rem": "sleep_duration_rem",
    "core": "sleep_duration_light",
    "awake": "sleep_duration_awake",
    "inBed": "sleep_duration_in_bed",
    "asleep": "sleep_duration",
    "totalSleep": "sleep_duration",
}

#: Workout payload field -> (canonical registry key, unit to assume when the field
#: declares none). Workout fields are sometimes a bare number rather than a
#: ``{"qty", "units"}`` object; ``duration`` in particular is seconds, which is why it
#: carries a fallback instead of being read as minutes and inflating every session
#: sixtyfold.
#:
#: Both spellings of energy and distance are listed because Health Auto Export
#: renamed them between its workout formats, and only the v1 names were here. In v2
#: ``activeEnergy`` is a *time-series array* and the scalar is ``activeEnergyBurned``;
#: ``totalDistance`` became ``distance``. So on every current payload the energy read
#: an array (yielding nothing) and the distance was looked for under a key that no
#: longer exists — two whole quantities, dropped without a word.
#: ``totalEnergy`` comes first deliberately. The archive path reads a workout's
#: ``totalEnergyBurned`` attribute before its ``ActiveEnergyBurned`` statistic
#: (`export_archive._workout_points`), so both paths must prefer the session total —
#: otherwise the same workout imported one way and then the other writes active energy
#: under `workout_energy` in one run and total energy in the next, under one name, and
#: whichever arrived first is the one Core keeps.
WORKOUT_FIELD_MAP: tuple[tuple[str, str, MetricUnit | None], ...] = (
    ("totalEnergy", "workout_energy", None),
    ("activeEnergyBurned", "workout_energy", None),
    ("activeEnergy", "workout_energy", None),
    ("distance", "workout_distance", None),
    ("totalDistance", "workout_distance", None),
    ("duration", "workout_duration", MetricUnit.SECOND),
    ("avgHeartRate", "workout_heart_rate_average", None),
    ("maxHeartRate", "workout_heart_rate_max", None),
    # `speed` is the session average under an older name, so it comes after `avgSpeed`
    # and only fills the metric when that one is absent.
    ("avgSpeed", "workout_speed_average", None),
    ("speed", "workout_speed_average", None),
    ("maxSpeed", "workout_speed_max", None),
    ("stepCadence", "workout_cadence", None),
    ("elevationUp", "workout_elevation_gain", None),
    ("flightsClimbed", "flights_climbed", None),
    ("intensity", "workout_intensity", None),
)

#: Workout fields that carry several quantities in one object, keyed
#: ``<field>.<member>`` in the same flat provider-vocabulary shape
#: ``ENTRY_FIELD_METRICS`` uses.
#:
#: Health Auto Export moved a workout's heart rate into ``heartRate:
#: {Min, Avg, Max, units}`` and kept the v1 scalars ``avgHeartRate``/``maxHeartRate``
#: only on older payloads. The map above looks for those scalars alone, so on a current
#: payload a workout's heart rate arrived, was recognised as an object holding no
#: ``qty``, and was dropped — both the average and the maximum, on every session.
WORKOUT_OBJECT_METRICS: dict[str, str] = {
    "heartRate.Avg": "workout_heart_rate_average",
    "heartRate.Max": "workout_heart_rate_max",
}

#: The same map grouped by field, built once rather than re-partitioned per workout.
WORKOUT_OBJECT_FIELDS: dict[str, dict[str, str]] = {}
for _path, _canonical in WORKOUT_OBJECT_METRICS.items():
    _field_key, _, _member = _path.partition(".")
    WORKOUT_OBJECT_FIELDS.setdefault(_field_key, {})[_member] = _canonical

#: Intra-workout time series -> the session quantity it accumulates, and how it
#: collapses into that one figure.
#:
#: An array is not a reason to drop a quantity. Summed, a series of per-interval energy
#: *is* the session's energy — the same number the scalar fields state directly — so it
#: is read and written whenever no scalar said it first.
#:
#: What it must not become is one point per sample under the daily metric. `steps` and
#: `distance` aggregate by ``SUM`` over a day and the metrics section already sends that
#: day's total, so forty per-minute samples from a workout would be added on top of a
#: figure that already counts them and the day would read a third too high. Storing them
#: that way is worse than not storing them, because a wrong number is indistinguishable
#: from a right one. Per-sample detail therefore needs a metric of its own — see
#: `docs/importers/apple-health.md` — and until it has one, the figure is kept and the
#: series is reported as seen.
WORKOUT_SERIES_MAP: tuple[tuple[str, str, str], ...] = (
    # Active and basal are the two halves of a session's total, so both are added.
    ("activeEnergy", "workout_energy", "sum"),
    ("basalEnergy", "workout_energy", "sum"),
    ("walkingAndRunningDistance", "workout_distance", "sum"),
    ("cyclingDistance", "workout_distance", "sum"),
    ("heartRateData", "workout_heart_rate_average", "average"),
    ("heartRateData", "workout_heart_rate_max", "max"),
    # Its own metric rather than `steps`, which the day's own total already fills.
    ("stepCount", "workout_steps", "sum"),
)

#: Workout fields kept beside the readings rather than becoming metrics of their own:
#: they describe the session instead of measuring anything, and the registry has no
#: metric for a boolean or a place name. Reported as mapped, because they are taken.
#: ``temperature`` and ``humidity`` are the conditions the workout happened in, and they
#: are deliberately *not* mapped onto `weather_temperature`/`weather_humidity`: those are
#: the weather importer's series for a place, and mixing a phone's workout sample into
#: them would make one name mean two measurements taken by two instruments.
WORKOUT_CONTEXT_FIELDS: dict[str, str] = {
    "isIndoor": "is_indoor",
    "location": "location",
    "metadata": "provider_metadata",
    "temperature": "ambient_temperature",
    "humidity": "ambient_humidity",
}

#: The four moments a sleep entry states about the night, kept as metadata. Not
#: measurements — but they are what says *which night* a reading belongs to, which one
#: timestamp on its own does not.
SLEEP_INTERVAL_FIELDS: dict[str, str] = {
    "sleepStart": "sleep_start",
    "sleepEnd": "sleep_end",
    "inBedStart": "in_bed_start",
    "inBedEnd": "in_bed_end",
}

#: Metric entries that do not carry a plain ``qty``. Each maps an entry key to the
#: canonical metric it becomes.
#:
#: Heart rate and blood pressure both live here, and both were being discarded
#: outright: a heart-rate entry carries ``Min``/``Avg``/``Max`` — capitalised — and a
#: blood-pressure entry carries ``systolic``/``diastolic``, while the reader looked
#: only for ``qty``, then lowercase ``avg``, then ``value``. None of those exist on
#: either shape, so every single reading was skipped.
#: Keyed ``<provider metric>.<entry field>`` so it stays a flat provider-vocabulary
#: to canonical-key map, which is the shape the rest of this file already uses.
ENTRY_FIELD_METRICS: dict[str, str] = {
    "heart_rate.Avg": "heart_rate",
    "resting_heart_rate.Avg": "heart_rate_resting",
    "walking_heart_rate_average.Avg": "heart_rate_walking_average",
    "blood_pressure.systolic": "blood_pressure_systolic",
    "blood_pressure.diastolic": "blood_pressure_diastolic",
}

#: The same map grouped by provider metric, built once rather than scanned per entry.
ENTRY_FIELDS_BY_METRIC: dict[str, dict[str, str]] = {}
for _path, _canonical in ENTRY_FIELD_METRICS.items():
    _provider_metric, _, _entry_field = _path.partition(".")
    ENTRY_FIELDS_BY_METRIC.setdefault(_provider_metric, {})[_entry_field] = _canonical

#: Kept alongside a reading rather than stored as metrics of their own: the registry
#: has no daily heart-rate minimum or maximum, and inventing one would be a metric
#: nobody else writes. They are still carried, so nothing is lost.
ENTRY_CONTEXT_FIELDS: tuple[str, ...] = ("Min", "Max")

#: Top-level sections this importer deliberately does not read.
#:
#: The scope is Health Auto Export's standard health data and its workouts. What is
#: listed here is special-category health data under Article 9 GDPR — a diagnosis, a
#: medication schedule, a cycle, a mood, an ECG trace — and whether a platform stores
#: that is the operator's decision, not a transformer's, and it changes what the
#: privacy policy has to say.
#:
#: Reported rather than silently skipped, which is the difference that matters: the
#: Data Quality Center names them as arriving-but-not-stored, so "my phone sends ECGs
#: and nothing shows up" is answerable, and enabling one later is a deliberate act
#: with somewhere to put the metrics rather than a discovery.
UNREAD_SECTIONS: tuple[str, ...] = (
    "stateOfMind",
    "symptoms",
    "cycleTracking",
    "ecg",
    "medications",
    "heartRateNotifications",
)

#: The `units` strings Health Auto Export emits, lowercased, mapped onto registry
#: units. Anything absent means "we do not know what this number is in" -- the value is
#: then stored unconverted rather than silently assumed to be canonical.
PROVIDER_UNITS: dict[str, MetricUnit] = {
    "count": MetricUnit.COUNT,
    "kcal": MetricUnit.KCAL,
    "cal": MetricUnit.KCAL,
    "kj": MetricUnit.KILOJOULE,
    "g": MetricUnit.GRAM,
    "kg": MetricUnit.KILOGRAM,
    "lb": MetricUnit.POUND,
    "lbs": MetricUnit.POUND,
    "%": MetricUnit.PERCENT,
    "bpm": MetricUnit.BPM,
    "count/min": MetricUnit.BPM,
    # Apple's own archive states blood pressure in mmHg; the push path never sent a
    # unit for it at all, so this is the spelling the export brought with it.
    "mmhg": MetricUnit.MMHG,
    "ms": MetricUnit.MILLISECOND,
    "s": MetricUnit.SECOND,
    "sec": MetricUnit.SECOND,
    "min": MetricUnit.MINUTE,
    "hr": MetricUnit.HOUR,
    "h": MetricUnit.HOUR,
    "hours": MetricUnit.HOUR,
    "m": MetricUnit.METER,
    "ft": MetricUnit.FOOT,
    "km": MetricUnit.KILOMETER,
    "mi": MetricUnit.MILE,
    # Health Auto Export spells speed with `hr`, not `h`, and follows the phone's locale.
    "km/hr": MetricUnit.KILOMETER_PER_HOUR,
    "km/h": MetricUnit.KILOMETER_PER_HOUR,
    "mi/hr": MetricUnit.MILE_PER_HOUR,
    "mph": MetricUnit.MILE_PER_HOUR,
    "spm": MetricUnit.STEPS_PER_MINUTE,
    "steps/min": MetricUnit.STEPS_PER_MINUTE,
    "met": MetricUnit.MET,
    "degc": MetricUnit.CELSIUS,
    "°c": MetricUnit.CELSIUS,
    "ml/kg·min": MetricUnit.ML_PER_KG_PER_MIN,
    "ml/(kg*min)": MetricUnit.ML_PER_KG_PER_MIN,
}


def canonical_name(raw_name: str) -> str:
    """Registry key for a HealthKit metric name, or a namespaced one if it has none.

    The fallback used to be the provider's name unchanged, which let any HealthKit type
    occupy a bare metric name next to the catalogued ones. Prefixing keeps the data —
    an uncatalogued metric is still worth storing — while leaving the canonical space
    to the registry.
    """
    if raw_name in METRIC_NAME_MAP:
        return canonical_metric_type(METRIC_NAME_MAP[raw_name])
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in raw_name).strip("_").lower()
    if not cleaned:
        return f"{NAMESPACE}metric"
    # A HealthKit name that already *is* a registry key needs no translation and no
    # namespace: `HKQuantityTypeIdentifierBloodPressureSystolic` reduces to
    # `blood_pressure_systolic`, which is the catalogued metric. Namespacing it
    # anyway put the same reading in `apple_health_blood_pressure_systolic`, next to
    # the real one and never meeting it.
    if cleaned in METRIC_CATALOG:
        return canonical_metric_type(cleaned)
    return f"{NAMESPACE}{cleaned}"


def normalise_value(
    value: float,
    declared_units: str,
    metric_type: str,
    default_unit: MetricUnit | None = None,
) -> float:
    """Convert ``value`` into the unit the registry defines for ``metric_type``.

    ``default_unit`` applies only when the payload declares nothing; a declared unit
    always wins, so a fallback cannot override what the phone actually said.

    Returns the value untouched when the metric is namespaced (no canonical unit
    exists), when the unit is neither declared nor defaulted nor recognised, or when the
    registry has no factor for the pair. Guessing in any of those cases would corrupt
    the number far more thoroughly than leaving it alone.
    """
    definition = METRIC_CATALOG.get(metric_type)
    if definition is None:
        return value

    provider_unit = PROVIDER_UNITS.get(declared_units.strip().lower(), default_unit)
    if provider_unit is None or provider_unit is definition.unit:
        return value

    try:
        return convert(value, provider_unit, definition.unit)
    except UnsupportedConversionError:
        logger.warning(
            "Apple Health reported %s in %r, which the registry cannot convert to %r; "
            "storing the value unconverted",
            metric_type,
            declared_units,
            definition.unit.value,
        )
        return value


def _member_value(container: dict[str, Any], name: str) -> Any:
    """A member of a provider object, whatever its capitalisation.

    Health Auto Export writes a workout's heart rate as `Avg`/`Max` and a metric entry's
    as `avg`, for the same quantity — so matching one spelling exactly reads one shape
    and silently drops the other.
    """
    if name in container:
        return container[name]
    lowered = name.lower()
    for key, value in container.items():
        if key.lower() == lowered:
            return value
    return None


def _series_figure(samples: list[Any], how: str) -> tuple[float | None, str, int]:
    """Collapse a provider time series into the one figure a session states about it.

    Returns the figure, the unit the samples declared, and how many were read — the last
    two so the point can say what it was derived from instead of looking like a reading
    the provider sent.

    ``average`` is the unweighted mean of the samples' own averages. Duration-weighting
    would be more correct, but a sample carries no duration; this is a fallback for a
    payload that sent no average at all, and an approximation of the right number beats
    the absence of any number.
    """
    values: list[float] = []
    units = ""
    for sample in samples:
        if isinstance(sample, dict) and not units:
            units = str(sample.get("units") or "")

        if not isinstance(sample, dict):
            value = _extract_numeric_value(sample)
        elif how == "max":
            value = _extract_numeric_value(_member_value(sample, "Max"))
        elif how == "average":
            value = _extract_numeric_value(_member_value(sample, "Avg"))
        else:
            value = None

        if value is None:
            value = _extract_numeric_value(sample)
        if value is not None:
            values.append(value)

    if not values:
        return None, units, 0
    if how == "sum":
        return sum(values), units, len(values)
    if how == "max":
        return max(values), units, len(values)
    return sum(values) / len(values), units, len(values)


def _extract_numeric_value(val: Any) -> float | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    if isinstance(val, dict):
        q = val.get("qty") or val.get("value") or val.get("avg")
        if isinstance(q, (int, float)) and not isinstance(q, bool):
            return float(q)
    return None


def transform_health_auto_export_json(
    payload: dict[str, Any],
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector | None = None,
) -> list[dict[str, Any]]:
    """Transform Health Auto Export JSON structure into standardized DataPoints.

    ``report``, when given, accumulates which payload paths became data points and
    which were seen and produced nothing — the shape only, never a value. That is
    what makes a silently ignored field visible instead of having to be found by
    holding the provider's documentation against this file by hand.
    """
    data_points: list[dict[str, Any]] = []
    report = report or FieldReportCollector()

    # Support payloads with root 'data' key or direct metrics/workouts keys
    data_content = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    metrics_list = data_content.get("metrics") or []
    workouts_list = data_content.get("workouts") or []

    for section in UNREAD_SECTIONS:
        entries = data_content.get(section)
        if isinstance(entries, list) and entries:
            report.unmapped(f"data.{section}[]", entries[0], times=len(entries))

    # 1. Transform Metrics
    for metric_obj in metrics_list:
        if not isinstance(metric_obj, dict):
            continue

        raw_name = str(metric_obj.get("name") or "").lower().strip()
        units = str(metric_obj.get("units") or "")
        metric_type = canonical_name(raw_name)
        entry_fields = ENTRY_FIELDS_BY_METRIC.get(raw_name)
        # Decided once for the whole metric rather than per entry: a push can carry tens
        # of thousands of them, and only sleep has stages or a night's boundaries.
        is_sleep = raw_name in ("sleep_analysis", "sleep")

        data_entries = metric_obj.get("data") or []
        for entry in data_entries:
            if not isinstance(entry, dict):
                continue

            raw_date = entry.get("date") or entry.get("startDate") or entry.get("timestamp")
            if not raw_date:
                continue

            ts = parse_timestamp(str(raw_date))
            if ts is None:
                continue

            base_metadata: dict[str, Any] = {
                "source_type": "apple_health",
                "original_metric_name": raw_name,
                # The unit the phone reported in, kept even after conversion: it is
                # what a "why is this number different from my Health app" question
                # is actually about.
                "units": units,
            }
            if "source" in entry:
                base_metadata["device_source"] = entry["source"]

            # Shapes that carry their numbers under their own names rather than
            # under `qty`: heart rate as Min/Avg/Max, blood pressure as
            # systolic/diastolic. Both were skipped entirely before.
            handled_keys: set[str] = {"date", "startDate", "endDate", "timestamp", "source"}

            # Normalised the same way a reading's own timestamp is, so a night's
            # boundaries and its points are in one timezone rather than two.
            intervals: dict[str, Any] = {}
            if is_sleep:
                for interval_field, metadata_key in SLEEP_INTERVAL_FIELDS.items():
                    moment = entry.get(interval_field)
                    if not isinstance(moment, str) or not moment:
                        continue
                    handled_keys.add(interval_field)
                    intervals[metadata_key] = parse_timestamp(moment) or moment
                base_metadata.update(intervals)

            if entry_fields:
                context = {
                    field: entry[field]
                    for field in ENTRY_CONTEXT_FIELDS
                    if _extract_numeric_value(entry.get(field)) is not None
                }
                for field, field_metric in entry_fields.items():
                    field_value = _extract_numeric_value(entry.get(field))
                    if field_value is None:
                        continue
                    handled_keys.add(field)
                    metadata = {**base_metadata, "provider_value": field_value, **context}
                    data_points.append(
                        {
                            "tenant_id": tenant_id,
                            "source_id": source_id,
                            "metric_type": field_metric,
                            "timestamp": ts,
                            "value": normalise_value(field_value, units, field_metric),
                            "metadata": metadata,
                            "idempotency_key": generate_idempotency_key(
                                tenant_id, source_id, field_metric, ts
                            ),
                            "source_type": "apple_health",
                        }
                    )
                    report.mapped(f"metrics.{raw_name}.{field}", field_value, field_metric)
                # Carried in metadata rather than as metrics of their own; still taken.
                for field in context:
                    handled_keys.add(field)
                    report.mapped(f"metrics.{raw_name}.{field}", entry[field], field_metric)

            val = _extract_numeric_value(entry.get("qty"))
            if val is None:
                val = _extract_numeric_value(entry.get("avg"))
            if val is None:
                val = _extract_numeric_value(entry.get("value"))

            if val is not None:
                handled_keys |= {"qty", "avg", "value"}
                metadata = {**base_metadata, "provider_value": val}

                dp = {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": metric_type,
                    "timestamp": ts,
                    "value": normalise_value(val, units, metric_type),
                    "metadata": metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, metric_type, ts
                    ),
                    "source_type": "apple_health",
                }
                data_points.append(dp)
                report.mapped(f"metrics.{raw_name}.qty", val, metric_type)

            # Anything else this entry carried and nothing read.
            for key, value in entry.items():
                if key in handled_keys or key in SLEEP_STAGE_MAP:
                    continue
                report.unmapped(f"metrics.{raw_name}.{key}", value)

            # Extra handling for sleep stages sub-fields if present
            if is_sleep:
                # `asleep` and `totalSleep` carry the same total the entry's own qty did.
                # Emitting two of them would produce two points with one idempotency
                # key, of which Core stores the first and logs the second as a duplicate.
                emitted_stages: set[str] = {metric_type} if val is not None else set()
                for stage, stage_metric_type in SLEEP_STAGE_MAP.items():
                    if stage_metric_type in emitted_stages:
                        continue
                    stage_val = _extract_numeric_value(entry.get(stage))
                    if stage_val is not None:
                        emitted_stages.add(stage_metric_type)
                        report.mapped(
                            f"metrics.{raw_name}.{stage}", stage_val, stage_metric_type
                        )
                        dp_stage = {
                            "tenant_id": tenant_id,
                            "source_id": source_id,
                            "metric_type": stage_metric_type,
                            "timestamp": ts,
                            "value": normalise_value(stage_val, units, stage_metric_type),
                            "metadata": {
                                "source_type": "apple_health",
                                "parent_metric": raw_name,
                                "stage": stage,
                                "units": units,
                                "provider_value": stage_val,
                                **intervals,
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
        if ts is None:
            continue
        workout_name = str(workout.get("name") or workout.get("workoutName") or "Workout")

        workout_metadata = {
            "source_type": "apple_health",
            "workout_name": workout_name,
            # Metadata, not part of the key -- absent rather than invented when the
            # provider does not send an end.
            "end_time": parse_timestamp(str(workout.get("end") or workout.get("endDate") or "")),
        }

        workout_id = str(workout.get("id") or "")
        handled_workout_keys: set[str] = {
            "id", "name", "workoutName", "start", "startDate", "end", "endDate",
        }
        emitted_metrics: set[str] = set()

        # Read before the metric loops so every point the session produces carries them.
        for context_field, metadata_key in WORKOUT_CONTEXT_FIELDS.items():
            if context_field in workout:
                workout_metadata[metadata_key] = workout[context_field]

        for field_key, w_metric_type, fallback_unit in WORKOUT_FIELD_MAP:
            raw_field = workout.get(field_key)
            val = _extract_numeric_value(raw_field)
            if val is None:
                continue
            handled_workout_keys.add(field_key)
            # Both spellings of a quantity are listed in the map; the first one
            # present wins, so a payload carrying v1 and v2 names does not emit two
            # points with one idempotency key.
            if w_metric_type in emitted_metrics:
                continue
            emitted_metrics.add(w_metric_type)

            # Workout fields carry their unit inside the field object rather than
            # alongside the metric, and distance in particular follows the phone's
            # locale — miles on one, kilometres on the next.
            field_units = str(raw_field.get("units") or "") if isinstance(raw_field, dict) else ""

            data_points.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": w_metric_type,
                    "timestamp": ts,
                    "value": normalise_value(val, field_units, w_metric_type, fallback_unit),
                    "metadata": {
                        **workout_metadata,
                        "units": field_units,
                        "provider_value": val,
                    },
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, w_metric_type, ts
                    ),
                    "source_type": "apple_health",
                }
            )
            report.mapped(f"workouts.{field_key}", raw_field, w_metric_type)

        # Objects holding more than one quantity: `heartRate` is `{Min, Avg, Max}`.
        # After the loop above, so a payload still sending the v1 scalars keeps them and
        # does not emit the same metric twice at one timestamp.
        for field_key, members in WORKOUT_OBJECT_FIELDS.items():
            container = workout.get(field_key)
            if not isinstance(container, dict):
                continue
            handled_workout_keys.add(field_key)
            field_units = str(container.get("units") or "")
            claimed = {member.lower() for member in members}
            # A minimum has no registry metric, and inventing one would be a metric
            # nobody else writes; it is carried instead, as `ENTRY_CONTEXT_FIELDS` does.
            context = {
                key: value
                for key, value in container.items()
                if key.lower() not in claimed and _extract_numeric_value(value) is not None
            }

            for member, w_metric_type in members.items():
                val = _extract_numeric_value(_member_value(container, member))
                if val is None or w_metric_type in emitted_metrics:
                    continue
                emitted_metrics.add(w_metric_type)
                data_points.append(
                    {
                        "tenant_id": tenant_id,
                        "source_id": source_id,
                        "metric_type": w_metric_type,
                        "timestamp": ts,
                        "value": normalise_value(val, field_units, w_metric_type),
                        "metadata": {
                            **workout_metadata,
                            "units": field_units,
                            "provider_value": val,
                            **context,
                        },
                        "idempotency_key": generate_idempotency_key(
                            tenant_id, source_id, w_metric_type, ts
                        ),
                        "source_type": "apple_health",
                    }
                )
                report.mapped(f"workouts.{field_key}.{member}", val, w_metric_type)

        # Time series, interpreted rather than dropped. Read after the scalar fields, so
        # a figure the provider stated outright always wins over one derived here.
        collected: dict[str, dict[str, Any]] = {}
        for field_key, w_metric_type, how in WORKOUT_SERIES_MAP:
            samples = workout.get(field_key)
            if not isinstance(samples, list) or not samples:
                continue
            handled_workout_keys.add(field_key)
            if w_metric_type in emitted_metrics:
                continue
            figure, field_units, count = _series_figure(samples, how)
            if figure is None:
                continue
            into = collected.setdefault(
                w_metric_type,
                {"how": how, "figures": [], "units": field_units, "fields": [], "samples": 0},
            )
            into["figures"].append(figure)
            into["fields"].append(field_key)
            into["samples"] += count
            if not into["units"]:
                into["units"] = field_units

        for w_metric_type, gathered in collected.items():
            figures: list[float] = gathered["figures"]
            how = gathered["how"]
            # Several series can state one quantity: active plus basal energy is the
            # session total, which is the figure `workout_energy` holds.
            if how == "sum":
                figure = sum(figures)
            elif how == "max":
                figure = max(figures)
            else:
                figure = sum(figures) / len(figures)

            emitted_metrics.add(w_metric_type)
            field_units = str(gathered["units"])
            data_points.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "metric_type": w_metric_type,
                    "timestamp": ts,
                    "value": normalise_value(figure, field_units, w_metric_type),
                    "metadata": {
                        **workout_metadata,
                        "units": field_units,
                        "provider_value": figure,
                        # Provenance, because this number is ours and not the phone's:
                        # which series it came from, how it was collapsed, and out of
                        # how many samples.
                        "derived_from": list(gathered["fields"]),
                        "derived_by": how,
                        "sample_count": gathered["samples"],
                    },
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, w_metric_type, ts
                    ),
                    "source_type": "apple_health",
                }
            )
            for field_key in gathered["fields"]:
                report.mapped(f"workouts.{field_key}", [], w_metric_type)

        # The context fields are reported against a metric this session produced,
        # because that is what carries them — the report's vocabulary is "this path
        # became that metric", and metadata on a point is how a field that is not a
        # measurement still arrives. A workout that produced no metric carried them
        # nowhere, so there they stay listed as arriving and unstored, which is true.
        anchor = next(
            (metric for _, metric, _ in WORKOUT_FIELD_MAP if metric in emitted_metrics),
            next(
                (m for m in WORKOUT_OBJECT_METRICS.values() if m in emitted_metrics),
                None,
            ),
        )
        if anchor is not None:
            for context_field in WORKOUT_CONTEXT_FIELDS:
                if context_field not in workout:
                    continue
                handled_workout_keys.add(context_field)
                report.mapped(f"workouts.{context_field}", workout[context_field], anchor)

        # GPS route. Each fix is its own `location_point`, keyed on its own
        # timestamp, so a route is a trace rather than one point per workout.
        route = workout.get("route")
        if isinstance(route, list) and route:
            handled_workout_keys.add("route")
            data_points.extend(
                route_points(route, tenant_id, source_id, workout_id, workout_name, report)
            )

        for key, value in workout.items():
            if key in handled_workout_keys:
                continue
            report.unmapped(f"workouts.{key}", value)

    return data_points


def route_points(
    route: list[Any],
    tenant_id: str,
    source_id: str,
    workout_id: str,
    workout_name: str,
    report: FieldReportCollector,
) -> list[dict[str, Any]]:
    """One `location_point` per GPS fix in a workout route.

    Health Auto Export spells the coordinates `latitude`/`longitude` in its current
    format and `lat`/`lon` in the older one; both are read, because a phone that has
    not been updated is not a reason to lose somebody's route.

    The coordinates travel in metadata, which is where the location importer already
    puts them and where the map reads them from.
    """
    points: list[dict[str, Any]] = []
    for fix in route:
        if not isinstance(fix, dict):
            continue
        # Membership, not `or`: a coordinate of exactly 0.0 is falsy, so `or` sent
        # every fix on the equator or the Greenwich meridian -- London, Accra --
        # down the older-spelling branch and then dropped it.
        latitude = _extract_numeric_value(
            fix["latitude"] if "latitude" in fix else fix.get("lat")
        )
        longitude = _extract_numeric_value(
            fix["longitude"] if "longitude" in fix else fix.get("lon")
        )
        ts = parse_timestamp(str(fix.get("timestamp") or ""))
        if latitude is None or longitude is None or ts is None:
            continue

        metadata: dict[str, Any] = {
            "source_type": "apple_health",
            "latitude": latitude,
            "longitude": longitude,
            "workout_name": workout_name,
            # A fix's `value` is a marker; what it actually measured is the pair of
            # coordinates above. The provenance pair still travels, so that every point
            # in the platform can answer the same question the same way (rule 19).
            **provenance("location_point", 1.0),
        }
        if workout_id:
            metadata["workout_id"] = workout_id
        for optional, key in (
            ("altitude", "altitude"),
            ("speed", "speed"),
            ("horizontalAccuracy", "horizontal_accuracy"),
            ("verticalAccuracy", "vertical_accuracy"),
            ("course", "course"),
        ):
            value = _extract_numeric_value(fix.get(optional))
            if value is not None:
                metadata[key] = value

        points.append(
            {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": "location_point",
                "timestamp": ts,
                "value": 1.0,
                "metadata": metadata,
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, "location_point", ts
                ),
                "source_type": "apple_health",
            }
        )

    if points:
        report.mapped("workouts.route[]", route[0], "location_point")
    return points
