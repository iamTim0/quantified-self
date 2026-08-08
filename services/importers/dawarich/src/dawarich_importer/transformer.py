"""Transformer for Dawarich Location Data into Standardized DataPoints."""

import hashlib
from datetime import datetime, timezone
from typing import Any

from shared_schemas.metrics import canonical_metric_type

# Resolved through the registry rather than spelled out as literals: if one of these
# is ever renamed in packages/shared-schemas/src/shared_schemas/metrics.py with the old
# name kept as an alias, this importer follows the rename instead of quietly writing an
# orphaned series -- and an unregistered name fails at import, not in production.
METRIC_POINT = canonical_metric_type("location_point")
METRIC_LATITUDE = canonical_metric_type("location_latitude")
METRIC_LONGITUDE = canonical_metric_type("location_longitude")


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """Generate deterministic SHA256 idempotency key per Rule 4."""
    raw = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_iso_timestamp(raw_timestamp: Any) -> str:
    """Normalize epoch or string timestamp to ISO 8601 UTC string."""
    if isinstance(raw_timestamp, (int, float)):
        dt = datetime.fromtimestamp(raw_timestamp, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(raw_timestamp, str) and raw_timestamp:
        try:
            dt = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def transform_dawarich_points(
    points: list[dict[str, Any]],
    tenant_id: str,
    source_id: str,
) -> list[dict[str, Any]]:
    """Transform Dawarich location points into standard DataPoints."""
    data_points: list[dict[str, Any]] = []

    for point in points:
        if not isinstance(point, dict):
            continue

        raw_lat = point.get("latitude") or point.get("lat")
        raw_lon = point.get("longitude") or point.get("lon") or point.get("lng")
        if raw_lat is None or raw_lon is None:
            continue

        try:
            lat = float(raw_lat)
            lon = float(raw_lon)
        except (ValueError, TypeError):
            continue

        raw_ts = point.get("timestamp") or point.get("created_at") or point.get("recorded_at")
        ts_iso = _normalize_iso_timestamp(raw_ts)

        altitude = point.get("altitude") or point.get("alt")
        speed = point.get("speed")

        metadata: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "source_type": "dawarich",
            "dawarich_point_id": str(point.get("id") or ""),
        }
        if altitude is not None:
            try:
                metadata["altitude"] = float(altitude)
            except (ValueError, TypeError):
                pass
        if speed is not None:
            try:
                metadata["speed"] = float(speed)
            except (ValueError, TypeError):
                pass

        # 1. Location Point Event
        dp_point = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": METRIC_POINT,
            "timestamp": ts_iso,
            "value": 1.0,
            "metadata": metadata,
            "idempotency_key": generate_idempotency_key(
                tenant_id, source_id, METRIC_POINT, ts_iso
            ),
        }
        data_points.append(dp_point)

        # 2. Latitude Metric DataPoint
        dp_lat = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": METRIC_LATITUDE,
            "timestamp": ts_iso,
            "value": lat,
            "metadata": metadata,
            "idempotency_key": generate_idempotency_key(
                tenant_id, source_id, METRIC_LATITUDE, ts_iso
            ),
        }
        data_points.append(dp_lat)

        # 3. Longitude Metric DataPoint
        dp_lon = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": METRIC_LONGITUDE,
            "timestamp": ts_iso,
            "value": lon,
            "metadata": metadata,
            "idempotency_key": generate_idempotency_key(
                tenant_id, source_id, METRIC_LONGITUDE, ts_iso
            ),
        }
        data_points.append(dp_lon)

    return data_points
