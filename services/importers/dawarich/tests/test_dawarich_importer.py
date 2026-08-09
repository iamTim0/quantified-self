"""Unit tests for Dawarich Importer Transformer & Client."""

from dawarich_importer.transformer import (
    _normalize_iso_timestamp,
    generate_idempotency_key,
    transform_dawarich_points,
)


def test_generate_idempotency_key():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic."""
    key1 = generate_idempotency_key("tenant-1", "src-1", "location_point", "2026-08-01T12:00:00Z")
    key2 = generate_idempotency_key("tenant-1", "src-1", "location_point", "2026-08-01T12:00:00Z")
    key3 = generate_idempotency_key("tenant-2", "src-1", "location_point", "2026-08-01T12:00:00Z")

    assert key1 == key2
    assert len(key1) == 64
    assert key1 != key3

def test_normalize_iso_timestamp():
    """Verifies timestamp normalization for string and numeric epoch inputs."""
    iso_str = _normalize_iso_timestamp("2026-08-01T12:00:00Z")
    assert iso_str == "2026-08-01T12:00:00Z"

    epoch_ts = _normalize_iso_timestamp(1785500000)
    assert "Z" in epoch_ts

def test_transform_dawarich_points():
    """Verifies Dawarich location points transformation into DataPoints."""
    raw_points = [
        {
            "id": 101,
            "latitude": 52.5200,
            "longitude": 13.4050,
            "altitude": 35.5,
            "speed": 1.2,
            "timestamp": "2026-08-01T12:00:00Z",
        }
    ]

    dps = transform_dawarich_points(raw_points, "tenant-123", "dawarich_src")
    assert len(dps) == 3  # location_point, location_latitude, location_longitude

    point_dp = next(dp for dp in dps if dp["metric_type"] == "location_point")
    assert point_dp["tenant_id"] == "tenant-123"
    assert point_dp["value"] == 1.0
    assert point_dp["metadata"]["latitude"] == 52.5200
    assert point_dp["metadata"]["longitude"] == 13.4050
    assert point_dp["metadata"]["altitude"] == 35.5
    assert len(point_dp["idempotency_key"]) == 64


def test_a_point_without_a_usable_timestamp_is_skipped():
    """It used to be stamped `now()`, which re-keyed it on every poll.

    The timestamp is hashed into the `idempotency_key`, so a substituted *now* made the
    same point new each sync: `ON CONFLICT DO NOTHING` had nothing to conflict with and
    inserted another row. For a GPS trace that turns a route into a smear.

    Verifies Fizzbee Invariant: NoDuplicateRecords
    """
    assert _normalize_iso_timestamp(None) is None
    assert _normalize_iso_timestamp("") is None
    assert _normalize_iso_timestamp("not a timestamp") is None

    points = [
        {"latitude": 52.5, "longitude": 13.4, "timestamp": "2026-08-01T12:00:00Z"},
        {"latitude": 52.6, "longitude": 13.5, "timestamp": "whenever"},
        {"latitude": 52.7, "longitude": 13.6},
    ]
    result = transform_dawarich_points(points, "tenant-1", "src-1")

    # Only the first point survives, and every emitted key is distinct.
    assert {dp["timestamp"] for dp in result} == {"2026-08-01T12:00:00Z"}
    keys = [dp["idempotency_key"] for dp in result]
    assert len(keys) == len(set(keys))
