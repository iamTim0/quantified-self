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

from typing import Any, NamedTuple

from shared_schemas import FieldReportCollector, idempotency_key, provenance
from shared_schemas.metrics import (
    METRIC_CATALOG,
    MetricUnit,
    canonical_metric_type,
    convert,
)


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
    ),
}


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

    ``report`` is optional and currently only supplied by the export reader — the
    polled path has no submit side yet, so passing one there would collect
    sightings nobody reads. See `docs/features/data-quality.md`.

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
