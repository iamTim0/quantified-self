"""Unit tests for Health Auto Export JSON transformer.

Maps to System Invariants:
- Rule 4: Idempotency SHA256 hash formatting
- Rule 2: Tenant isolation and event structure
"""

import hashlib

from apple_health_importer.transformer import (
    generate_idempotency_key,
    transform_health_auto_export_json,
)


def test_generate_idempotency_key():
    """Verifies Rule 4: SHA256 deterministic idempotency key format."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    source_id = "apple_health_src"
    metric_type = "step_count"
    timestamp = "2026-08-03T12:00:00+00:00"

    expected = hashlib.sha256(
        f"{tenant_id}:{source_id}:{metric_type}:{timestamp}".encode()
    ).hexdigest()

    key = generate_idempotency_key(tenant_id, source_id, metric_type, timestamp)
    assert key == expected
    assert len(key) == 64


def test_transform_health_auto_export_metrics():
    """Verifies parsing of standard Health Auto Export metric items."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    source_id = "apple_health_src"

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {
                            "qty": 1250,
                            "date": "2026-08-03 14:00:00 +0000",
                            "source": "Apple Watch",
                        }
                    ],
                },
                {
                    "name": "heart_rate",
                    "units": "bpm",
                    "data": [
                        {
                            "avg": 75.5,
                            "date": "2026-08-03T14:30:00Z",
                        }
                    ],
                },
            ]
        }
    }

    events = transform_health_auto_export_json(payload, tenant_id, source_id)
    assert len(events) == 2

    step_event = events[0]
    assert step_event["tenant_id"] == tenant_id
    assert step_event["source_id"] == source_id
    assert step_event["metric_type"] == "steps"
    assert step_event["value"] == 1250.0
    assert step_event["metadata"]["device_source"] == "Apple Watch"
    assert "idempotency_key" in step_event

    hr_event = events[1]
    assert hr_event["metric_type"] == "heart_rate"
    assert hr_event["value"] == 75.5


def test_transform_health_auto_export_sleep():
    """Verifies sleep analysis parsing including sleep stage sub-metrics."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    source_id = "apple_health_src"

    payload = {
        "metrics": [
            {
                "name": "sleep_analysis",
                "units": "hr",
                "data": [
                    {
                        "qty": 8.0,
                        "date": "2026-08-03 07:00:00 +0000",
                        "deep": 1.5,
                        "rem": 2.0,
                        "core": 4.0,
                        "awake": 0.5,
                    }
                ],
            }
        ]
    }

    events = transform_health_auto_export_json(payload, tenant_id, source_id)
    # 1 main sleep_duration + 4 stages (deep, rem, core/light, awake) = 5 events
    assert len(events) == 5

    by_metric = {e["metric_type"]: e for e in events}
    assert set(by_metric) == {
        "sleep_duration",
        "sleep_duration_deep",
        "sleep_duration_rem",
        "sleep_duration_light",
        "sleep_duration_awake",
    }

    # The payload declares `units: "hr"` and the registry defines sleep in minutes, so
    # the hours are converted rather than stored as if they were minutes. This is the
    # bug the registry was built to stop: one phone exporting hours and another minutes
    # into a single series, with nothing recording which was which.
    assert by_metric["sleep_duration"]["value"] == 480.0
    assert by_metric["sleep_duration_deep"]["value"] == 90.0
    assert by_metric["sleep_duration_light"]["value"] == 240.0
    # The reading as the phone sent it survives alongside the converted one.
    assert by_metric["sleep_duration"]["metadata"]["provider_value"] == 8.0
    assert by_metric["sleep_duration"]["metadata"]["units"] == "hr"


def test_transform_health_auto_export_workouts():
    """Verifies workout parsing from Health Auto Export JSON."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    source_id = "apple_health_src"

    payload = {
        "data": {
            "workouts": [
                {
                    "name": "Running",
                    "start": "2026-08-03 08:00:00 +0000",
                    "end": "2026-08-03 08:45:00 +0000",
                    "duration": 2700,
                    "activeEnergy": {"qty": 450.0, "units": "kcal"},
                    "totalDistance": {"qty": 5.5, "units": "km"},
                    "avgHeartRate": 150.0,
                }
            ]
        }
    }

    events = transform_health_auto_export_json(payload, tenant_id, source_id)
    # activeEnergy, totalDistance, duration, avgHeartRate -> 4 workout events
    assert len(events) == 4

    by_metric = {e["metric_type"]: e for e in events}
    assert set(by_metric) == {
        "workout_energy",
        "workout_distance",
        "workout_duration",
        "workout_heart_rate_average",
    }

    # `duration` arrives as a bare 2700 with no declared unit. Health Auto Export means
    # seconds, and the workout does run 08:00-08:45, so it must become 45 minutes and
    # not 2700 of them.
    assert by_metric["workout_duration"]["value"] == 45.0
    # Already in the registry's units, so untouched.
    assert by_metric["workout_energy"]["value"] == 450.0
    assert by_metric["workout_distance"]["value"] == 5.5


def test_transform_invalid_payload():
    """Verifies graceful handling of empty or malformed JSON payloads."""
    events = transform_health_auto_export_json({}, "tenant_1", "src_1")
    assert events == []

    events_bad = transform_health_auto_export_json({"data": "invalid"}, "tenant_1", "src_1")
    assert events_bad == []


def test_a_reading_without_a_usable_timestamp_is_skipped():
    """It used to be stamped `now()`, which re-keyed the reading on every poll.

    The timestamp is hashed into the `idempotency_key`, so a substituted *now* made the
    same reading look new each sync — `ON CONFLICT DO NOTHING` had nothing to conflict
    with, and inserted another row. Returning the raw unparsed string did the same
    whenever the provider varied its formatting.

    Verifies Fizzbee Invariant: NoDuplicateRecords
    """
    from apple_health_importer.transformer import parse_timestamp

    assert parse_timestamp("") is None
    assert parse_timestamp("not a timestamp") is None
    assert parse_timestamp("2026-08-03T14:00:00Z") == "2026-08-03T14:00:00+00:00"

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {"date": "2026-08-03 14:00:00 +0000", "qty": 1000},
                        {"date": "whenever", "qty": 2000},
                    ],
                }
            ]
        }
    }
    result = transform_health_auto_export_json(payload, "tenant-1", "src-1")

    assert [dp["value"] for dp in result] == [1000]
    keys = [dp["idempotency_key"] for dp in result]
    assert len(keys) == len(set(keys))
