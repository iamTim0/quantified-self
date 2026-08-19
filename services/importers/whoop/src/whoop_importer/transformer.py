"""Transformer for WHOOP Metrics into Standardized DataPoints.

Metric names and units come from the shared registry
(packages/shared-schemas/src/shared_schemas/metrics.py). Two things changed when it
was introduced:

* WHOOP reports burned energy in **kilojoules** and Apple Health reports it in
  kilocalories. Both used to be stored raw under names that mentioned neither unit,
  so Core's cross-source conflict detection compared 8400 against 2000 and called it a
  disagreement. Energy is now converted to kcal on the way in.
* Names that were WHOOP's field names (``hrv_rmssd_milli``, ``skin_temp_celsius``,
  ``workout_average_heart_rate``) are now the platform's names, so the same quantity
  from another source lands in the same series -- except for the two genuinely
  proprietary indices, which keep a ``whoop_`` prefix precisely because nothing else
  produces a comparable number.
"""

from datetime import datetime
from typing import Any, NamedTuple

from shared_schemas import FieldReportCollector, idempotency_key, provenance
from shared_schemas.activities import activity_metadata
from shared_schemas.metrics import (
    METRIC_CATALOG,
    MetricUnit,
    canonical_metric_type,
    convert,
)
from shared_schemas.sessions import session_metadata


class _Mapping(NamedTuple):
    """Where a value sits in the WHOOP payload, and what it has to become.

    ``section`` is the nested object the API wraps its numbers in — always
    ``"score"`` there. The emailed CSV export is flat, so it passes an empty
    section and the field is read from the record directly. The names and units
    are the same either way, which is the point of sharing this table: an export
    and a polled sync must produce the same metric under the same name.
    """

    metric_type: str
    section: str
    field: str
    #: Unit WHOOP reports in, when it differs from the registry's unit for the metric.
    #: ``None`` means WHOOP already reports in the canonical unit.
    provider_unit: MetricUnit | None = None


class _MetadataMapping(NamedTuple):
    """A provider field carried as context on the related metric point."""

    field: str
    metadata_key: str
    section: str = ""


def _parse_moment(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def derived_workout_points(
    record: dict[str, Any],
    *,
    tenant_id: str,
    source_id: str,
    timestamp: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    """The two workout figures WHOOP implies rather than states.

    Both were missing from the polled path while the emailed export carried them,
    so a connector that was working normally reported *less* than one somebody had
    uploaded an archive to.

    Neither is a field WHOOP sends, so both declare how they were reached
    (rule 19). That needs two `derived_by` verbs the registry did not previously
    use — `difference` for a span between two instants, and `share` for a part
    expressed as a percentage of a whole. They are documented in `docs/metrics.md`
    beside the existing five, because extending that vocabulary is a decision that
    gets written down rather than one a transformer makes on its own.
    """
    points: list[dict[str, Any]] = []

    def emit(metric_type: str, value: float, extra: dict[str, Any]) -> None:
        canonical = canonical_metric_type(metric_type)
        points.append(
            {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "source_type": "whoop",
                "metric_type": canonical,
                "timestamp": timestamp,
                "value": value,
                "metadata": {
                    **metadata,
                    **provenance(canonical, value),
                    **extra,
                },
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, canonical, timestamp
                ),
            }
        )

    start = _parse_moment(record.get("start"))
    end = _parse_moment(record.get("end"))
    if start is not None and end is not None and end > start:
        emit(
            "workout_duration",
            (end - start).total_seconds() / 60.0,
            {
                "derived_from": ["start", "end"],
                "derived_by": "difference",
                "sample_count": 2,
            },
        )

    zones = (record.get("score") or {}).get("zone_duration")
    if isinstance(zones, dict):
        durations = {
            field: float(zones[field])
            for field, _ in _ZONE_FIELDS
            if isinstance(zones.get(field), (int, float))
            and not isinstance(zones.get(field), bool)
        }
        total = sum(durations.values())
        if total > 0:
            for field, metric_type in _ZONE_FIELDS:
                if metric_type is None or field not in durations:
                    continue
                emit(
                    metric_type,
                    durations[field] / total * 100.0,
                    {
                        "derived_from": [f"score.zone_duration.{field}"],
                        "derived_by": "share",
                        # The buckets the denominator stands on, which is what
                        # makes a share auditable: a session WHOOP reported four
                        # zones for is a different denominator from one it
                        # reported six for.
                        "sample_count": len(durations),
                        # Below-zone-1 time is part of the session and part of the
                        # denominator, so the reader can see why five shares do not
                        # add up to a hundred.
                        "zone_below_one_ms": durations.get("zone_zero_milli"),
                        "zone_total_ms": total,
                    },
                )

    return points


#: SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4, defined once
#: in `shared_schemas`. An alias rather than a wrapper: a wrapper would be a fifth
#: identical docstring to keep in step, and its `timestamp: str` annotation would hide
#: that the shared function also takes a `datetime`.
generate_idempotency_key = idempotency_key


METRICS: dict[str, tuple[_Mapping, ...]] = {
    "cycle": (
        _Mapping("whoop_strain", "score", "strain"),
        _Mapping("energy_total", "score", "kilojoule", MetricUnit.KILOJOULE),
        _Mapping("heart_rate_average", "score", "average_heart_rate"),
        _Mapping("heart_rate_max", "score", "max_heart_rate"),
    ),
    "recovery": (
        _Mapping("whoop_recovery_score", "score", "recovery_score"),
        _Mapping("heart_rate_resting", "score", "resting_heart_rate"),
        _Mapping("hrv_rmssd", "score", "hrv_rmssd_milli"),
        _Mapping("blood_oxygen", "score", "spo2_percentage"),
        _Mapping("skin_temperature", "score", "skin_temp_celsius"),
    ),
    "sleep": (
        _Mapping("whoop_sleep_performance", "score", "sleep_performance_percentage"),
        _Mapping("sleep_efficiency", "score", "sleep_efficiency_percentage"),
        _Mapping("respiratory_rate", "score", "respiratory_rate"),
    ),
    "workout": (
        _Mapping("whoop_workout_strain", "score", "strain"),
        _Mapping("workout_energy", "score", "kilojoule", MetricUnit.KILOJOULE),
        _Mapping("workout_heart_rate_average", "score", "average_heart_rate"),
        _Mapping("workout_distance", "score", "distance_meter", MetricUnit.METER),
        # The polled path used to emit four of these where the emailed CSV export
        # emitted eleven, so the same connector said less when it was working
        # normally than when somebody uploaded an archive. Both fields below are
        # in every v2 workout payload and were simply never read.
        _Mapping("workout_heart_rate_max", "score", "max_heart_rate"),
        _Mapping("workout_elevation_gain", "score", "altitude_gain_meter", MetricUnit.METER),
    ),
}

#: WHOOP's heart-rate zone buckets, in order, as they appear under
#: `score.zone_duration`. Six of them against the registry's five metrics: zone zero
#: is the time spent *below* zone 1, which is not a zone anyone trains in but is part
#: of the session. It counts toward the denominator and is carried as metadata —
#: folding it into zone 1 would inflate the lowest band, and dropping it would make
#: the five shares sum to more than the session.
_ZONE_FIELDS: tuple[tuple[str, str | None], ...] = (
    ("zone_zero_milli", None),
    ("zone_one_milli", "workout_heart_rate_zone_1"),
    ("zone_two_milli", "workout_heart_rate_zone_2"),
    ("zone_three_milli", "workout_heart_rate_zone_3"),
    ("zone_four_milli", "workout_heart_rate_zone_4"),
    ("zone_five_milli", "workout_heart_rate_zone_5"),
)


# The export contains useful context that is not itself a time series: activity
# names, timestamps, the cycle timezone and whether GPS was enabled. Keeping those
# values on each related point makes them available to consumers without inventing a
# metric whose aggregation would be meaningless. The API uses the same concepts under
# its own field names, so both input paths are listed here.
_REPEATED_SLEEP_FIELDS: tuple[_MetadataMapping, ...] = (
    _MetadataMapping("sleep_duration_minutes", "sleep_duration"),
    _MetadataMapping("sleep_in_bed_minutes", "sleep_duration_in_bed"),
    _MetadataMapping("sleep_light_minutes", "sleep_duration_light"),
    _MetadataMapping("sleep_deep_minutes", "sleep_duration_deep"),
    _MetadataMapping("sleep_rem_minutes", "sleep_duration_rem"),
    _MetadataMapping("sleep_awake_minutes", "sleep_duration_awake"),
    _MetadataMapping("sleep_efficiency_percentage", "sleep_efficiency"),
    _MetadataMapping("sleep_performance_percentage", "whoop_sleep_performance"),
    _MetadataMapping("sleep_need_minutes", "whoop_sleep_need"),
    _MetadataMapping("sleep_consistency_percentage", "whoop_sleep_consistency"),
    _MetadataMapping("sleep_debt_minutes", "whoop_sleep_debt"),
)
_SLEEP_NAP_FIELD = "sleep_nap_count"


METADATA_FIELDS: dict[str, tuple[_MetadataMapping, ...]] = {
    "cycle": (
        _MetadataMapping("cycle_start_time", "cycle_start_time"),
        _MetadataMapping("start", "cycle_start_time"),
        _MetadataMapping("cycle_end_time", "cycle_end_time"),
        _MetadataMapping("end", "cycle_end_time"),
        _MetadataMapping("cycle_timezone", "cycle_timezone"),
        _MetadataMapping("timezone_offset", "cycle_timezone"),
        _MetadataMapping("sleep_start_time", "sleep_start_time"),
        _MetadataMapping("sleep_onset", "sleep_start_time"),
        _MetadataMapping("wake_start_time", "wake_start_time"),
        _MetadataMapping("sleep_wake_start", "wake_start_time"),
        *_REPEATED_SLEEP_FIELDS,
    ),
    "recovery": (
        _MetadataMapping("cycle_start_time", "cycle_start_time"),
        _MetadataMapping("start", "cycle_start_time"),
        _MetadataMapping("cycle_end_time", "cycle_end_time"),
        _MetadataMapping("end", "cycle_end_time"),
        _MetadataMapping("cycle_timezone", "cycle_timezone"),
        _MetadataMapping("timezone_offset", "cycle_timezone"),
        _MetadataMapping("sleep_start_time", "sleep_start_time"),
        _MetadataMapping("sleep_onset", "sleep_start_time"),
        _MetadataMapping("wake_start_time", "wake_start_time"),
        _MetadataMapping("sleep_wake_start", "wake_start_time"),
        *_REPEATED_SLEEP_FIELDS,
    ),
    "sleep": (
        _MetadataMapping("sleep_start_time", "sleep_start_time"),
        _MetadataMapping("start", "sleep_start_time"),
        _MetadataMapping("sleep_end_time", "sleep_end_time"),
        _MetadataMapping("end", "sleep_end_time"),
        _MetadataMapping("cycle_start_time", "cycle_start_time"),
        _MetadataMapping("cycle_end_time", "cycle_end_time"),
        _MetadataMapping("cycle_timezone", "cycle_timezone"),
        _MetadataMapping("timezone_offset", "cycle_timezone"),
        # Some export locales spell the nap value as a label rather than a number;
        # the metric mapping handles numeric values and this keeps other spellings.
        _MetadataMapping(_SLEEP_NAP_FIELD, "sleep_nap_count"),
        _MetadataMapping("sleep_nap_flag", "sleep_nap_flag"),
    ),
    "workout": (
        _MetadataMapping("workout_start_time", "workout_start_time"),
        _MetadataMapping("start", "workout_start_time"),
        _MetadataMapping("workout_end_time", "workout_end_time"),
        _MetadataMapping("end", "workout_end_time"),
        _MetadataMapping("cycle_start_time", "cycle_start_time"),
        _MetadataMapping("cycle_end_time", "cycle_end_time"),
        _MetadataMapping("cycle_timezone", "cycle_timezone"),
        _MetadataMapping("timezone_offset", "cycle_timezone"),
        _MetadataMapping("activity_name", "activity_name"),
        _MetadataMapping("sport_name", "activity_name"),
        _MetadataMapping("gps_enabled", "gps_enabled"),
    ),
}


def _metadata_for_record(record: dict[str, Any], kind: str) -> tuple[dict[str, Any], set[str]]:
    """Return selected context fields and the source keys they consumed."""
    metadata: dict[str, Any] = {}
    consumed: set[str] = set()
    for mapping in METADATA_FIELDS.get(kind, ()):
        container = (record.get(mapping.section) or {}) if mapping.section else record
        value = container.get(mapping.field)
        if value is None or value == "":
            continue
        metadata.setdefault(mapping.metadata_key, value)
        consumed.add(mapping.section or mapping.field)
    return metadata, consumed


def transform_whoop_records(
    kind: str,
    records: list[dict[str, Any]],
    tenant_id: str,
    source_id: str,
    *,
    require_scored: bool = True,
    mappings: dict[str, tuple[_Mapping, ...]] | None = None,
    report: FieldReportCollector | None = None,
) -> list[dict[str, Any]]:
    """Transform WHOOP records into standard DataPoints.

    ``mappings`` names where the numbers sit and what unit they arrive in. The
    export declares its own because it reports the same quantities in different
    units — its energy column is already kilocalories where the API sends
    kilojoules, and reading one as the other is wrong by a factor of four. What it
    must *not* change is the metric names, which is why both tables spell them the
    same (rule 15).

    ``report`` is optional, and both paths supply one: the export reader, and the
    polled sync since it gained a submit side in `main.py`. It stays optional so a
    caller that only wants the points — a test, a dry run — need not build one.
    See `docs/features/data-quality.md`.

    ``require_scored`` guards the API path, where an unscored record is one WHOOP
    has not finished processing and whose numbers would change. The CSV export has
    no such column — every row in it is final — so the export passes ``False``
    rather than having every row silently discarded.
    """
    data_points: list[dict[str, Any]] = []
    report = report or FieldReportCollector()

    for record in records:
        if not isinstance(record, dict):
            continue
        if require_scored and record.get("score_state") != "SCORED":
            continue

        ts = str(record.get("start") or record.get("created_at") or "")
        if not ts:
            continue

        whoop_id = str(record.get("id") or record.get("cycle_id") or "")
        record_metadata, metadata_fields = _metadata_for_record(record, kind)
        metadata = {
            "source_type": "whoop",
            "whoop_id": whoop_id,
            "kind": kind,
            **record_metadata,
        }

        # Only a workout is a session. A cycle is a day and a sleep is a night;
        # giving either a `session_id` would put them on the workout list, which
        # is not what a reader means by "my workouts".
        if kind == "workout":
            activity = str(record_metadata.get("activity_name") or "Workout")
            metadata.update(
                session_metadata(
                    source_type="whoop",
                    source_id=source_id,
                    provider_session_id=whoop_id or None,
                    start=ts,
                    end=record.get("end") or record_metadata.get("workout_end_time"),
                    label=activity,
                    derived_from=("start", "sport_name"),
                )
            )
            # `activity_name` is WHOOP's word for it and Apple's key is a different
            # one entirely, so neither is something a query can filter on. The
            # canonical type is (rule 17); the provider's own wording stays beside
            # it as `activity_label`.
            metadata.update(activity_metadata(activity))

        consumed: set[str] = {"score_state", "start", "created_at", "id", "cycle_id"}
        consumed.update(metadata_fields)
        mapped_metric_types: list[str] = []
        for mapping in (mappings or METRICS).get(kind, ()):
            metric_type = canonical_metric_type(mapping.metric_type)
            container = (record.get(mapping.section) or {}) if mapping.section else record
            val = container.get(mapping.field)
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            consumed.add(mapping.section or mapping.field)

            value = float(val)
            if mapping.provider_unit is not None:
                value = convert(
                    value,
                    mapping.provider_unit,
                    METRIC_CATALOG[metric_type].unit,
                )

            point_metadata = {
                **metadata,
                **provenance(
                    metric_type,
                    float(val),
                    mapping.provider_unit.value if mapping.provider_unit is not None else None,
                ),
            }

            data_points.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "source_type": "whoop",
                    "metric_type": metric_type,
                    "timestamp": ts,
                    "value": value,
                    "metadata": point_metadata,
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, metric_type, ts
                    ),
                }
            )
            report.mapped(f"{kind}.{mapping.field}", val, metric_type)
            mapped_metric_types.append(metric_type)

        # Figures WHOOP implies rather than states: the session's duration, and
        # each heart-rate zone as a share of it. Only on the API path — the CSV
        # export states its own duration and has no zone columns, and a derived
        # figure must never overwrite one the provider gave (rule 19).
        if kind == "workout" and mappings is None:
            derived = derived_workout_points(
                record,
                tenant_id=tenant_id,
                source_id=source_id,
                timestamp=ts,
                metadata=metadata,
            )
            for point in derived:
                if point["metric_type"] in mapped_metric_types:
                    continue
                data_points.append(point)
                mapped_metric_types.append(point["metric_type"])
            if derived:
                consumed.add("end")
                consumed.add("score")

        # A metadata field is reported once per input record, rather than once per
        # metric point. The first mapped metric is the point that makes the context
        # usable; the context itself is also copied onto the other points above.
        if mapped_metric_types:
            for mapping in METADATA_FIELDS.get(kind, ()):
                container = (record.get(mapping.section) or {}) if mapping.section else record
                value = container.get(mapping.field)
                if value is not None and value != "" and mapping.metadata_key in record_metadata:
                    report.mapped(
                        f"{kind}.{mapping.field}", value, mapped_metric_types[0]
                    )
        else:
            # A context-only row has no point on which it can travel. Name it in the
            # shape report instead of allowing a recognised field to disappear.
            for mapping in METADATA_FIELDS.get(kind, ()):
                container = (record.get(mapping.section) or {}) if mapping.section else record
                value = container.get(mapping.field)
                if value is not None and value != "" and mapping.metadata_key in record_metadata:
                    report.unmapped(f"{kind}.{mapping.field}", value)

        for key, value in record.items():
            if key in consumed:
                continue
            report.unmapped(f"{kind}.{key}", value)

    return data_points
