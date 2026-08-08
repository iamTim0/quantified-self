"""Transform weather records to canonical ingestion events.

The previous transformer emitted a single metric named ``weather`` carrying only
``temperature_2m``, and stamped records lacking a timestamp with ``now()`` — which
produced a fresh ``idempotency_key`` on every sync and therefore a duplicate row
each time. Every requested variable is now its own metric series, and a record
without a parseable timestamp is skipped rather than invented.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from shared_schemas.metrics import UnknownMetricTypeError, canonical_metric_type

logger = logging.getLogger(__name__)

SOURCE_TYPE = "weather"

# Provider variable -> canonical metric name from the shared registry
# (packages/shared-schemas/src/shared_schemas/metrics.py). The names used to carry
# their unit as a suffix -- `weather_temperature_c`, `weather_wind_speed_kmh` -- which
# is exactly what the registry replaced: the unit is a property of the metric, and
# putting it in the name meant a unit change silently became a second metric.
# Open-Meteo already delivers these variables in the registry's units, so nothing here
# needs converting.
METRIC_NAMES = {
    "temperature_2m": "weather_temperature",
    "apparent_temperature": "weather_temperature_apparent",
    "relative_humidity_2m": "weather_humidity",
    "precipitation": "weather_precipitation",
    "surface_pressure": "weather_pressure",
    "wind_speed_10m": "weather_wind_speed",
    "cloud_cover": "weather_cloud_cover",
    "uv_index": "weather_uv_index",
}


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4."""
    return hashlib.sha256(
        f"{tenant_id}:{source_id}:{metric_type}:{timestamp}".encode()
    ).hexdigest()


def _normalise_timestamp(raw: Any) -> str | None:
    """Open-Meteo emits local wall-clock like ``2026-08-05T14:00``; anchor it to UTC."""
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def transform(
    records: list[dict[str, Any]], tenant_id: str, source_id: str
) -> list[dict[str, Any]]:
    """One event per (hour, variable)."""
    events: list[dict[str, Any]] = []

    for record in records:
        timestamp = _normalise_timestamp(record.get("time") or record.get("timestamp"))
        if timestamp is None:
            # No usable timestamp means no deterministic key; skip rather than
            # substitute now(), which duplicated a row on every sync.
            continue

        for variable, metric in METRIC_NAMES.items():
            if variable not in record:
                continue
            try:
                value = float(record[variable])
            except (TypeError, ValueError):
                continue

            events.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "source_type": SOURCE_TYPE,
                    "metric_type": metric,
                    "timestamp": timestamp,
                    "value": value,
                    "metadata": {"source_type": SOURCE_TYPE, "variable": variable},
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, metric, timestamp
                    ),
                }
            )

        # Providers that already deliver a single named metric per row. The name comes
        # from outside, so it goes through the registry rather than straight into the
        # database -- an unrecognised one is dropped with a log line instead of minting
        # a metric nobody can interpret.
        if "metric_type" in record and "value" in record:
            try:
                metric = canonical_metric_type(str(record["metric_type"]))
            except UnknownMetricTypeError:
                logger.warning(
                    "Skipping unregistered metric_type %r from the weather provider",
                    record["metric_type"],
                )
                continue
            try:
                value = float(record["value"])
            except (TypeError, ValueError):
                continue
            events.append(
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "source_type": SOURCE_TYPE,
                    "metric_type": metric,
                    "timestamp": timestamp,
                    "value": value,
                    "metadata": {"source_type": SOURCE_TYPE},
                    "idempotency_key": generate_idempotency_key(
                        tenant_id, source_id, metric, timestamp
                    ),
                }
            )

    return events
