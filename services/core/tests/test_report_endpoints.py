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
        assert entry["primary_reason"] == "COVERAGE"
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
    assert first == second == ("aaa", "COVERAGE")


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
            assert entry["primary_reason"] == "PREFERENCE"

            cleared = await client.delete(
                "/api/v1/data/metrics/source-preferences/steps", headers=headers
            )
            assert cleared.status_code == 200

            listed = (
                await client.get(
                    "/api/v1/data/metrics/source-preferences", headers=headers
                )
            ).json()
            assert listed["metrics"][0]["primary_reason"] == "COVERAGE"

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
