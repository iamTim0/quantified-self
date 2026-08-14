"""Unit tests for Streak 2.0 gym log transformer.

Maps to System Invariants:
- Rule 4: Idempotency SHA256 hash formatting
- Rule 2: Tenant isolation and event structure
"""

import hashlib

from streak_importer.transformer import (
    generate_idempotency_key,
    transform_streak_export_json,
)


def test_generate_idempotency_key():
    """Verifies Rule 4: SHA256 deterministic idempotency key format."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    source_id = "streak_src"
    metric_type = "strength_set_weight_1001"
    timestamp = "2026-08-03T18:05:00+00:00"

    expected = hashlib.sha256(
        f"{tenant_id}:{source_id}:{metric_type}:{timestamp}".encode()
    ).hexdigest()

    key = generate_idempotency_key(tenant_id, source_id, metric_type, timestamp)
    assert key == expected
    assert len(key) == 64


def test_transform_streak_export_workouts():
    """Verifies transformation of Streak 2.0 workouts, sets, and volume metrics."""
    tenant_id = "00000000-0000-0000-0000-000000000001"
    source_id = "streak_src"

    payload = {
        "schemaVersion": 1,
        "source": "streak",
        "exportedAt": "2026-08-03T23:00:00Z",
        "workouts": [
            {
                "id": 101,
                "title": "Push Day",
                "category": "Chest",
                "finished": True,
                "createdAt": "2026-08-03T18:00:00Z",
                "sets": [
                    {
                        "id": 1001,
                        "setNumber": 1,
                        "weight": 80.0,
                        "reps": 10,
                        "maxPulse": 145,
                        "createdAt": "2026-08-03T18:05:00Z",
                        "exercise": {
                            "id": 10,
                            "title": "Bench Press",
                            "category": "Chest",
                        },
                    }
                ],
            }
        ],
    }

    events = transform_streak_export_json(payload, tenant_id, source_id)
    # 1 set -> weight, reps, set_volume, maxPulse + 2 summary metrics (total_volume, total_sets) = 6 events
    assert len(events) == 6

    m_types = [e["metric_type"] for e in events]
    assert "strength_set_weight" in m_types
    assert "strength_set_reps" in m_types
    assert "strength_set_volume" in m_types
    assert "strength_set_heart_rate_max" in m_types
    assert "strength_session_volume" in m_types
    assert "strength_session_sets" in m_types

    # Check set volume calculation (80 * 10 = 800)
    vol_event = next(e for e in events if e["metric_type"] == "strength_set_volume")
    assert vol_event["value"] == 800.0
    assert vol_event["metadata"]["exercise_title"] == "Bench Press"
    assert vol_event["idempotency_key"] == generate_idempotency_key(
        tenant_id,
        f"{source_id}_1001",
        "strength_set_volume",
        vol_event["timestamp"],
    )


def test_transform_empty_payload():
    """Verifies graceful handling of empty or malformed Streak payload."""
    assert transform_streak_export_json({}, "tenant_1", "src_1") == []
    assert transform_streak_export_json({"workouts": "bad"}, "tenant_1", "src_1") == []


def test_a_set_without_a_usable_timestamp_is_skipped():
    """It used to be stamped `now()`, which re-keyed the set on every poll.

    The timestamp is hashed into the `idempotency_key`, so a substituted *now* made the
    same set look new each sync — `ON CONFLICT DO NOTHING` had nothing to conflict with,
    and inserted another row.

    Verifies Fizzbee Invariant: NoDuplicateRecords
    """
    from streak_importer.transformer import parse_timestamp

    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("whenever") is None
    assert parse_timestamp("2026-08-03T14:00:00Z") == "2026-08-03T14:00:00+00:00"

    payload = {
        "workouts": [
            {
                "id": "w1",
                "title": "Push",
                "createdAt": "2026-08-03T14:00:00Z",
                "sets": [{"id": "s1", "setNumber": 1, "weight": 60, "reps": 8}],
            },
            {
                "id": "w2",
                "title": "Pull",
                "createdAt": "whenever",
                "sets": [{"id": "s2", "setNumber": 1, "weight": 70, "reps": 6}],
            },
        ]
    }
    result = transform_streak_export_json(payload, "tenant-1", "src-1")

    assert result, "the workout with a valid timestamp must still be imported"
    assert all(dp["metadata"].get("workout_id") != "w2" for dp in result)
    keys = [dp["idempotency_key"] for dp in result]
    assert len(keys) == len(set(keys))
