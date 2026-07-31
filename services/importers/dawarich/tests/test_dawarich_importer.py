"""Unit tests for Dawarich Importer transformer and client.

Verifies Fizzbee Invariants:
- ExactOnceIngestion: Deterministic SHA256 idempotency_key for location points.
- DataPointNormalization: Normalization of latitude, longitude, and timestamps.
"""

import pytest
from dawarich_importer.transformer import (
    generate_idempotency_key,
    transform_dawarich_points,
    _normalize_iso_timestamp,
)


def test_idempotency_key_deterministic():
    """Verifies Fizzbee Invariant: ExactOnceIngestion (Deterministic Key)."""
    key1 = generate_idempotency_key("tenant_1", "src_dawarich", "location_latitude", "2026-07-31T12:00:00Z")
    key2 = generate_idempotency_key("tenant_1", "src_dawarich", "location_latitude", "2026-07-31T12:00:00Z")
    assert key1 == key2
    assert len(key1) == 64


def test_timestamp_normalization():
    """Verifies ISO timestamp conversion for epoch and ISO strings."""
    assert _normalize_iso_timestamp(1722432000) == "2024-07-31T13:20:00Z"
    assert _normalize_iso_timestamp("2026-07-31T12:00:00Z") == "2026-07-31T12:00:00Z"


def test_transform_dawarich_points():
    """Verifies transformation of raw Dawarich GPS points into DataPoints."""
    raw_points = [
        {
            "id": 101,
            "latitude": 52.520008,
            "longitude": 13.404954,
            "altitude": 34.5,
            "speed": 2.1,
            "timestamp": 1722432000,
        }
    ]

    dps = transform_dawarich_points(raw_points, tenant_id="t_test", source_id="src_dawarich")

    # Should generate 3 data points per location: location_point, location_latitude, location_longitude
    assert len(dps) == 3

    types = [dp["metric_type"] for dp in dps]
    assert "location_point" in types
    assert "location_latitude" in types
    assert "location_longitude" in types

    lat_dp = next(dp for dp in dps if dp["metric_type"] == "location_latitude")
    assert lat_dp["value"] == 52.520008
    assert lat_dp["tenant_id"] == "t_test"
    assert lat_dp["source_id"] == "src_dawarich"
    assert len(lat_dp["idempotency_key"]) == 64
