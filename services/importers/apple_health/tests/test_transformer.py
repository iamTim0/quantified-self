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
        f"{tenant_id}:{source_id}:{metric_type}:{timestamp}".encode("utf-8")
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
    assert step_event["metric_type"] == "step_count"
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
    # 1 main sleep_duration + 4 stages (deep, rem, core, awake) = 5 events
    assert len(events) == 5

    metric_types = [e["metric_type"] for e in events]
    assert "sleep_duration" in metric_types
    assert "sleep_deep_duration" in metric_types
    assert "sleep_rem_duration" in metric_types
    assert "sleep_core_duration" in metric_types
    assert "sleep_awake_duration" in metric_types


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

    w_types = [e["metric_type"] for e in events]
    assert "workout_active_energy" in w_types
    assert "workout_distance" in w_types
    assert "workout_duration" in w_types
    assert "workout_avg_heart_rate" in w_types


def test_transform_invalid_payload():
    """Verifies graceful handling of empty or malformed JSON payloads."""
    events = transform_health_auto_export_json({}, "tenant_1", "src_1")
    assert events == []

    events_bad = transform_health_auto_export_json({"data": "invalid"}, "tenant_1", "src_1")
    assert events_bad == []
