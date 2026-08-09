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

from shared_schemas import FieldReportCollector, idempotency_key
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
        metadata = {
            "source_type": "whoop",
            "whoop_id": whoop_id,
            "kind": kind,
        }

        consumed: set[str] = {"score_state", "start", "created_at", "id", "cycle_id"}
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

            point_metadata = dict(metadata)
            if mapping.provider_unit is not None:
                # Keep the raw reading: a conversion factor is a lossy edit to somebody's
                # data, and the original is what a support question is about.
                point_metadata["provider_value"] = float(val)
                point_metadata["provider_unit"] = mapping.provider_unit.value

            data_points.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
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

        for key, value in record.items():
            if key in consumed:
                continue
            report.unmapped(f"{kind}.{key}", value)

    return data_points
