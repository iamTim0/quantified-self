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


def _payload(**workout_overrides):
    workout = {
        "id": 501,
        "title": "Leg Day",
        "category": "Legs",
        "createdAt": "2026-08-15T17:00:00Z",
        "sets": [
            {
                "id": 9001,
                "setNumber": 1,
                "weight": 100.0,
                "reps": 5,
                "createdAt": "2026-08-15T17:05:00Z",
                "exercise": {"title": "Back Squat", "category": "Legs"},
            },
            {
                "id": 9002,
                "setNumber": 2,
                "weight": 110.0,
                "reps": 3,
                "createdAt": "2026-08-15T17:12:00Z",
                "exercise": {"title": "Back Squat", "category": "Legs"},
            },
        ],
    }
    workout.update(workout_overrides)
    return {"workouts": [workout]}


TENANT = "00000000-0000-0000-0000-000000000001"
SOURCE = "22222222-2222-2222-2222-222222222222"


def test_sets_and_the_session_summary_share_one_session_id():
    """Verifies Fizzbee Invariant: SessionGroupingIsStable.

    Sets are stamped minutes apart, so before a session id every set was its own
    event and the summary was a third one.
    """
    points = transform_streak_export_json(_payload(), TENANT, SOURCE)

    ids = {p["metadata"]["session_id"] for p in points}
    assert len(ids) == 1, "one workout is one session"
    assert next(iter(ids)).startswith("streak:")

    kinds = {p["metric_type"] for p in points}
    assert "strength_set_weight" in kinds
    assert "strength_session_volume" in kinds


def test_the_session_id_is_stable_across_re_imports():
    first = transform_streak_export_json(_payload(), TENANT, SOURCE)
    second = transform_streak_export_json(_payload(), TENANT, SOURCE)
    assert first[0]["metadata"]["session_id"] == second[0]["metadata"]["session_id"]


def test_the_session_states_no_end_it_cannot_know():
    """Streak sends no end, so none is claimed — the read path derives the span."""
    points = transform_streak_export_json(_payload(), TENANT, SOURCE)
    assert all("session_end" not in p["metadata"] for p in points)
    assert points[0]["metadata"]["session_origin"] == "provider"


def test_the_provider_category_is_mapped_and_also_kept():
    points = transform_streak_export_json(_payload(), TENANT, SOURCE)
    sets = [p for p in points if p["metric_type"] == "strength_set_weight"]
    assert sets[0]["metadata"]["muscle_group"] == "quads"
    assert sets[0]["metadata"]["exercise_category"] == "Legs", "the raw word survives"


def test_a_german_category_maps_to_the_same_group():
    """A localised category list must not split one muscle group into two."""
    german = _payload(category="Beine")
    german["workouts"][0]["sets"][0]["exercise"]["category"] = "Beine"
    points = transform_streak_export_json(german, TENANT, SOURCE)
    sets = [p for p in points if p["metric_type"] == "strength_set_weight"]
    assert sets[0]["metadata"]["muscle_group"] == "quads"


def test_a_bodyweight_session_still_emits_its_summary():
    """Pull-ups have reps and no weight, and used to produce no session at all.

    `total_workout_sets` was incremented inside the weight branch, so a whole
    calisthenics workout reached the summary with a count of zero and emitted
    nothing — the sets were stored, the session they belonged to was not.
    """
    bodyweight = _payload(
        title="Calisthenics",
        sets=[
            {
                "id": 9101,
                "setNumber": 1,
                "reps": 12,
                "createdAt": "2026-08-15T17:05:00Z",
                "exercise": {"title": "Pull-up", "category": "Back"},
            }
        ],
    )
    points = transform_streak_export_json(bodyweight, TENANT, SOURCE)
    kinds = {p["metric_type"] for p in points}

    assert "strength_session_sets" in kinds
    sets_point = next(p for p in points if p["metric_type"] == "strength_session_sets")
    assert sets_point["value"] == 1.0
    # No volume was liftable, so the session's volume is honestly zero.
    volume = next(p for p in points if p["metric_type"] == "strength_session_volume")
    assert volume["value"] == 0.0


def test_unread_provider_fields_are_named_in_the_field_report():
    """Rule 19: a field that arrives and is not stored must still be visible."""
    from shared_schemas.field_report import FieldReportCollector

    payload = _payload()
    payload["workouts"][0]["rpe"] = 8
    payload["workouts"][0]["sets"][0]["restSeconds"] = 90
    payload["workouts"][0]["sets"][0]["exercise"]["equipment"] = "barbell"

    report = FieldReportCollector()
    transform_streak_export_json(payload, TENANT, SOURCE, report=report)
    paths = {sighting.path for sighting in report.build().unmapped}

    assert "workouts[].rpe" in paths
    assert "workouts[].sets[].restSeconds" in paths
    assert "workouts[].sets[].exercise.equipment" in paths


def test_an_unrecognised_muscle_category_is_reported_not_swallowed():
    """`other` must never be the quiet answer to a provider renaming its list."""
    from shared_schemas.field_report import FieldReportCollector

    payload = _payload()
    payload["workouts"][0]["sets"][0]["exercise"]["category"] = "Kettlebell Complex"

    report = FieldReportCollector()
    points = transform_streak_export_json(payload, TENANT, SOURCE, report=report)
    sets = [p for p in points if p["metric_type"] == "strength_set_weight"]

    assert sets[0]["metadata"]["muscle_group"] == "other"
    assert sets[0]["metadata"]["exercise_category"] == "Kettlebell Complex"
    paths = {s.path for s in report.build().unmapped}
    assert "workouts[].sets[].exercise.category" in paths


def test_the_session_block_does_not_change_the_idempotency_key():
    """Verifies Fizzbee Invariant: NoDuplicateData."""
    points = transform_streak_export_json(_payload(), TENANT, SOURCE)
    weight = next(p for p in points if p["metric_type"] == "strength_set_weight")
    assert weight["idempotency_key"] == generate_idempotency_key(
        TENANT, f"{SOURCE}_9001", "strength_set_weight", "2026-08-15T17:05:00+00:00"
    )


def test_the_field_report_names_what_streak_keeps_too():
    """A report listing only what is dropped is half a report."""
    from shared_schemas.field_report import FieldReportCollector

    report = FieldReportCollector()
    transform_streak_export_json(_payload(), TENANT, SOURCE, report=report)
    mapped = {sighting.path: sighting.metric_type for sighting in report.build().mapped}

    assert mapped.get("workouts[].sets[].weight") == "strength_set_weight"
    assert mapped.get("workouts[].sets[].reps") == "strength_set_reps"
