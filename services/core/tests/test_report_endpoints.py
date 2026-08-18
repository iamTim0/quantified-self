"""Integration tests for precomputed reports.

Verifies:
- GET  /api/v1/data/reports/{kind}
- POST /api/v1/data/reports/{kind}/refresh
- GET/PUT/DELETE /api/v1/data/metrics/source-preferences

Maps to Fizzbee Invariants:
- ReportSingleFlight
- ReportNeverServesFutureData
- StrictTenantIsolationOnRead
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import (
    DataPoint,
    DataSource,
    MetricSourcePreference,
    ReportRun,
    SyncRun,
)
from core.db.session import async_session_maker
from core.main import app
from core.reports import report_is_stale, tenant_data_high_water
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_source(tenant_id: str, source_type: str = "oura") -> str:
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


@pytest.mark.asyncio
async def test_a_report_that_has_never_run_says_so_rather_than_computing():
    """Reading never triggers a computation — that is the whole point.

    Before this, opening the page *was* the trigger, so the cost of looking was
    the cost of a full-history scan.
    """
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            response = await client.get(
                "/api/v1/data/reports/gaps", headers=auth_headers(tenant_id)
            )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "never_computed"
        assert body["result"] is None
        assert body["computed_at"] is None
        assert body["stale"] is True
        assert body["error"] is None

        # Nothing was written by a read.
        async with async_session_maker() as session:
            runs = (
                await session.execute(
                    select(ReportRun).where(ReportRun.tenant_id == tenant_id)
                )
            ).scalars().all()
        assert runs == []
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_failed_report_exposes_a_machine_code_and_fallback_message():
    """A failed first run is visible instead of looking like no computation."""
    tenant_id = await create_test_tenant()
    try:
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            session.add(
                ReportRun(
                    tenant_id=tenant_id,
                    kind="insights",
                    status="error",
                    trigger="manual",
                    request_id="req_failure",
                    message_code="insights_failed_ValueError",
                    message_params={},
                    message="The Analysis Service could not compute this report.",
                    started_at=now - timedelta(minutes=1),
                    finished_at=now,
                )
            )
            await session.commit()

        async with await _client() as client:
            response = await client.get(
                "/api/v1/data/reports/insights", headers=auth_headers(tenant_id)
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "never_computed"
        assert body["result"] is None
        assert body["error"]["code"] == "insights_failed_ValueError"
        assert body["error"]["message"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_unknown_report_kind_is_a_404():
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            response = await client.get(
                "/api/v1/data/reports/nonsense", headers=auth_headers(tenant_id)
            )
        assert response.status_code == 404
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_refreshing_conflicts_stores_a_run_that_the_read_then_serves():
    """A manual refresh computes once; the read afterwards is a stored row."""
    tenant_id = await create_test_tenant()
    try:
        await _seed_source(tenant_id)
        async with await _client() as client:
            started = await client.post(
                "/api/v1/data/reports/conflicts/refresh", headers=auth_headers(tenant_id)
            )
            assert started.status_code == 202
            assert started.json()["started"] is True

            # `conflicts` is computed by Core in a background task, so the read is
            # retried briefly rather than assumed to be instant.
            body = {}
            for _ in range(40):
                response = await client.get(
                    "/api/v1/data/reports/conflicts", headers=auth_headers(tenant_id)
                )
                body = response.json()
                if body["status"] == "ready":
                    break
                await _sleep()

        assert body["status"] == "ready", body
        assert body["computed_at"] is not None
        assert body["result"]["conflicts"] == []
    finally:
        await cleanup_test_tenant(tenant_id)


async def _sleep() -> None:
    import asyncio

    await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_a_second_refresh_does_not_queue_a_second_run():
    """Verifies Fizzbee Invariant: ReportSingleFlight.

    Two impatient clicks must not become two identical scans. `insights` is used
    because its run stays queued until a worker claims it, which is exactly the
    window in which a duplicate could be created.
    """
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            first = await client.post(
                "/api/v1/data/reports/insights/refresh", headers=auth_headers(tenant_id)
            )
            second = await client.post(
                "/api/v1/data/reports/insights/refresh", headers=auth_headers(tenant_id)
            )

        assert first.json()["started"] is True
        assert second.json()["started"] is False
        assert second.json()["status"] == "already_running"

        async with async_session_maker() as session:
            runs = (
                await session.execute(
                    select(ReportRun).where(
                        ReportRun.tenant_id == tenant_id, ReportRun.kind == "insights"
                    )
                )
            ).scalars().all()
        assert len(runs) == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_report_is_stale_once_an_import_finishes_after_it():
    """Verifies Fizzbee Invariant: ReportNeverServesFutureData.

    Staleness is a comparison of two timestamps, not a recomputation: a run
    records the newest finished import it could see, and a later one makes it
    stale without anything having to re-scan to find out.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        now = datetime.now(timezone.utc)

        async with async_session_maker() as session:
            # A report computed against data as of an hour ago.
            session.add(
                ReportRun(
                    tenant_id=tenant_id,
                    kind="gaps",
                    status="success",
                    trigger="scheduled",
                    request_id="req_test",
                    covers_data_through=now - timedelta(hours=1),
                    payload={"gaps": []},
                    started_at=now - timedelta(hours=1),
                    finished_at=now - timedelta(hours=1),
                )
            )
            await session.commit()

        async with await _client() as client:
            before = (
                await client.get(
                    "/api/v1/data/reports/gaps", headers=auth_headers(tenant_id)
                )
            ).json()
        assert before["stale"] is False, before

        # An import finishes after the report was computed.
        async with async_session_maker() as session:
            session.add(
                SyncRun(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="oura",
                    request_id="req_import",
                    status="success",
                    started_at=now,
                    finished_at=now,
                )
            )
            await session.commit()

        async with await _client() as client:
            after = (
                await client.get(
                    "/api/v1/data/reports/gaps", headers=auth_headers(tenant_id)
                )
            ).json()
        assert after["stale"] is True
        # The stored answer is still served — stale is a label, not a deletion.
        assert after["result"] == {"gaps": []}
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_one_tenants_report_is_never_served_to_another():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead."""
    owner = await create_test_tenant()
    intruder = await create_test_tenant()
    try:
        async with async_session_maker() as session:
            session.add(
                ReportRun(
                    tenant_id=owner,
                    kind="gaps",
                    status="success",
                    trigger="scheduled",
                    request_id="req_owner",
                    payload={"gaps": [{"metric_type": "steps", "missing_dates": ["2026-01-01"]}]},
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        async with await _client() as client:
            seen = (
                await client.get(
                    "/api/v1/data/reports/gaps", headers=auth_headers(intruder)
                )
            ).json()
        assert seen["status"] == "never_computed"
        assert seen["result"] is None
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(intruder)


@pytest.mark.asyncio
async def test_only_metrics_from_several_connectors_offer_a_source_choice():
    """A metric with one source needs no decision and is not listed."""
    tenant_id = await create_test_tenant()
    try:
        oura = await _seed_source(tenant_id, "oura")
        apple = await _seed_source(tenant_id, "apple_health")
        now = datetime.now(timezone.utc)

        async with async_session_maker() as session:
            # `steps` from both connectors; `weight` from one.
            for source_id, metric, value in (
                (oura, "steps", 5000.0),
                (apple, "steps", 9000.0),
                (oura, "weight", 74.0),
            ):
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type=metric,
                        timestamp=now,
                        value=value,
                        idempotency_key=f"{metric}-{source_id}-{uuid.uuid4().hex[:8]}",
                    )
                )
            await session.commit()

        # Rollups are what the endpoint reads, so build them the way ingestion
        # does. Coverage is the *number of samples*, not their magnitude, so
        # apple_health is given more days rather than a larger value.
        from core.rollups import update_rollups_for_point

        async with async_session_maker() as session:
            for day in range(5):
                await update_rollups_for_point(
                    session,
                    tenant_id=tenant_id,
                    source_id=apple,
                    metric_type="steps",
                    timestamp=now - timedelta(days=day),
                    value=9000.0,
                    metadata={},
                )
            await update_rollups_for_point(
                session,
                tenant_id=tenant_id,
                source_id=oura,
                metric_type="steps",
                timestamp=now,
                value=5000.0,
                metadata={},
            )
            await update_rollups_for_point(
                session,
                tenant_id=tenant_id,
                source_id=oura,
                metric_type="weight",
                timestamp=now,
                value=74.0,
                metadata={},
            )
            await session.commit()

        async with await _client() as client:
            listed = (
                await client.get(
                    "/api/v1/data/metrics/source-preferences",
                    headers=auth_headers(tenant_id),
                )
            ).json()

        # `weight` has one source, so it is not a decision anyone has to make.
        names = [entry["metric_type"] for entry in listed["metrics"]]
        assert names == ["steps"], listed
        entry = listed["metrics"][0]
        # No preference stated, so coverage decides — apple_health has five days
        # against Oura's one.
        assert entry["primary_reason"] == "coverage"
        assert entry["primary_source_id"] == apple
        assert [source["sample_count"] for source in entry["sources"]] == [5, 1]
    finally:
        await cleanup_test_tenant(tenant_id)


def test_equal_coverage_is_broken_deterministically():
    """A tie must not flicker between calls.

    Coverage decides when no preference is stated, and two connectors that have
    reported the same number of days are genuinely tied. Falling back to row
    order would make the analysed series change identity between two page loads
    for no reason the reader could see.
    """
    from core.reports import resolve_primary_source

    first = resolve_primary_source(
        ["bbb", "aaa"], preference=None, coverage={"aaa": 7, "bbb": 7}
    )
    second = resolve_primary_source(
        ["aaa", "bbb"], preference=None, coverage={"bbb": 7, "aaa": 7}
    )
    assert first == second == ("aaa", "coverage")


def test_every_reason_is_a_lowercase_identifier():
    """Rule 17: a client compares against this, so it is spelled one way.

    These were `PREFERENCE` / `COVERAGE` / `ONLY_SOURCE` while `direction`,
    `status` and `severity` beside them were lowercase — the same convention in
    two spellings, which leaves the next person to guess. The check is here so a
    fourth reason cannot arrive in a third style.
    """
    from core.reports import SOURCE_REASONS, resolve_primary_source

    assert SOURCE_REASONS == {"only_source", "preference", "coverage"}
    assert all(
        reason == reason.lower() and reason.isascii() and " " not in reason
        for reason in SOURCE_REASONS
    )

    # Not just the constants — what the resolver actually returns.
    _, by_coverage = resolve_primary_source(["a"], preference=None, coverage={"a": 1})
    _, by_preference = resolve_primary_source(["a"], preference="a", coverage={"a": 1})
    assert {by_coverage, by_preference} <= SOURCE_REASONS


@pytest.mark.asyncio
async def test_a_stated_preference_beats_coverage_and_can_be_cleared():
    """A preference is a statement about trust, not a vote that volume can win."""
    tenant_id = await create_test_tenant()
    try:
        oura = await _seed_source(tenant_id, "oura")
        apple = await _seed_source(tenant_id, "apple_health")
        now = datetime.now(timezone.utc)

        from core.rollups import update_rollups_for_point

        async with async_session_maker() as session:
            for source_id, value in ((oura, 5000.0), (apple, 9000.0)):
                await update_rollups_for_point(
                    session,
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    timestamp=now,
                    value=value,
                    metadata={},
                )
            await session.commit()

        async with await _client() as client:
            headers = auth_headers(tenant_id)
            saved = await client.put(
                "/api/v1/data/metrics/source-preferences/steps",
                json={"primary_source_id": oura},
                headers=headers,
            )
            assert saved.status_code == 200
            assert saved.json()["primary_source_id"] == oura

            listed = (
                await client.get(
                    "/api/v1/data/metrics/source-preferences", headers=headers
                )
            ).json()
            entry = listed["metrics"][0]
            # Oura covered less and still answers, because it was chosen.
            assert entry["primary_source_id"] == oura
            assert entry["primary_reason"] == "preference"

            cleared = await client.delete(
                "/api/v1/data/metrics/source-preferences/steps", headers=headers
            )
            assert cleared.status_code == 200

            listed = (
                await client.get(
                    "/api/v1/data/metrics/source-preferences", headers=headers
                )
            ).json()
            assert listed["metrics"][0]["primary_reason"] == "coverage"

        async with async_session_maker() as session:
            rows = (
                await session.execute(
                    select(MetricSourcePreference).where(
                        MetricSourcePreference.tenant_id == tenant_id
                    )
                )
            ).scalars().all()
        assert rows == []
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_high_water_ignores_runs_that_did_not_succeed():
    """A failed import did not change the data, so it must not age a report."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            session.add(
                SyncRun(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="oura",
                    request_id="req_failed",
                    status="error",
                    started_at=now,
                    finished_at=now,
                )
            )
            await session.commit()

            assert await tenant_data_high_water(session, tenant_id) is None

        run = ReportRun(
            tenant_id=tenant_id,
            kind="gaps",
            status="success",
            trigger="scheduled",
            request_id="req",
            covers_data_through=None,
            started_at=now,
            finished_at=now,
        )
        assert report_is_stale(run, None) is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_scheduled_rerun_keeps_the_window_the_reader_asked_for():
    """The mechanism that makes a long-range analysis stay a long-range analysis.

    Asking for 365 days is not a one-off: the scheduler carries the last run's
    params into the next one, so the deep answer is maintained from then on without
    anybody asking again. Without it a tick replaces a 365-day bundle with the
    90-day default and the selector snaps back under the reader -- and
    `offset_minutes` goes with it, so a scheduled run silently reverts to UTC day
    boundaries.

    The behaviour was described in a comment and covered by nothing.
    """
    from core.reports import find_due_reports

    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        # A fixed instant, and a quiet one: at UTC+2 this is 02:00 local, so the
        # 365-day window below is not held back for the night. Wall-clock `now`
        # made the assertion depend on what time the suite happened to run.
        now = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)

        async with async_session_maker() as session:
            # A finished import, so the workspace has something to report on.
            session.add(
                SyncRun(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="oura",
                    request_id="req_seed",
                    status="success",
                    started_at=now - timedelta(hours=2),
                    finished_at=now - timedelta(hours=1),
                )
            )
            # The reader's own run: a year, in their own timezone.
            session.add(
                ReportRun(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    kind="insights",
                    status="success",
                    trigger="manual",
                    request_id="req_reader",
                    started_at=now - timedelta(hours=3),
                    finished_at=now - timedelta(hours=3),
                    covers_data_through=now - timedelta(hours=3),
                    params={"days": 365, "offset_minutes": 120, "compare_to_previous": True},
                    payload={},
                )
            )
            await session.commit()

            due = await find_due_reports(session, now=now)

        insights = [item for item in due if item.tenant_id == tenant_id and item.kind == "insights"]
        assert insights, "a newer import must make the bundle due again"
        assert insights[0].params["days"] == 365
        assert insights[0].params["offset_minutes"] == 120
        assert insights[0].reason == "new_data"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_year_long_recompute_waits_for_the_readers_night():
    """The other half of the long-range analysis: when it runs, not just how wide.

    A 365-day bundle reads a workspace's whole history to redraw a page that is
    already on screen and already right. Doing that the moment an import lands
    spends the most expensive computation the platform has at the time it is most
    in the way. It waits -- and the wait is measured on the *reader's* clock, not
    the server's, because "the middle of the night" is a fact about the reader.
    """
    from core.reports import find_due_reports

    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        # 15:00 for a reader at UTC+2. The middle of their afternoon.
        busy = datetime(2026, 8, 17, 13, 0, tzinfo=timezone.utc)

        async with async_session_maker() as session:
            session.add(
                SyncRun(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="oura",
                    request_id="req_seed",
                    status="success",
                    started_at=busy - timedelta(hours=2),
                    finished_at=busy - timedelta(hours=1),
                )
            )
            session.add(
                ReportRun(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    kind="insights",
                    status="success",
                    trigger="manual",
                    request_id="req_reader",
                    started_at=busy - timedelta(hours=3),
                    finished_at=busy - timedelta(hours=3),
                    covers_data_through=busy - timedelta(hours=3),
                    params={"days": 365, "offset_minutes": 120},
                    payload={},
                )
            )
            await session.commit()

            during_the_day = await find_due_reports(session, now=busy)
            # 02:00 the next morning for the same reader.
            quiet = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
            at_night = await find_due_reports(session, now=quiet)

        def insights_for(due):
            return [i for i in due if i.tenant_id == tenant_id and i.kind == "insights"]

        assert insights_for(during_the_day) == []
        assert insights_for(at_night), "the night is when the deferred run happens"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_deferred_report_says_so_instead_of_only_saying_stale():
    """"Stale" invites a reader to press refresh for something already scheduled.

    Which is exactly what they would do, repeatedly, for a report that was going
    to recompute overnight anyway -- and each press starts the expensive run the
    deferral existed to move.
    """
    from core.db.models import ReportRun as Run
    from core.reports import report_payload

    busy = datetime(2026, 8, 17, 13, 0, tzinfo=timezone.utc)
    run = Run(
        tenant_id="t",
        kind="insights",
        status="success",
        trigger="scheduled",
        request_id="r",
        finished_at=busy - timedelta(hours=3),
        params={"days": 365, "offset_minutes": 120},
        payload={},
    )

    assert report_payload(run, stale=True, now=busy)["deferred"] is True
    # In the quiet hour it is simply due, and nothing is being put off.
    quiet = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
    assert report_payload(run, stale=True, now=quiet)["deferred"] is False
    # And a report nobody is waiting on is not "deferred" either -- there is
    # nothing to recompute.
    assert report_payload(run, stale=False, now=busy)["deferred"] is False


@pytest.mark.asyncio
async def test_a_default_window_is_never_held_back():
    """Every window a reader gets without choosing one behaves exactly as before.

    The deferral is about the 180- and 365-day options. If it reached the default
    it would turn "the dashboard updates when data arrives" into "the dashboard
    updates tomorrow", which is a different product.
    """
    from core.reports import defer_to_quiet_hours

    busy = datetime(2026, 8, 17, 13, 0, tzinfo=timezone.utc)
    run = ReportRun(
        tenant_id="t",
        kind="insights",
        status="success",
        trigger="scheduled",
        request_id="r",
        finished_at=busy - timedelta(hours=3),
        params={},
        payload={},
    )

    for days in (None, 7, 30, 90):
        params = {"offset_minutes": 120} | ({"days": days} if days else {})
        assert defer_to_quiet_hours(run, params, now=busy) is False, days

    # A run with no recorded offset is not deferred either: guessing the reader's
    # night would put it in the middle of their afternoon at UTC+12.
    assert defer_to_quiet_hours(run, {"days": 365}, now=busy) is False

    # A first result is never held back -- an empty page is waiting for an answer.
    assert defer_to_quiet_hours(None, {"days": 365, "offset_minutes": 120}, now=busy) is False

    # And a night that never comes delays a report rather than cancelling it.
    stale_run = ReportRun(
        tenant_id="t",
        kind="insights",
        status="success",
        trigger="scheduled",
        request_id="r",
        finished_at=busy - timedelta(hours=40),
        params={},
        payload={},
    )
    assert (
        defer_to_quiet_hours(stale_run, {"days": 365, "offset_minutes": 120}, now=busy) is False
    )
