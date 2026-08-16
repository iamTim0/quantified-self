"""The workout list and the workout detail.

Verifies:
- GET /api/v1/data/workouts
- GET /api/v1/data/workouts/{session_key}

Maps to Fizzbee Invariants (specs/workout_sessions.fizz):
- SessionGroupingIsStable
- SessionGroupsAreDisjoint
- SessionDetailIsTenantScoped
- BoundedSessionRead
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataPoint, DataSource
from core.db.session import async_session_maker
from core.main import app
from core.sessions import SessionRef, decode_session_key, encode_session_key
from core.workouts import MAX_SESSION_HOURS
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

START = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1, hours=6)
SESSION = "apple_health:0123456789abcdef"


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _source(tenant_id: str, source_type: str = "apple_health") -> str:
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                display_name=source_type,
            )
        )
        await session.commit()
    return source_id


async def _points(rows: list[dict]) -> None:
    async with async_session_maker() as session:
        for row in rows:
            session.add(
                DataPoint(
                    id=str(uuid.uuid4()),
                    tenant_id=row["tenant_id"],
                    source_id=row["source_id"],
                    metric_type=row["metric_type"],
                    timestamp=row["timestamp"],
                    value=row.get("value"),
                    metadata_=row.get("metadata") or {},
                    idempotency_key=f"{row['metric_type']}-{uuid.uuid4().hex}",
                )
            )
        await session.commit()


def _session_meta(session_id: str = SESSION, **extra) -> dict:
    return {
        "source_type": "apple_health",
        "session_id": session_id,
        "session_start": START.isoformat(),
        "session_origin": "provider",
        "workout_name": "Morning Run",
        **extra,
    }


async def _a_workout(tenant_id: str, source_id: str) -> None:
    meta = _session_meta(session_end=(START + timedelta(minutes=45)).isoformat())
    await _points(
        [
            {"tenant_id": tenant_id, "source_id": source_id,
             "metric_type": "workout_duration", "timestamp": START, "value": 45.0,
             "metadata": meta},
            {"tenant_id": tenant_id, "source_id": source_id,
             "metric_type": "workout_distance", "timestamp": START, "value": 8.2,
             "metadata": meta},
        ]
    )


async def _list(tenant_id: str, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    async with await _client() as client:
        response = await client.get(
            f"/api/v1/data/workouts?{query}" if query else "/api/v1/data/workouts",
            headers=auth_headers(tenant_id),
        )
    assert response.status_code == 200, response.text
    return response.json()


async def _detail(tenant_id: str, key: str, **params) -> tuple[int, dict]:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/v1/data/workouts/{key}"
    async with await _client() as client:
        response = await client.get(
            f"{url}?{query}" if query else url, headers=auth_headers(tenant_id)
        )
    return response.status_code, response.json()


# ── The key ──────────────────────────────────────────────────────────────────


def test_a_session_key_round_trips_in_both_shapes():
    tagged = SessionRef(kind="session_id", start=START, session_id=SESSION)
    decoded = decode_session_key(encode_session_key(tagged))
    assert decoded.kind == "session_id"
    assert decoded.session_id == SESSION
    assert decoded.start == START

    legacy = SessionRef(
        kind="timestamp_title", start=START, source_id="src-1", title="Morning Run"
    )
    decoded = decode_session_key(encode_session_key(legacy))
    assert decoded.kind == "timestamp_title"
    assert decoded.source_id == "src-1"
    assert decoded.title == "Morning Run"
    assert decoded.start == START


def test_a_title_containing_the_separator_survives():
    """A workout can be called anything, including something with a pipe in it."""
    ref = SessionRef(
        kind="timestamp_title", start=START, source_id="src-1", title="Run | easy | 5k"
    )
    assert decode_session_key(encode_session_key(ref)).title == "Run | easy | 5k"


@pytest.mark.parametrize("bad", ["", "not-base64!!", "YWJj", "eyJhIjoxfQ"])
def test_a_malformed_key_is_rejected_rather_than_guessed(bad):
    with pytest.raises(ValueError):
        decode_session_key(bad)


@pytest.mark.asyncio
async def test_a_malformed_key_is_a_400_with_a_stable_code():
    """A client mistake and a missing session deserve different answers."""
    tenant_id = await create_test_tenant()
    try:
        status, body = await _detail(tenant_id, "not-a-key")
        assert status == 400
        assert body["detail"]["code"] == "invalid_session_key"
    finally:
        await cleanup_test_tenant(tenant_id)


# ── Tenant scoping ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_forged_session_key_returns_the_callers_own_empty_result():
    """Verifies Fizzbee Invariant: SessionDetailIsTenantScoped.

    The key is unsigned on purpose. This is the demonstration that forging one is
    uninteresting: every query behind it filters on the tenant the Gateway
    injected, so a key naming somebody else's session resolves to nothing.
    """
    owner = await create_test_tenant()
    intruder = await create_test_tenant()
    try:
        source_id = await _source(owner)
        await _a_workout(owner, source_id)

        listing = await _list(owner, offset_minutes=0)
        key = listing["sessions"][0]["session_key"]

        status, _ = await _detail(intruder, key)
        assert status == 404, "another workspace's session is simply not there"

        status, body = await _detail(owner, key)
        assert status == 200
        assert body["measures"]
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(intruder)


@pytest.mark.asyncio
async def test_the_list_shows_only_the_authenticated_tenants_sessions():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead."""
    owner = await create_test_tenant()
    other = await create_test_tenant()
    try:
        await _a_workout(owner, await _source(owner))

        listing = await _list(other, offset_minutes=0)
        assert listing["sessions"] == []
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(other)


# ── Grouping ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_tagged_workout_is_one_session_however_its_points_are_stamped():
    """Verifies Fizzbee Invariant: SessionGroupingIsStable."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "streak")
        meta = _session_meta("streak:aaaa1111", workout_name="Leg Day")
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "strength_set_weight",
                 "timestamp": START + timedelta(minutes=i * 3), "value": 100.0 + i * 5,
                 "metadata": {**meta, "exercise_title": "Back Squat",
                              "muscle_group": "quads", "set_number": i + 1,
                              "set_id": f"s{i}"}}
                for i in range(3)
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        assert len(listing["sessions"]) == 1
        entry = listing["sessions"][0]
        assert entry["identity"] == "session_id"
        assert entry["title"] == "Leg Day"
        assert entry["exercise_count"] == 1
        assert entry["muscle_groups"] == ["quads"]
        # MAX aggregation: the heaviest set, not the sum of all three.
        assert entry["measures"]["strength_set_weight"] == 110.0
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_tagged_and_untagged_points_never_share_a_session():
    """Verifies Fizzbee Invariant: SessionGroupsAreDisjoint.

    A workout whose rows straddle the change shows as two. What must never happen
    is one row in both, because its measures would then be counted twice and a
    doubled number is indistinguishable from a right one (rule 19).
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "workout_duration", "timestamp": START, "value": 45.0,
                 "metadata": {"workout_name": "Morning Run"}},
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "workout_distance", "timestamp": START, "value": 8.2,
                 "metadata": _session_meta()},
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        assert len(listing["sessions"]) == 2
        identities = {s["identity"] for s in listing["sessions"]}
        assert identities == {"session_id", "timestamp_title"}

        measured = [set(s["measures"]) for s in listing["sessions"]]
        assert measured[0].isdisjoint(measured[1]), "one row, one session"

        # Both are addressable, and each resolves to only its own rows.
        for entry in listing["sessions"]:
            status, body = await _detail(tenant_id, entry["session_key"])
            assert status == 200
            assert len(body["measures"]) == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_legacy_group_reports_identity_timestamp_title():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _points(
            [{"tenant_id": tenant_id, "source_id": source_id,
              "metric_type": "workout_duration", "timestamp": START, "value": 30.0,
              "metadata": {"workout_name": "Old Run"}}]
        )
        listing = await _list(tenant_id, offset_minutes=0)
        assert listing["sessions"][0]["identity"] == "timestamp_title"
        assert listing["sessions"][0]["session_id"] is None
    finally:
        await cleanup_test_tenant(tenant_id)


# ── The detail ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_detail_pulls_every_connector_in_the_window():
    """The point of the whole feature: what else was happening at the time.

    The weather connector knows nothing about the workout. It is included because
    its reading falls inside the session's span, which is what "during my workout"
    means.
    """
    tenant_id = await create_test_tenant()
    try:
        apple = await _source(tenant_id, "apple_health")
        weather = await _source(tenant_id, "weather")
        whoop = await _source(tenant_id, "whoop")

        await _a_workout(tenant_id, apple)
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": weather,
                 "metric_type": "weather_temperature",
                 "timestamp": START + timedelta(minutes=10), "value": 18.4,
                 "metadata": {"source_type": "weather"}},
                {"tenant_id": tenant_id, "source_id": whoop,
                 "metric_type": "hrv_rmssd",
                 "timestamp": START + timedelta(minutes=20), "value": 62.0,
                 "metadata": {"source_type": "whoop"}},
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        status, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])

        assert status == 200
        surrounding = {row["metric_type"] for row in body["surroundings"]}
        assert "weather_temperature" in surrounding
        assert "hrv_rmssd" in surrounding
        assert {row["source_reason"] for row in body["surroundings"]} == {"only_source"}
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_strength_breakdown_groups_by_exercise():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "streak")
        meta = _session_meta("streak:bbbb2222", workout_name="Push Day")
        rows = []
        for index, (exercise, group, weight, reps) in enumerate(
            [("Bench Press", "chest", 80.0, 8), ("Bench Press", "chest", 85.0, 5),
             ("Overhead Press", "shoulders", 45.0, 8)]
        ):
            at = START + timedelta(minutes=index * 4)
            common = {**meta, "exercise_title": exercise, "muscle_group": group,
                      "set_id": f"set-{index}", "set_number": index + 1}
            rows += [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "strength_set_weight", "timestamp": at,
                 "value": weight, "metadata": common},
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "strength_set_reps", "timestamp": at,
                 "value": float(reps), "metadata": common},
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "strength_set_volume", "timestamp": at,
                 "value": weight * reps, "metadata": common},
            ]
        await _points(rows)

        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])

        exercises = {e["exercise_title"]: e for e in body["strength"]["exercises"]}
        assert set(exercises) == {"Bench Press", "Overhead Press"}
        assert len(exercises["Bench Press"]["sets"]) == 2
        assert exercises["Bench Press"]["top_set_weight"] == 85.0
        assert exercises["Bench Press"]["total_reps"] == 13.0
        assert exercises["Bench Press"]["muscle_group"] == "chest"
        assert body["strength"]["total_sets"] == 3
        assert body["strength"]["set_rows_truncated"] is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_route_is_returned_from_the_geometry_column():
    """The one read in the platform that uses PostGIS.

    The trigger fills `location_geom` from the coordinates in metadata, and this
    is where `ST_Simplify` and `ST_Length` finally get used.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _a_workout(tenant_id, source_id)
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "location_point",
                 "timestamp": START + timedelta(seconds=index * 10), "value": 1.0,
                 "metadata": {"latitude": 52.52 + index * 0.001,
                              "longitude": 13.40 + index * 0.001,
                              "altitude": 38.0 + index, **_session_meta()}}
                for index in range(20)
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])

        route = body["route"]
        assert route is not None
        assert route["source"] == "geometry"
        # A measured length beside the provider's stated distance.
        assert route["measured_distance_m"] > 0
        assert route["fix_count"] == 20
        assert route["samples"][0]["altitude"] == 38.0
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_three_hour_workout_returns_a_bounded_payload():
    """Verifies Fizzbee Invariant: BoundedSessionRead.

    The response shape does not grow with the session. Every truncation is
    reported, because a quietly shortened answer is indistinguishable from a short
    workout.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        meta = _session_meta(session_end=(START + timedelta(hours=3)).isoformat())
        await _points(
            [{"tenant_id": tenant_id, "source_id": source_id,
              "metric_type": "workout_duration", "timestamp": START, "value": 180.0,
              "metadata": meta}]
        )
        # 1,800 heart-rate samples and 1,800 fixes over three hours.
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "workout_heart_rate",
                 "timestamp": START + timedelta(seconds=index * 6),
                 "value": 140.0 + (index % 40), "metadata": meta}
                for index in range(1800)
            ]
        )
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "location_point",
                 "timestamp": START + timedelta(seconds=index * 6), "value": 1.0,
                 "metadata": {"latitude": 52.5 + index * 0.0001,
                              "longitude": 13.4 + index * 0.0001, **meta}}
                for index in range(1800)
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(
            tenant_id, listing["sessions"][0]["session_key"],
            stream_points=200, route_points=300,
        )

        stream = next(s for s in body["streams"] if s["metric_type"] == "workout_heart_rate")
        assert stream["point_count"] <= 200
        assert body["route"]["sample_count"] <= 300
        assert body["route"]["truncated"] is True
        assert body["route"]["fix_count"] == 1800, "the true count is still reported"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_decimation_preserves_the_peak():
    """A bucket that hides its maximum is a number that looks measured.

    A single 190 bpm spike inside a bucket averaging 145 must survive as that
    bucket's `max`, or the chart shows a different workout from the one that
    happened.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        meta = _session_meta(session_end=(START + timedelta(minutes=30)).isoformat())
        await _points(
            [{"tenant_id": tenant_id, "source_id": source_id,
              "metric_type": "workout_duration", "timestamp": START, "value": 30.0,
              "metadata": meta}]
        )
        rows = [
            {"tenant_id": tenant_id, "source_id": source_id,
             "metric_type": "workout_heart_rate",
             "timestamp": START + timedelta(seconds=index), "value": 145.0,
             "metadata": meta}
            for index in range(300)
        ]
        rows[150]["value"] = 190.0
        await _points(rows)

        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(
            tenant_id, listing["sessions"][0]["session_key"], stream_points=10
        )

        stream = next(s for s in body["streams"] if s["metric_type"] == "workout_heart_rate")
        assert max(point["max"] for point in stream["points"]) == 190.0
        assert stream["bucket_seconds"] > 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_window_is_clamped_and_says_so():
    """A workout mis-stamped with an end three days later is not a three-day scan."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        meta = _session_meta(session_end=(START + timedelta(days=3)).isoformat())
        await _points(
            [{"tenant_id": tenant_id, "source_id": source_id,
              "metric_type": "workout_duration", "timestamp": START, "value": 45.0,
              "metadata": meta}]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])

        assert body["window"]["clamped"] is True
        span = datetime.fromisoformat(body["window"]["end"]) - datetime.fromisoformat(
            body["window"]["start"]
        )
        assert span == timedelta(hours=MAX_SESSION_HOURS)
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_derived_measure_still_says_it_was_derived():
    """Rule 19 travels all the way to the screen."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "whoop")
        meta = _session_meta("whoop:cccc3333", workout_name="Cycling")
        await _points(
            [{"tenant_id": tenant_id, "source_id": source_id,
              "metric_type": "workout_duration", "timestamp": START, "value": 45.0,
              "metadata": {**meta, "derived_by": "difference",
                           "derived_from": ["start", "end"]}}]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])

        duration = next(m for m in body["measures"] if m["metric_type"] == "workout_duration")
        assert duration["derived_by"] == "difference"
        assert duration["derived_from"] == ["start", "end"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_session_with_no_route_says_so_rather_than_inventing_one():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "streak")
        await _points(
            [{"tenant_id": tenant_id, "source_id": source_id,
              "metric_type": "strength_session_volume", "timestamp": START,
              "value": 4200.0, "metadata": _session_meta("streak:dddd4444")}]
        )
        listing = await _list(tenant_id, offset_minutes=0)
        _, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])
        assert body["route"] is None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_list_can_be_filtered_by_category():
    tenant_id = await create_test_tenant()
    try:
        apple = await _source(tenant_id, "apple_health")
        streak = await _source(tenant_id, "streak")
        await _a_workout(tenant_id, apple)
        await _points(
            [{"tenant_id": tenant_id, "source_id": streak,
              "metric_type": "strength_session_volume", "timestamp": START,
              "value": 4200.0, "metadata": _session_meta("streak:eeee5555")}]
        )

        assert len((await _list(tenant_id, offset_minutes=0))["sessions"]) == 2
        cardio = await _list(tenant_id, offset_minutes=0, category="workout")
        assert [s["category"] for s in cardio["sessions"]] == ["workout"]
        strength = await _list(tenant_id, offset_minutes=0, category="strength")
        assert [s["category"] for s in strength["sessions"]] == ["strength"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_range_beyond_a_year_is_refused():
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            response = await client.get(
                "/api/v1/data/workouts?start_date=2020-01-01&end_date=2026-01-01",
                headers=auth_headers(tenant_id),
            )
        assert response.status_code == 400
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_legacy_key_does_not_pull_in_a_different_session():
    """Two legacy workouts at one instant from one connector are two sessions.

    The list groups them apart — the grouping key includes the title — so the
    detail must resolve them apart too. If it matched on the timestamp alone, both
    keys would return both workouts' measures, and a reader opening either would
    see the other's numbers added to it.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "workout_distance", "timestamp": START, "value": 8.0,
                 "metadata": {"workout_name": "Morning Run"}},
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "workout_duration", "timestamp": START, "value": 30.0,
                 "metadata": {"workout_name": "Evening Swim"}},
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        assert len(listing["sessions"]) == 2, "two names, two sessions"

        by_title = {entry["title"]: entry for entry in listing["sessions"]}
        _, run = await _detail(tenant_id, by_title["Morning Run"]["session_key"])
        _, swim = await _detail(tenant_id, by_title["Evening Swim"]["session_key"])

        assert [m["metric_type"] for m in run["measures"]] == ["workout_distance"]
        assert [m["metric_type"] for m in swim["measures"]] == ["workout_duration"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_legacy_key_separates_a_workout_from_a_strength_session():
    """The third part of the legacy group key: the category.

    A category is a property of the metric name in the registry rather than a
    column, so it cannot go in the SQL predicate. Applied nowhere, a cardio session
    and a strength session sharing an instant and a name were two rows in the list
    and one merged page when opened.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "workout_duration", "timestamp": START, "value": 40.0,
                 "metadata": {"workout_name": "Circuit"}},
                {"tenant_id": tenant_id, "source_id": source_id,
                 "metric_type": "strength_session_volume", "timestamp": START,
                 "value": 2200.0, "metadata": {"workout_name": "Circuit"}},
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        assert len(listing["sessions"]) == 2

        by_category = {entry["category"]: entry for entry in listing["sessions"]}
        _, cardio = await _detail(tenant_id, by_category["workout"]["session_key"])
        _, strength = await _detail(tenant_id, by_category["strength"]["session_key"])

        assert [m["metric_type"] for m in cardio["measures"]] == ["workout_duration"]
        assert [m["metric_type"] for m in strength["measures"]] == ["strength_session_volume"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_two_connectors_reporting_one_metric_pick_a_winner():
    """The branch the other tests never reached.

    Every earlier case has one connector per metric, so `only_source` short-circuits
    before the resolver is called — which is how a wrong call signature survived to
    here. With two connectors reporting `heart_rate_resting` inside the window, the
    detail must name one of them rather than adding them together (rule 19).
    """
    tenant_id = await create_test_tenant()
    try:
        apple = await _source(tenant_id, "apple_health")
        whoop = await _source(tenant_id, "whoop")
        await _a_workout(tenant_id, apple)
        await _points(
            [
                {"tenant_id": tenant_id, "source_id": apple,
                 "metric_type": "heart_rate_resting",
                 "timestamp": START + timedelta(minutes=5), "value": 52.0,
                 "metadata": {"source_type": "apple_health"}},
                {"tenant_id": tenant_id, "source_id": whoop,
                 "metric_type": "heart_rate_resting",
                 "timestamp": START + timedelta(minutes=6), "value": 49.0,
                 "metadata": {"source_type": "whoop"}},
            ]
        )

        listing = await _list(tenant_id, offset_minutes=0)
        status, body = await _detail(tenant_id, listing["sessions"][0]["session_key"])
        assert status == 200, body

        resting = next(
            row for row in body["surroundings"] if row["metric_type"] == "heart_rate_resting"
        )
        # One connector answers; the other is named, never added.
        assert resting["source_reason"] in {"preference", "coverage"}
        assert resting["value"] in (52.0, 49.0), "never 101 — that would be the sum"
        assert len(resting["other_sources"]) == 1
    finally:
        await cleanup_test_tenant(tenant_id)
