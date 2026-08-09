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


# ─── Shapes that were being discarded ────────────────────────
#
# Each of these covers a quantity Health Auto Export sends and this importer threw
# away without a word. They were found by reading the provider's documentation
# against the transformer by hand; the field report exists so the next one is not.

TENANT = "00000000-0000-0000-0000-000000000001"
SOURCE = "11111111-1111-1111-1111-111111111111"


def _metrics(payload: dict) -> dict[str, float]:
    points = transform_health_auto_export_json(payload, tenant_id=TENANT, source_id=SOURCE)
    return {p["metric_type"]: p["value"] for p in points}


def test_heart_rate_entries_are_read():
    """Entries carry Min/Avg/Max — capitalised — and never a `qty`.

    The reader looked for `qty`, then lowercase `avg`, then `value`, so every
    single heart-rate reading was skipped.
    """
    values = _metrics(
        {
            "data": {
                "metrics": [
                    {
                        "name": "heart_rate",
                        "units": "bpm",
                        "data": [{"date": "2026-08-05 10:00:00 +0000", "Min": 52, "Avg": 61.5, "Max": 128}],
                    }
                ]
            }
        }
    )
    assert values["heart_rate"] == 61.5


def test_heart_rate_min_and_max_are_kept_as_context():
    """The registry has no daily min/max, so they travel alongside rather than vanish."""
    points = transform_health_auto_export_json(
        {
            "data": {
                "metrics": [
                    {
                        "name": "heart_rate",
                        "units": "bpm",
                        "data": [{"date": "2026-08-05 10:00:00 +0000", "Min": 52, "Avg": 61.5, "Max": 128}],
                    }
                ]
            }
        },
        tenant_id=TENANT,
        source_id=SOURCE,
    )
    assert points[0]["metadata"]["Min"] == 52
    assert points[0]["metadata"]["Max"] == 128


def test_blood_pressure_becomes_two_metrics():
    """It arrives as systolic/diastolic and was dropped entirely."""
    values = _metrics(
        {
            "data": {
                "metrics": [
                    {
                        "name": "blood_pressure",
                        "units": "mmHg",
                        "data": [
                            {"date": "2026-08-05 10:00:00 +0000", "systolic": 118, "diastolic": 76}
                        ],
                    }
                ]
            }
        }
    )
    assert values["blood_pressure_systolic"] == 118
    assert values["blood_pressure_diastolic"] == 76


def test_workout_energy_and_distance_use_the_current_field_names():
    """v2 renamed them, and only the v1 names were read.

    Worse than a rename: in v2 `activeEnergy` is a time-series *array*, so the old
    lookup found something and extracted nothing from it.
    """
    values = _metrics(
        {
            "data": {
                "workouts": [
                    {
                        "id": "w1",
                        "name": "Run",
                        "start": "2026-08-05 07:00:00 +0000",
                        "activeEnergy": [{"date": "2026-08-05 07:01:00 +0000", "qty": 12}],
                        "activeEnergyBurned": {"qty": 410, "units": "kcal"},
                        "distance": {"qty": 8.2, "units": "km"},
                        "duration": 2400,
                    }
                ]
            }
        }
    )
    assert values["workout_energy"] == 410
    assert values["workout_distance"] == 8.2
    # Seconds, declared nowhere; read as minutes it would have been 2400 minutes.
    assert values["workout_duration"] == 40


def test_a_workout_route_becomes_location_points():
    """GPS was never read at all, so a recorded run had no trace."""
    points = transform_health_auto_export_json(
        {
            "data": {
                "workouts": [
                    {
                        "id": "w1",
                        "name": "Run",
                        "start": "2026-08-05 07:00:00 +0000",
                        "route": [
                            {
                                "latitude": 52.52,
                                "longitude": 13.41,
                                "altitude": 34.0,
                                "timestamp": "2026-08-05 07:00:05 +0000",
                            },
                            {
                                "lat": 52.53,
                                "lon": 13.42,
                                "timestamp": "2026-08-05 07:00:15 +0000",
                            },
                        ],
                    }
                ]
            }
        },
        tenant_id=TENANT,
        source_id=SOURCE,
    )
    route = [p for p in points if p["metric_type"] == "location_point"]

    # Both the current and the older coordinate spelling are read.
    assert len(route) == 2
    assert route[0]["metadata"]["latitude"] == 52.52
    assert route[0]["metadata"]["altitude"] == 34.0
    assert route[1]["metadata"]["longitude"] == 13.42
    # A trace, not one point per workout: distinct timestamps, distinct keys.
    assert route[0]["idempotency_key"] != route[1]["idempotency_key"]


def test_the_field_report_names_what_was_not_stored():
    """The systematic version of how the defects above were found."""
    from shared_schemas import FieldReportCollector

    report = FieldReportCollector()
    transform_health_auto_export_json(
        {
            "data": {
                "workouts": [
                    {
                        "id": "w1",
                        "name": "Swim",
                        "start": "2026-08-05 07:00:00 +0000",
                        "duration": 1800,
                        "swolfScore": 34,
                    }
                ],
                "ecg": [{"classification": "Sinus Rhythm"}],
            }
        },
        tenant_id=TENANT,
        source_id=SOURCE,
        report=report,
    )
    built = report.build()

    unmapped = {sighting.path for sighting in built.unmapped}
    assert "workouts.swolfScore" in unmapped
    assert "data.ecg[]" in unmapped
    assert {s.path for s in built.mapped} == {"workouts.duration"}

    # No value ever appears in a report — only a path and the kind of thing there.
    for sighting in (*built.mapped, *built.unmapped):
        assert sighting.kind in {"number", "string", "bool", "array", "object", "null"}
        assert not hasattr(sighting, "value")
