"""The unified job list behind the notification bell.

Verifies:
- GET /api/v1/data/jobs

Maps to Fizzbee Invariants:
- StrictTenantIsolationOnRead
"""

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest
from core.db.models import DataSource, ReportRun, SyncRun
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

NOW = datetime.now(timezone.utc).replace(microsecond=0)


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _source(tenant_id: str, source_type: str = "whoop") -> str:
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                display_name="My Whoop",
            )
        )
        await session.commit()
    return source_id


async def _sync_run(tenant_id: str, source_id: str, **kwargs) -> None:
    async with async_session_maker() as session:
        session.add(
            SyncRun(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source_id=source_id,
                source_type=kwargs.pop("source_type", "whoop"),
                request_id=f"req_{uuid.uuid4().hex[:8]}",
                started_at=kwargs.pop("started_at", NOW),
                **kwargs,
            )
        )
        await session.commit()


async def _report_run(tenant_id: str, **kwargs) -> None:
    async with async_session_maker() as session:
        session.add(
            ReportRun(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                kind=kwargs.pop("kind", "insights"),
                request_id=f"req_{uuid.uuid4().hex[:8]}",
                started_at=kwargs.pop("started_at", NOW),
                **kwargs,
            )
        )
        await session.commit()


async def _jobs(tenant_id: str, **params) -> dict:
    # Encoded, because `since` is an ISO timestamp and its `+00:00` offset arrives
    # as a space otherwise -- a 422, and the same trap any client hand-building this
    # query would hit. `URLSearchParams` in the dashboard escapes it correctly.
    query = urlencode(params)
    async with await _client() as client:
        response = await client.get(
            f"/api/v1/data/jobs?{query}" if query else "/api/v1/data/jobs",
            headers=auth_headers(tenant_id),
        )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_imports_and_reports_arrive_in_one_list_newest_first():
    """The whole point: a reader should not have to know which page to open."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _sync_run(
            tenant_id,
            source_id,
            status="success",
            started_at=NOW - timedelta(hours=3),
            finished_at=NOW - timedelta(hours=3),
        )
        await _report_run(
            tenant_id,
            status="success",
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(hours=1),
        )

        body = await _jobs(tenant_id)
        kinds = [job["kind"] for job in body["jobs"]]
        assert kinds == ["report", "import"], kinds
        assert body["jobs"][1]["detail"]["source_name"] == "My Whoop"
        assert body["active_count"] == 0
        assert body["poll_recommended"] is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_import_reports_progress_and_a_report_does_not():
    """A derivation has no interior, so a percentage for it would be invented."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _sync_run(
            tenant_id, source_id, status="running", points_expected=400, points_processed=100
        )
        await _report_run(tenant_id, status="running")

        body = await _jobs(tenant_id)
        by_kind = {job["kind"]: job for job in body["jobs"]}
        assert by_kind["import"]["progress"] == pytest.approx(0.25)
        assert by_kind["report"]["progress"] is None
        assert body["active_count"] == 2
        assert body["poll_recommended"] is True
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_import_with_no_expected_count_claims_no_progress():
    """A push connector cannot say in advance how much is coming.

    Reporting a fraction anyway puts the bar at 100% from the first event to the
    last, which reads as finished for the entire duration of the run.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "apple_health")
        await _sync_run(
            tenant_id,
            source_id,
            source_type="apple_health",
            status="running",
            points_processed=812,
        )

        body = await _jobs(tenant_id)
        assert body["jobs"][0]["progress"] is None
        assert body["jobs"][0]["detail"]["points_processed"] == 812
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_unseen_counts_what_finished_after_the_reader_last_looked():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        looked_at = NOW - timedelta(hours=2)
        await _sync_run(
            tenant_id,
            source_id,
            status="success",
            started_at=NOW - timedelta(hours=5),
            finished_at=NOW - timedelta(hours=5),
        )
        await _sync_run(
            tenant_id,
            source_id,
            status="failed",
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(hours=1),
            message_code="provider_unavailable",
        )

        body = await _jobs(tenant_id, since=looked_at.isoformat())
        assert body["unseen_count"] == 1
        assert body["failed_unseen_count"] == 1

        # Without a stated `since` the answer is "no basis to say", not "nothing
        # new" -- a client that has never looked has nothing to compare against.
        assert (await _jobs(tenant_id))["unseen_count"] is None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_list_shows_only_the_authenticated_tenants_jobs():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead."""
    owner = await create_test_tenant()
    other = await create_test_tenant()
    try:
        await _sync_run(owner, await _source(owner), status="success", finished_at=NOW)
        await _report_run(owner, status="success", finished_at=NOW)

        assert (await _jobs(other))["jobs"] == []
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(other)


@pytest.mark.asyncio
async def test_a_report_nobody_claimed_says_so_rather_than_blaming_the_clock():
    """`report_timeout` and `report_never_claimed` are different events.

    A run still `queued` was never picked up -- the Analysis Service is stopped or
    unreachable -- and telling the reader it "did not complete before the run
    timeout" sends them looking for a slow query that does not exist.
    """
    from core.reports import expire_stale_report_runs

    tenant_id = await create_test_tenant()
    try:
        long_ago = NOW - timedelta(hours=2)
        await _report_run(tenant_id, status="queued", started_at=long_ago)
        await _report_run(tenant_id, status="running", started_at=long_ago, kind="gaps")

        async with async_session_maker() as session:
            changed = await expire_stale_report_runs(session, now=NOW, tenant_ids=[tenant_id])
            await session.commit()
        assert changed == 2

        codes = {
            job["subject"]: job["message_code"] for job in (await _jobs(tenant_id))["jobs"]
        }
        assert codes["insights"] == "report_never_claimed"
        assert codes["gaps"] == "report_timeout"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_long_window_is_given_proportionally_longer_to_finish():
    """A 365-day bundle reads four times the history of a 90-day one.

    A flat thirty minutes gave both the same allowance, so the run most likely to
    need the time was the one most likely to be killed for taking it. The allowance
    scales with `params.days`; a 90-day run keeps exactly what it has today.
    """
    from core.reports import expire_stale_report_runs

    tenant_id = await create_test_tenant()
    try:
        # Forty minutes in: past the flat thirty, inside a 365-day allowance.
        started = NOW - timedelta(minutes=40)
        await _report_run(tenant_id, status="running", started_at=started, params={"days": 365})
        await _report_run(
            tenant_id, status="running", started_at=started, kind="gaps", params={"days": 90}
        )

        async with async_session_maker() as session:
            changed = await expire_stale_report_runs(session, now=NOW, tenant_ids=[tenant_id])
            await session.commit()

        # Only the 90-day one is past its allowance.
        assert changed == 1
        by_kind = {job["subject"]: job for job in (await _jobs(tenant_id))["jobs"]}
        assert by_kind["insights"]["status"] == "running"
        assert by_kind["gaps"]["status"] == "error"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_in_flight_guard_uses_the_same_allowance_as_the_sweep():
    """Otherwise a click in minute thirty-one queues a second run beside the first.

    The guard exists to stop a row of impatient clicks becoming a row of identical
    scans, and it would have stopped doing so exactly for the long windows that take
    longest.
    """
    from core.reports import has_in_flight_report

    tenant_id = await create_test_tenant()
    try:
        started = NOW - timedelta(minutes=40)
        await _report_run(tenant_id, status="running", started_at=started, params={"days": 365})

        async with async_session_maker() as session:
            assert await has_in_flight_report(session, tenant_id, "insights", now=NOW) is True
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_run_that_states_no_window_keeps_the_flat_allowance():
    """The gap, conflict and day reports are computed inside Core in seconds.

    They state no `days`, so nothing about them may change.
    """
    from core.reports import expire_stale_report_runs

    tenant_id = await create_test_tenant()
    try:
        await _report_run(
            tenant_id, status="running", started_at=NOW - timedelta(minutes=31), kind="day"
        )
        async with async_session_maker() as session:
            changed = await expire_stale_report_runs(session, now=NOW, tenant_ids=[tenant_id])
            await session.commit()
        assert changed == 1
    finally:
        await cleanup_test_tenant(tenant_id)
