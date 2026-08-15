"""Bounded, provenance-preserving ingestion aggregation.

Importers use this module before publishing to NATS. It deliberately contains no
database or network code: the same deterministic transformation can therefore be
used by push payloads and file imports, and Core remains the only database owner.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .events import idempotency_key
from .metrics import (
    METRIC_CATALOG,
    Aggregation,
    IngestResolution,
    canonical_metric_type,
    describe,
)


def _as_datetime(value: Any) -> datetime:
    """Parse an event timestamp and normalize it to UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def bucket_timestamp(timestamp: Any, resolution: IngestResolution | str) -> datetime:
    """Return the UTC start of an ingestion bucket."""
    ts = _as_datetime(timestamp)
    resolved = IngestResolution(resolution)
    if resolved is IngestResolution.MINUTE:
        return ts.replace(second=0, microsecond=0)
    if resolved is IngestResolution.HOUR:
        return ts.replace(minute=0, second=0, microsecond=0)
    if resolved is IngestResolution.DAY:
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    return ts


def default_policies() -> dict[str, dict[str, Any]]:
    """Serialize registry defaults for an importer that cannot reach Core."""
    return {
        key: {
            "resolution": definition.default_ingest_resolution.value,
            "aggregation": definition.aggregation.value,
            "raw_retention_days": definition.raw_retention_days,
        }
        for key, definition in METRIC_CATALOG.items()
    }


def _policy_for(metric_type: str, policies: Mapping[str, Mapping[str, Any]] | None) -> tuple[IngestResolution, Aggregation]:
    """Resolve a validated metric to its configured resolution and operation."""
    definition = describe(metric_type)
    override = (policies or {}).get(metric_type, {})
    raw_resolution = override.get("resolution") or definition.default_ingest_resolution.value
    try:
        resolution = IngestResolution(str(raw_resolution))
    except ValueError:
        resolution = definition.default_ingest_resolution
    raw_aggregation = override.get("aggregation") or definition.aggregation.value
    try:
        aggregation = Aggregation(str(raw_aggregation))
    except ValueError:
        aggregation = definition.aggregation
    return resolution, aggregation


def _numeric_provider_value(event: Mapping[str, Any]) -> float | None:
    """Read the compact provider value used for provenance without raw payloads."""
    value = (event.get("metadata") or {}).get("provider_value")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _provider_total_event(
    event: Mapping[str, Any],
    *,
    metric_type: str,
    source_key: str,
) -> dict[str, Any]:
    """Normalize an authoritative daily total for rollup precedence."""
    result = dict(event)
    timestamp = bucket_timestamp(event["timestamp"], IngestResolution.DAY)
    result["metric_type"] = metric_type
    result["timestamp"] = timestamp.isoformat()
    metadata = dict(result.get("metadata") or {})
    metadata.update(
        {
            "provider_total": True,
            "ingest_resolution": IngestResolution.DAY.value,
            "sample_count": 1,
        }
    )
    result["metadata"] = metadata
    result["idempotency_key"] = idempotency_key(
        str(result["tenant_id"]),
        source_key,
        metric_type,
        timestamp,
    )
    return result


def _aggregate_group(events: list[dict[str, Any]], aggregation: Aggregation) -> dict[str, Any]:
    """Collapse one metric/bucket group and add auditable derivation metadata."""
    ordered = sorted(events, key=lambda item: _as_datetime(item["timestamp"]))
    values = [float(item["value"]) for item in ordered if item.get("value") is not None]
    if not values:
        result = dict(ordered[-1])
    elif aggregation is Aggregation.SUM:
        result = dict(ordered[-1])
        result["value"] = sum(values)
    elif aggregation is Aggregation.MAX:
        result = dict(ordered[-1])
        result["value"] = max(values)
    elif aggregation is Aggregation.LAST:
        result = dict(ordered[-1])
    else:
        result = dict(ordered[-1])
        result["value"] = sum(values) / len(values)

    metadata = dict(result.get("metadata") or {})
    provider_values = [value for event in ordered if (value := _numeric_provider_value(event)) is not None]
    if provider_values:
        if aggregation is Aggregation.SUM:
            metadata["provider_value"] = sum(provider_values)
        elif aggregation is Aggregation.MAX:
            metadata["provider_value"] = max(provider_values)
        elif aggregation is Aggregation.LAST:
            metadata["provider_value"] = provider_values[-1]
        else:
            metadata["provider_value"] = sum(provider_values) / len(provider_values)
    metadata.update(
        {
            "derived_from": [ordered[0].get("metric_type")],
            "derived_by": aggregation.value,
            "sample_count": len(ordered),
            "ingest_resolution": metadata.get("ingest_resolution") or "bucket",
        }
    )
    result["metadata"] = metadata
    timestamp = _as_datetime(result["timestamp"])
    result["timestamp"] = timestamp.isoformat()
    source_for_key = str(result.get("idempotency_source_id") or result["source_id"])
    result["idempotency_key"] = idempotency_key(
        str(result["tenant_id"]),
        source_for_key,
        canonical_metric_type(str(result["metric_type"])),
        timestamp,
    )
    return result


def aggregate_events(
    events: Iterable[dict[str, Any]],
    policies: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate events according to metric policies.

    Provider totals win over derived samples in the same bucket. This prevents a
    daily Apple total from being added to the per-interval values that produced it.
    Raw policies preserve the original event objects and their idempotency keys.
    """
    passthrough: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    provider_totals: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    aggregations: dict[tuple[str, str, str, str], Aggregation] = {}
    prepared: list[tuple[dict[str, Any], str, IngestResolution, Aggregation, str]] = []
    provider_days: set[tuple[str, str, str]] = set()

    for original in events:
        event = dict(original)
        metric_type = canonical_metric_type(str(event["metric_type"]))
        event["metric_type"] = metric_type
        resolution, aggregation = _policy_for(metric_type, policies)
        source_key = str(event.get("idempotency_source_id") or event["source_id"])
        prepared.append((event, metric_type, resolution, aggregation, source_key))
        if (event.get("metadata") or {}).get("provider_total") is True and aggregation is Aggregation.SUM:
            provider_days.add(
                (source_key, metric_type, bucket_timestamp(event["timestamp"], IngestResolution.DAY).isoformat())
            )

    for event, metric_type, resolution, aggregation, source_key in prepared:
        if resolution is IngestResolution.RAW:
            # Raw mode is an explicit request to preserve the provider event. Legacy
            # rows without this marker are treated as raw by the retention command.
            passthrough.append(event)
            continue
        bucket = bucket_timestamp(event["timestamp"], resolution)
        day_key = (source_key, metric_type, bucket_timestamp(bucket, IngestResolution.DAY).isoformat())
        if (
            aggregation is Aggregation.SUM
            and (event.get("metadata") or {}).get("provider_total") is not True
            and day_key in provider_days
        ):
            # A provider total is the authoritative statement for the whole day;
            # retaining its interval components would create a second value with the
            # same deterministic key at the day boundary.
            continue
        key = (source_key, metric_type, resolution.value, bucket.isoformat())
        aggregations[key] = aggregation
        metadata = event.get("metadata") or {}
        if metadata.get("provider_total") is True:
            provider_totals[key].append(event)
        else:
            event["timestamp"] = bucket.isoformat()
            event_metadata = dict(event.get("metadata") or {})
            event_metadata["ingest_resolution"] = resolution.value
            event["metadata"] = event_metadata
            groups[key].append(event)

    result = list(passthrough)
    all_keys = set(groups) | set(provider_totals)
    for key in sorted(all_keys):
        if provider_totals.get(key):
            # A provider statement is authoritative. Keep the newest statement and
            # mark it so later Core rollups can apply the same precedence.
            event = max(
                provider_totals[key], key=lambda item: _as_datetime(item["timestamp"])
            )
            result.append(
                _provider_total_event(
                    event,
                    metric_type=key[1],
                    source_key=key[0],
                )
            )
            continue
        entries = groups[key]
        result.append(_aggregate_group(entries, aggregations[key]))

    return sorted(result, key=lambda item: _as_datetime(item["timestamp"]))


def aggregate_stream(
    events: Iterable[dict[str, Any]],
    policies: Mapping[str, Mapping[str, Any]] | None = None,
) -> Iterable[dict[str, Any]]:
    """Aggregate a stream with bounded memory by flushing completed buckets.

    Apple archives are normally chronological. Closed minute/hour buckets are
    collapsed immediately. SUM buckets are held only as one aggregate per bucket
    until their UTC day closes, because a daily provider total may arrive after the
    interval samples and must win without an idempotency collision.
    """
    pending: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    completed_sum: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    provider_totals: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    latest_bucket: dict[tuple[str, str, str], datetime] = {}
    aggregations: dict[tuple[str, str, str, str], Aggregation] = {}

    def day_identity(source_key: str, metric_type: str, timestamp: Any) -> tuple[str, str, str]:
        return (
            source_key,
            metric_type,
            bucket_timestamp(timestamp, IngestResolution.DAY).isoformat(),
        )

    def remove_day_candidates(day_key: tuple[str, str, str]) -> None:
        """Drop interval candidates superseded by a provider total."""
        completed_sum.pop(day_key, None)
        for candidate in list(pending):
            if candidate[0] != day_key[0] or candidate[1] != day_key[1]:
                continue
            if bucket_timestamp(candidate[3], IngestResolution.DAY).isoformat() == day_key[2]:
                pending.pop(candidate, None)
                aggregations.pop(candidate, None)

    def flush_day(day_key: tuple[str, str, str]) -> list[dict[str, Any]]:
        totals = provider_totals.pop(day_key, [])
        if totals:
            return [max(totals, key=lambda item: _as_datetime(item["timestamp"]))]
        return completed_sum.pop(day_key, [])

    for event in events:
        metric_type = canonical_metric_type(str(event["metric_type"]))
        resolution, aggregation = _policy_for(metric_type, policies)
        if resolution is IngestResolution.RAW:
            raw_event = dict(event)
            yield raw_event
            continue
        bucket = bucket_timestamp(event["timestamp"], resolution)
        source_key = str(event.get("idempotency_source_id") or event["source_id"])
        metric_key = (source_key, metric_type, resolution.value)
        day_key = day_identity(source_key, metric_type, bucket)

        # A chronological stream can now close all earlier days for this metric.
        # This keeps the memory bound at one day's worth of already-aggregated
        # buckets, rather than one export's worth of samples.
        for old_day in sorted(
            {
                candidate
                for candidate in set(completed_sum) | set(provider_totals)
                if candidate[:2] == day_key[:2] and candidate[2] < day_key[2]
            }
        ):
            yield from flush_day(old_day)

        is_provider_total = (event.get("metadata") or {}).get("provider_total") is True
        if is_provider_total and aggregation is Aggregation.SUM:
            provider_event = _provider_total_event(
                event,
                metric_type=metric_type,
                source_key=source_key,
            )
            provider_totals[day_key].append(provider_event)
            remove_day_candidates(day_key)
            continue
        if aggregation is Aggregation.SUM and day_key in provider_totals:
            continue

        latest_bucket[metric_key] = max(bucket, latest_bucket.get(metric_key, bucket))
        key = (*metric_key, bucket.isoformat())
        aggregations[key] = aggregation
        event_copy = dict(event)
        event_copy["timestamp"] = bucket.isoformat()
        event_metadata = dict(event_copy.get("metadata") or {})
        event_metadata["ingest_resolution"] = resolution.value
        event_copy["metadata"] = event_metadata
        pending[key].append(event_copy)
        cutoff = latest_bucket[metric_key]
        for old_key in [
            candidate
            for candidate in pending
            if candidate[:3] == metric_key and _as_datetime(candidate[3]) < cutoff
        ]:
            entries = pending.pop(old_key, [])
            aggregation = aggregations.pop(old_key)
            if not entries:
                continue
            aggregate = _aggregate_group(entries, aggregation)
            if aggregation is Aggregation.SUM:
                completed_sum[day_identity(source_key, metric_type, old_key[3])].append(aggregate)
            else:
                yield aggregate

    for key in list(pending):
        entries = pending.pop(key, [])
        aggregation = aggregations.pop(key)
        if not entries:
            continue
        aggregate = _aggregate_group(entries, aggregation)
        if aggregation is Aggregation.SUM:
            completed_sum[day_identity(key[0], key[1], key[3])].append(aggregate)
        else:
            yield aggregate

    for day_key in sorted(set(completed_sum) | set(provider_totals)):
        yield from flush_day(day_key)
