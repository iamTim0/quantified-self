"""Integration tests for coverage, import planning and sync history endpoints.

These run against the real database so the SQL bucketing is exercised, not mocked.
Each test creates its own tenant and removes it again (AGENTS.md rule 10).

Maps to Fizzbee Invariants:
- StrictTenantIsolationOnRead
- NoDuplicateData
- SmartSkipOnlyWhenComplete
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataPoint, DataSource, SyncRun
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)


class MockNATSClient:
    def __init__(self):
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject, payload):
        self.published.append((subject, payload))


@pytest.fixture
def mock_nats():
    nc = MockNATSClient()
    app.state.nats_client = nc
    return nc


async def _seed_source(tenant_id: str, source_type: str = "whoop", **config) -> str:
    source_id = str(uuid.uuid4())
    cfg = {"status": "active", "encrypted_token": "x", "poll_interval_hours": 6,
           "lookback_days": 30}
    cfg.update(config)
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id, tenant_id=tenant_id, source_type=source_type, config=cfg
            )
        )
        await session.commit()
    return source_id


async def _seed_hourly_days(tenant_id: str, source_id: str, days: range) -> None:
    """One point per hour for each named day offset from BASE."""
    async with async_session_maker() as session:
        for day in days:
            for hour in range(24):
                ts = BASE + timedelta(days=day, hours=hour)
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="recovery_score",
                        timestamp=ts,
                        value=float(hour),
                        idempotency_key=f"seed-{day}-{hour}-{uuid.uuid4().hex[:6]}",
                    )
                )
        await session.commit()


@pytest.mark.asyncio
async def test_coverage_reports_present_and_missing_ranges():
    """Coverage must describe real data, bucketed in SQL."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        await _seed_hourly_days(tenant_id, source_id, range(0, 5))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/data/coverage",
                params={
                    "start": BASE.isoformat(),
                    "end": (BASE + timedelta(days=8)).isoformat(),
                    "source_type": "whoop",
                },
                headers=auth_headers(tenant_id),
            )

        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total_points"] == 5 * 24
        assert data["covered_ranges"], "expected the seeded days to be covered"
        assert data["missing_ranges"], "expected the unseeded tail to be missing"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_coverage_does_not_leak_across_tenants():
    """Another tenant's points must never count as coverage.

    Verifies Fizzbee Invariant: StrictTenantIsolationOnRead
    """
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    try:
        source_a = await _seed_source(tenant_a)
        await _seed_hourly_days(tenant_a, source_a, range(0, 5))
        await _seed_source(tenant_b)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/data/coverage",
                params={
                    "start": BASE.isoformat(),
                    "end": (BASE + timedelta(days=5)).isoformat(),
                },
                headers=auth_headers(tenant_b),
            )

        assert res.status_code == 200
        assert res.json()["total_points"] == 0
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


@pytest.mark.asyncio
async def test_import_plan_narrows_to_the_missing_tail():
    """Smart mode proposes only the range that is actually absent."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        await _seed_hourly_days(tenant_id, source_id, range(0, 5))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/sources/whoop/import-plan",
                json={
                    "start": BASE.isoformat(),
                    "end": (BASE + timedelta(days=8)).isoformat(),
                    "mode": "smart",
                },
                headers=auth_headers(tenant_id),
            )

        assert res.status_code == 200, res.text
        plan = res.json()
        assert plan["mode"] == "smart"
        assert plan["recommended_range"] is not None
        recommended_start = datetime.fromisoformat(plan["recommended_range"]["start"])
        assert recommended_start >= BASE + timedelta(days=4)
        assert plan["skipped_ranges"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_import_plan_force_skips_nothing():
    """Force mode must propose the whole requested range and warn about the cost."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id)
        await _seed_hourly_days(tenant_id, source_id, range(0, 5))

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/sources/whoop/import-plan",
                json={
                    "start": BASE.isoformat(),
                    "end": (BASE + timedelta(days=5)).isoformat(),
                    "mode": "force",
                },
                headers=auth_headers(tenant_id),
            )

        plan = res.json()
        assert plan["mode"] == "force"
        assert plan["skipped_ranges"] == []
        assert "Force mode" in plan["reason"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_sync_publishes_a_window_and_records_a_run(mock_nats):
    """The task payload carries the window; the run is the audit record."""
    tenant_id = await create_test_tenant()
    try:
        await _seed_source(tenant_id, "whoop")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/sources/sync",
                json={"source_type": "whoop", "mode": "smart"},
                headers=auth_headers(tenant_id),
            )

        assert res.status_code == 202, res.text
        subject, payload = mock_nats.published[-1]
        assert subject == "qs.task.sync.whoop"

        import json

        event = json.loads(payload.decode())
        assert event["tenant_id"] == tenant_id
        assert event["mode"] == "smart"
        assert event["window_start"] and event["window_end"]
        assert event["request_id"] and event["sync_run_id"]

        async with async_session_maker() as session:
            runs = await session.execute(
                select(SyncRun).where(SyncRun.tenant_id == tenant_id)
            )
            run = runs.scalars().first()
            assert run is not None
            assert run.status == "queued"
            assert run.window_start is not None
            assert run.window_reason
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_sync_skips_when_the_range_is_already_complete(mock_nats):
    """A complete range must not enqueue work at all."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id, "whoop")
        # Cover a wide, dense range so the derived window lands inside it.
        await _seed_hourly_days(tenant_id, source_id, range(0, 40))
        before = len(mock_nats.published)

        now = BASE + timedelta(days=30)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/sources/sync",
                json={
                    "source_type": "whoop",
                    "mode": "smart",
                    "start": (now - timedelta(days=5)).isoformat(),
                    "end": now.isoformat(),
                },
                headers=auth_headers(tenant_id),
            )

        assert res.status_code == 202
        body = res.json()
        assert body["status"] == "skipped"
        assert "already complete" in body["plan"]["reason"]
        assert len(mock_nats.published) == before, "nothing should have been enqueued"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_force_sync_enqueues_even_when_complete(mock_nats):
    """Force overrides the skip, and the run records that it was a force import."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id, "whoop")
        await _seed_hourly_days(tenant_id, source_id, range(0, 40))

        now = BASE + timedelta(days=30)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/sources/sync",
                json={
                    "source_type": "whoop",
                    "mode": "force",
                    "start": (now - timedelta(days=5)).isoformat(),
                    "end": now.isoformat(),
                },
                headers=auth_headers(tenant_id),
            )

        assert res.status_code == 202
        assert res.json()["status"] == "sync_queued"

        async with async_session_maker() as session:
            runs = await session.execute(
                select(SyncRun).where(SyncRun.tenant_id == tenant_id)
            )
            run = runs.scalars().first()
            assert run.mode == "force"
            assert run.skipped_ranges == []
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_sync_history_is_listed_and_tenant_scoped(mock_nats):
    """Import history is queryable and never shows another tenant's runs."""
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    try:
        await _seed_source(tenant_a, "whoop")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/data/sources/sync",
                json={"source_type": "whoop", "mode": "smart"},
                headers=auth_headers(tenant_a),
            )

            mine = await ac.get(
                "/api/v1/data/sources/whoop/sync-runs", headers=auth_headers(tenant_a)
            )
            theirs = await ac.get(
                "/api/v1/data/sources/whoop/sync-runs", headers=auth_headers(tenant_b)
            )

        assert len(mine.json()["runs"]) == 1
        assert mine.json()["runs"][0]["mode"] == "smart"
        assert theirs.json()["runs"] == []
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


@pytest.mark.asyncio
async def test_adaptive_window_resumes_from_the_last_successful_run(mock_nats):
    """A completed run moves the resume point; the next window starts near it."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _seed_source(tenant_id, "whoop", poll_interval_hours=1)
        last_end = datetime.now(timezone.utc) - timedelta(hours=3)

        async with async_session_maker() as session:
            session.add(
                SyncRun(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    source_type="whoop",
                    request_id="req-previous",
                    mode="smart",
                    trigger="manual",
                    window_start=last_end - timedelta(hours=6),
                    window_end=last_end,
                    status="success",
                )
            )
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/data/sources/sync",
                json={"source_type": "whoop", "mode": "smart"},
                headers=auth_headers(tenant_id),
            )

        import json

        event = json.loads(mock_nats.published[-1][1].decode())
        window_start = datetime.fromisoformat(event["window_start"])
        # Hourly polling means a two-hour overlap before the previous end.
        assert window_start == pytest.approx(
            last_end - timedelta(hours=2), abs=timedelta(minutes=1)
        )
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_coverage_rejects_an_inverted_window():
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/data/coverage",
                params={
                    "start": (BASE + timedelta(days=5)).isoformat(),
                    "end": BASE.isoformat(),
                },
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 400
    finally:
        await cleanup_test_tenant(tenant_id)
