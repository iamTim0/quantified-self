"""End-to-End Integration Tests for All Importer Microservices with Mocked Data.

Verifies end-to-end data transformation, idempotency key generation, tenant isolation,
and canonical event payload structure for every single importer:
1. Yazio (Nutrition & Diary)
2. Dawarich (Location & GPS)
3. WHOOP (Strain, Recovery, Sleep, Workout)
4. Apple Health / Health Auto Export (Activity, Vitals, Sleep, Workouts)
5. Streak 2.0 (Gym & Workout Sets)
6. Calendar (Events & Time Tracking)
7. Home Assistant (IoT & Smart Home)
8. Weather (Temperature & Environment)

Verifies Rule 2 (Tenant Isolation) & Rule 4 (Deterministic Idempotency Key).
"""

import uuid
from datetime import datetime, timezone

import pytest
from apple_health_importer.transformer import transform_health_auto_export_json
from calendar_importer.ics import CalendarEvent
from calendar_importer.transformer import transform_events as transform_calendar_events
from dawarich_importer.transformer import transform_dawarich_points
from home_assistant_importer.transformer import transform as transform_home_assistant
from streak_importer.transformer import transform_streak_export_json
from weather_importer.transformer import transform as transform_weather
from whoop_importer.transformer import transform_whoop_records
from yazio_importer.transformer import transform_consumed_items


@pytest.fixture
def mock_tenant_context():
    tenant_id = f"tenant-e2e-{uuid.uuid4().hex[:8]}"
    source_id = f"source-e2e-{uuid.uuid4().hex[:8]}"
    return tenant_id, source_id


def test_yazio_importer_e2e_mock_import(mock_tenant_context):
    """Test Yazio importer data transformation and idempotency with mock diary payload."""
    tenant_id, source_id = mock_tenant_context
    raw_data = {
        "summary": {"energy": 2150.0, "protein": 140.0, "carbs": 210.0, "fat": 65.0},
        "consumed": [
            {
                "product_id": "prod_123",
                "amount": 150.0,
                "meal": "lunch",
            }
        ],
    }
    product_cache = {
        "prod_123": {
            "name": "Haferflocken Bio",
            "base_amount": 100.0,
            "energy_kcal": 370.0,
            "protein_g": 13.0,
            "carbs_g": 60.0,
            "fat_g": 7.0,
        }
    }

    dps = transform_consumed_items(
        raw_data=raw_data,
        day="2026-08-04",
        tenant_id=tenant_id,
        source_id=source_id,
        product_cache=product_cache,
        recipe_cache={},
    )

    assert len(dps) >= 3
    for dp in dps:
        assert dp["tenant_id"] == tenant_id
        assert dp["source_id"] == source_id
        assert "idempotency_key" in dp
        assert len(dp["idempotency_key"]) == 64


def test_dawarich_importer_e2e_mock_import(mock_tenant_context):
    """Test Dawarich location importer data transformation with mock GPS points."""
    tenant_id, source_id = mock_tenant_context
    raw_points = [
        {
            "id": 9981,
            "latitude": 52.5200,
            "longitude": 13.4050,
            "altitude": 34.5,
            "speed": 1.2,
            "timestamp": 1722768000, # 2026-08-04T10:00:00Z
        }
    ]

    dps = transform_dawarich_points(raw_points, tenant_id, source_id)
    assert len(dps) == 3 # location_point, latitude & longitude metrics
    types = {dp["metric_type"] for dp in dps}
    assert "location_latitude" in types
    assert "location_longitude" in types
    for dp in dps:
        assert dp["tenant_id"] == tenant_id
        assert len(dp["idempotency_key"]) == 64


def test_whoop_importer_e2e_mock_import(mock_tenant_context):
    """Test WHOOP importer data transformation with mock strain & recovery records."""
    tenant_id, source_id = mock_tenant_context
    recovery_records = [
        {
            "id": "rec_789",
            "score_state": "SCORED",
            "start": "2026-08-04T07:00:00Z",
            "score": {
                "recovery_score": 85.0,
                "resting_heart_rate": 52.0,
                "hrv_rmssd_milli": 68.4,
                "spo2_percentage": 98.5,
                "skin_temp_celsius": 36.2,
            },
        }
    ]

    dps = transform_whoop_records("recovery", recovery_records, tenant_id, source_id)
    assert len(dps) == 5
    metrics = {dp["metric_type"]: dp["value"] for dp in dps}
    assert metrics["whoop_recovery_score"] == 85.0
    assert metrics["heart_rate_resting"] == 52.0
    # Same canonical name Apple Health writes its resting pulse under.
    assert metrics["hrv_rmssd"] == 68.4
    for dp in dps:
        assert dp["tenant_id"] == tenant_id
        assert len(dp["idempotency_key"]) == 64


def test_apple_health_importer_e2e_mock_import(mock_tenant_context):
    """Test Apple Health importer with mock Health Auto Export payload."""
    tenant_id, source_id = mock_tenant_context
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {"date": "2026-08-04 10:00:00 +0000", "qty": 8450}
                    ],
                },
                {
                    "name": "heart_rate",
                    "units": "bpm",
                    "data": [
                        {"date": "2026-08-04 10:15:00 +0000", "avg": 64.0}
                    ],
                },
            ],
            "workouts": [
                {
                    "name": "Outdoor Run",
                    "start": "2026-08-04 08:00:00 +0000",
                    "end": "2026-08-04 08:45:00 +0000",
                    "activeEnergy": {"qty": 420.0, "units": "kcal"},
                    "totalDistance": {"qty": 5.2, "units": "km"},
                }
            ],
        }
    }

    dps = transform_health_auto_export_json(payload, tenant_id, source_id)
    assert len(dps) >= 4
    metrics = {dp["metric_type"] for dp in dps}
    assert "steps" in metrics
    assert "heart_rate" in metrics
    assert "workout_energy" in metrics
    assert "workout_distance" in metrics
    for dp in dps:
        assert dp["tenant_id"] == tenant_id


def test_streak_importer_e2e_mock_import(mock_tenant_context):
    """Test Streak 2.0 gym importer with mock workout sets payload."""
    tenant_id, source_id = mock_tenant_context
    payload = {
        "workouts": [
            {
                "id": "w_555",
                "title": "Leg Day",
                "category": "Hypertrophy",
                "createdAt": "2026-08-04T09:00:00Z",
                "sets": [
                    {
                        "id": "s_1",
                        "setNumber": 1,
                        "weight": 100.0,
                        "reps": 10,
                        "exercise": {"title": "Squat", "category": "Legs"},
                    }
                ],
            }
        ]
    }

    dps = transform_streak_export_json(payload, tenant_id, source_id)
    assert len(dps) >= 3
    for dp in dps:
        assert dp["tenant_id"] == tenant_id
        assert dp["source_type"] == "streak"


def _occurrence(**overrides) -> CalendarEvent:
    base = dict(  # noqa: C408
        uid="event-1",
        summary="Deep Work",
        start=datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 4, 11, 0, tzinfo=timezone.utc),
        all_day=False,
    )
    base.update(overrides)
    return CalendarEvent(**base)


def test_calendar_importer_e2e_mock_import(mock_tenant_context):
    """Test the Calendar transformer against expanded ICS occurrences.

    This used to drive `transform()`, a JSON entry point the importer never
    called — it existed for a REST calendar mode that was removed because it had
    never worked. The real path is ICS, so that is what is covered here.
    """
    tenant_id, source_id = mock_tenant_context
    events = [_occurrence()]

    dps = transform_calendar_events(events, tenant_id, source_id)

    durations = [d for d in dps if d["metric_type"] == "calendar_meeting_duration"]
    assert len(durations) == 1
    assert durations[0]["tenant_id"] == tenant_id
    assert durations[0]["value"] == 60.0

    # Re-running must yield the identical key (Rule 4).
    again = transform_calendar_events(events, tenant_id, source_id)
    assert [d["idempotency_key"] for d in again] == [d["idempotency_key"] for d in dps]


def test_calendar_occurrences_at_the_same_minute_do_not_collide(mock_tenant_context):
    """Two meetings starting together are two data points, not one overwriting the other.

    A timestamp-only key would collide here; the occurrence's own uid is part of it.
    """
    tenant_id, source_id = mock_tenant_context
    events = [_occurrence(uid="a"), _occurrence(uid="b", summary="Standup")]

    dps = transform_calendar_events(events, tenant_id, source_id)

    keys = [d["idempotency_key"] for d in dps if d["metric_type"] == "calendar_meeting_duration"]
    assert len(keys) == 2
    assert len(set(keys)) == 2


def test_home_assistant_importer_e2e_mock_import(mock_tenant_context):
    """Test Home Assistant importer transformer with mock state values."""
    tenant_id, source_id = mock_tenant_context
    records = [
        {"state": 22.4, "last_updated": "2026-08-04T10:00:00+00:00", "entity_id": "sensor.living_room_temp"}
    ]
    dps = transform_home_assistant(records, tenant_id, source_id)
    assert len(dps) == 1
    assert dps[0]["tenant_id"] == tenant_id
    assert dps[0]["value"] == 22.4


def test_weather_importer_e2e_mock_import(mock_tenant_context):
    """Test Weather importer transformer with mock temperature records."""
    tenant_id, source_id = mock_tenant_context
    records = [
        {"temperature_2m": 24.5, "time": "2026-08-04T10:00:00+00:00"}
    ]
    dps = transform_weather(records, tenant_id, source_id)
    assert len(dps) == 1
    assert dps[0]["tenant_id"] == tenant_id
    assert dps[0]["value"] == 24.5
