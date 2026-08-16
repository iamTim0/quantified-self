"""Integration tests for the daily story endpoint.

Verifies:
- GET /api/v1/data/day

Maps to Fizzbee Invariants:
- StrictTenantIsolationOnRead
- ReturnedDataBelongsToTarget
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from core.daily_story import day_window
from core.db.models import DataPoint, DataSource, SyncRun
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True


async def _sleep() -> None:
    """A short wait, for a report Core computes in a background task."""
    import asyncio

    await asyncio.sleep(0.1)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _source(tenant_id: str, source_type: str = "oura") -> str:
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


async def _point(
    tenant_id: str,
    source_id: str,
    metric_type: str,
    at: datetime,
    value: float,
    metadata: dict | None = None,
) -> None:
    async with async_session_maker() as session:
        session.add(
            DataPoint(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type=metric_type,
                timestamp=at,
                value=value,
                metadata_=metadata or {},
                idempotency_key=f"{metric_type}-{uuid.uuid4().hex}",
            )
        )
        await session.commit()


def test_a_local_day_is_not_a_utc_day():
    """The whole reason this endpoint exists rather than reusing /metrics.

    Day rollups are `date_trunc('day')` in UTC, so a reader two hours east would
    otherwise be shown a "day" running 22:00 to 22:00 — and a meal at 23:30 would
    be filed under tomorrow.
    """
    east = day_window(date(2026, 8, 16), 120)
    assert east.start.isoformat() == "2026-08-15T22:00:00+00:00"
    assert east.end.isoformat() == "2026-08-16T22:00:00+00:00"

    west = day_window(date(2026, 8, 16), -300)
    assert west.start.isoformat() == "2026-08-16T05:00:00+00:00"
    assert west.end.isoformat() == "2026-08-17T05:00:00+00:00"

    # Exactly 24 hours whatever the offset.
    assert east.end - east.start == timedelta(days=1)
    assert west.end - west.start == timedelta(days=1)


@pytest.mark.asyncio
async def test_a_late_evening_point_belongs_to_the_readers_day_not_utcs():
    """A point at 23:30 local is yesterday's, and UTC bucketing would lose it."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        # 23:30 at UTC+2 is 21:30 UTC on the same date — a UTC day bucket would
        # agree here. 00:30 local is 22:30 UTC on the *previous* date, and that
        # is the one that moves.
        local_after_midnight = day_window(yesterday, 120).start + timedelta(minutes=30)
        await _point(tenant_id, source_id, "steps", local_after_midnight, 1234.0)

        async with await _client() as client:
            body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=120",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        activity = next(lane for lane in body["lanes"] if lane["category"] == "activity")
        steps = next(m for m in activity["metrics"] if m["metric_type"] == "steps")
        assert steps["value"] == 1234.0

        # Read as UTC, the same point falls on the day before.
        async with await _client() as client:
            utc_body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(tenant_id),
                )
            ).json()
        assert not any(lane["category"] == "activity" for lane in utc_body["lanes"])
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_today_is_never_reported_complete():
    """A day still in progress cannot be complete, whatever the importers say."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        now = datetime.now(timezone.utc)
        await _point(tenant_id, source_id, "steps", now, 500.0)
        async with async_session_maker() as session:
            # An import that finished in the future relative to the window end.
            session.add(
                SyncRun(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="oura",
                    request_id="req_today",
                    status="success",
                    started_at=now,
                    finished_at=now + timedelta(days=2),
                )
            )
            await session.commit()

        async with await _client() as client:
            body = (
                await client.get(
                    "/api/v1/data/day?offset_minutes=0", headers=auth_headers(tenant_id)
                )
            ).json()

        assert body["is_today"] is True
        assert body["complete"] is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_lane_reports_when_its_connector_last_ran():
    """An empty lane must be distinguishable from a connector that has not run.

    Rendering both as "nothing happened" turns an import schedule into a finding,
    which is the mistake the card grid made.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        window = day_window(yesterday, 0)
        await _point(tenant_id, source_id, "steps", window.start + timedelta(hours=9), 7000.0)

        async with async_session_maker() as session:
            session.add(
                SyncRun(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="oura",
                    request_id="req_done",
                    status="success",
                    started_at=window.end,
                    finished_at=window.end + timedelta(hours=1),
                )
            )
            await session.commit()

        async with await _client() as client:
            body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        activity = next(lane for lane in body["lanes"] if lane["category"] == "activity")
        assert activity["last_import_at"] is not None
        assert activity["complete"] is True
        assert body["complete"] is True
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_two_connectors_reporting_one_metric_are_never_added():
    """Rule 19: one connector answers, and the story says which."""
    tenant_id = await create_test_tenant()
    try:
        oura = await _source(tenant_id, "oura")
        apple = await _source(tenant_id, "apple_health")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        at = day_window(yesterday, 0).start + timedelta(hours=10)

        await _point(tenant_id, oura, "steps", at, 4000.0)
        await _point(tenant_id, apple, "steps", at + timedelta(minutes=1), 6000.0)

        async with await _client() as client:
            body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        activity = next(lane for lane in body["lanes"] if lane["category"] == "activity")
        steps = next(m for m in activity["metrics"] if m["metric_type"] == "steps")
        # 10000 would be the double count. One source answers.
        assert steps["value"] in (4000.0, 6000.0)
        assert steps["source_reason"] in ("COVERAGE", "PREFERENCE")
        assert len(steps["other_sources"]) == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_workout_is_one_event_not_twelve_numbers():
    """The metrics of one session are regrouped by the metadata that joins them."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "apple_health")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        at = day_window(yesterday, 0).start + timedelta(hours=18)
        meta = {"workout_name": "Running", "end_time": (at + timedelta(minutes=45)).isoformat()}

        await _point(tenant_id, source_id, "workout_duration", at, 2700.0, meta)
        await _point(tenant_id, source_id, "workout_distance", at, 8200.0, meta)
        await _point(tenant_id, source_id, "workout_energy", at, 610.0, meta)

        async with await _client() as client:
            body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        assert len(body["events"]) == 1
        event = body["events"][0]
        assert event["title"] == "Running"
        assert event["category"] == "workout"
        assert set(event["measures"]) == {
            "workout_duration",
            "workout_distance",
            "workout_energy",
        }
        assert event["until"] is not None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_future_day_is_refused():
    tenant_id = await create_test_tenant()
    try:
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=2)).date()
        async with await _client() as client:
            response = await client.get(
                f"/api/v1/data/day?day={tomorrow.isoformat()}",
                headers=auth_headers(tenant_id),
            )
        assert response.status_code == 400
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_day_shows_only_the_authenticated_tenants_data():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead."""
    owner = await create_test_tenant()
    intruder = await create_test_tenant()
    try:
        source_id = await _source(owner)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        at = day_window(yesterday, 0).start + timedelta(hours=8)
        await _point(owner, source_id, "steps", at, 9999.0)

        async with await _client() as client:
            seen = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(intruder),
                )
            ).json()
        assert seen["lanes"] == []
        assert seen["events"] == []
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(intruder)


@pytest.mark.asyncio
async def test_a_last_valued_metric_shows_its_newest_reading_not_the_mean():
    """`body_weight` and coordinates are LAST metrics; averaging them is wrong.

    The mean of a day's latitudes is a place the reader was never at, and the
    mean of two weigh-ins is a weight they never had. Rule 19: a wrong number is
    worse than a missing one, because nothing marks it as wrong.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "apple_health")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        window = day_window(yesterday, 0)

        await _point(tenant_id, source_id, "body_weight", window.start + timedelta(hours=7), 80.0)
        await _point(tenant_id, source_id, "body_weight", window.start + timedelta(hours=20), 79.0)

        async with await _client() as client:
            body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        lane = next(lane for lane in body["lanes"] if lane["category"] == "body")
        weight = next(m for m in lane["metrics"] if m["metric_type"] == "body_weight")
        assert weight["aggregation"] == "last"
        # 79.5 would be the average — a weight that was never on the scale.
        assert weight["value"] == 79.0
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_gps_trace_does_not_crowd_the_evening_off_the_timeline():
    """Events are filtered in SQL, so high-volume lane data cannot exhaust the scan.

    Filtering after the limit meant a day whose early hours held a GPS trace
    spent the whole budget before reaching the evening — and the timeline came
    back short while `event_limit_reached` stayed false, so a truncated day was
    indistinguishable from a quiet one.
    """
    tenant_id = await create_test_tenant()
    try:
        dawarich = await _source(tenant_id, "dawarich")
        apple = await _source(tenant_id, "apple_health")
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        window = day_window(yesterday, 0)

        # A morning of location fixes, far more than the event scan's budget.
        async with async_session_maker() as session:
            for minute in range(600):
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=dawarich,
                        metric_type="location_point",
                        timestamp=window.start + timedelta(minutes=minute),
                        value=1.0,
                        metadata_={},
                        idempotency_key=f"loc-{minute}-{uuid.uuid4().hex[:8]}",
                    )
                )
            await session.commit()

        # One workout in the evening, after all of them.
        at = window.start + timedelta(hours=19)
        await _point(
            tenant_id, apple, "workout_duration", at, 1800.0, {"workout_name": "Evening ride"}
        )

        async with await _client() as client:
            body = (
                await client.get(
                    f"/api/v1/data/day?day={yesterday.isoformat()}&offset_minutes=0",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        assert [event["title"] for event in body["events"]] == ["Evening ride"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_day_report_holds_both_days_and_records_which_day_it_is_for():
    """The story is a stored run, so opening the page reads a row, not a scan."""

    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        at = day_window(yesterday, 0).start + timedelta(hours=9)
        await _point(tenant_id, source_id, "steps", at, 7000.0)

        async with await _client() as client:
            started = await client.post(
                "/api/v1/data/reports/day/refresh",
                json={"offset_minutes": 0},
                headers=auth_headers(tenant_id),
            )
            assert started.status_code == 202

            body = {}
            for _ in range(40):
                body = (
                    await client.get(
                        "/api/v1/data/reports/day", headers=auth_headers(tenant_id)
                    )
                ).json()
                if body["status"] == "ready":
                    break
                await _sleep()

        assert body["status"] == "ready", body
        days = body["result"]["days"]
        # Yesterday first, then today — the order the page renders.
        assert len(days) == 2
        assert days[0]["day"] == yesterday.isoformat()
        assert days[0]["is_today"] is False
        assert days[1]["is_today"] is True
        # The day it answers for is recorded, which is what the rollover check reads.
        assert body["params"]["day"] == days[1]["day"]
    finally:
        await cleanup_test_tenant(tenant_id)


def test_a_day_report_goes_stale_at_the_readers_midnight():
    """The one kind that expires on a clock rather than on an import.

    At one minute past midnight a run computed yesterday still holds the wrong
    two days. No data changed, so the data-driven trigger sees nothing, and the
    twelve-hour age backstop would leave the landing page naming the wrong days
    for most of a morning.
    """
    from core.db.models import ReportRun
    from core.reports import day_report_has_rolled_over

    today = datetime.now(timezone.utc).date()

    current = ReportRun(kind="day", params={"day": today.isoformat(), "offset_minutes": 0})
    assert day_report_has_rolled_over(current) is False

    rolled = ReportRun(
        kind="day",
        params={"day": (today - timedelta(days=1)).isoformat(), "offset_minutes": 0},
    )
    assert day_report_has_rolled_over(rolled) is True

    # A run from before the day was recorded cannot be trusted to be current.
    legacy = ReportRun(kind="day", params={})
    assert day_report_has_rolled_over(legacy) is True
