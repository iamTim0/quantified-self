"""Integration tests for Core Data Service REST query endpoints.

Verifies:
- GET /api/v1/data/metrics
- GET /api/v1/data/metrics/types
- GET /api/v1/data/metrics/summary

Maps to Fizzbee Invariants:
- StrictTenantIsolationOnRead
- ReturnedDataBelongsToTarget
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataPoint, DataSource, MetricRollup
from core.db.session import async_session_maker
from core.main import app
from core.rollup_coverage import forget_day_rollup_coverage
from core.rollups import update_rollups_for_point
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

async def ensure_seeded_data(tenant_id: str) -> str:
    """Seed test metric data points for query endpoint tests."""
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        ds = DataSource(id=source_id, tenant_id=tenant_id, source_type="oura", display_name="Oura")
        session.add(ds)
        await session.flush()

        dp_sleep = DataPoint(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source_id,
            metric_type="oura_sleep_score",
            timestamp=datetime.now(timezone.utc),
            value=85.0,
            idempotency_key=f"test-sleep-{uuid.uuid4().hex[:8]}",
        )
        dp_steps = DataPoint(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source_id,
            metric_type="steps",
            timestamp=datetime.now(timezone.utc),
            value=10500.0,
            idempotency_key=f"test-steps-{uuid.uuid4().hex[:8]}",
        )
        session.add(dp_sleep)
        session.add(dp_steps)
        await session.commit()
    return source_id


@pytest.mark.asyncio
async def test_health_check_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "qs-core-service"
    assert payload["version"]
    assert payload["commit"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_query_metrics_endpoint():
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        await ensure_seeded_data(tenant_id)
        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get("/api/v1/data/metrics?metric_type=oura_sleep_score", headers=headers)
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == tenant_id
    assert "data_points" in data
    assert isinstance(data["data_points"], list)


@pytest.mark.asyncio
async def test_list_metric_types_endpoint():
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        await ensure_seeded_data(tenant_id)
        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get("/api/v1/data/metrics/types", headers=headers)
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    data = response.json()
    assert "metric_types" in data
    assert "oura_sleep_score" in data["metric_types"]
    assert "steps" in data["metric_types"]


@pytest.mark.asyncio
async def test_metrics_summary_endpoint():
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        await ensure_seeded_data(tenant_id)
        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get("/api/v1/data/metrics/summary", headers=headers)
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "oura_sleep_score" in data["metrics"]
    assert data["metrics"]["oura_sleep_score"]["count"] >= 1


@pytest.mark.asyncio
async def test_query_metrics_returns_tenant_scoped_rollups():
    """Verifies Fizzbee Invariants: StrictTenantIsolationOnRead & ReturnedDataBelongsToTarget."""
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        source_id = await ensure_seeded_data(tenant_id)
        bucket = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        async with async_session_maker() as session:
            session.add(
                MetricRollup(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    resolution="minute",
                    bucket_start=bucket,
                    value=120.0,
                    sample_count=2,
                    sum_value=120.0,
                    min_value=40.0,
                    max_value=80.0,
                    first_value=40.0,
                    last_value=80.0,
                    first_timestamp=bucket,
                    last_timestamp=bucket,
                    metadata_={"derived_by": "sum", "sample_count": 2},
                )
            )
            await session.commit()

        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get(
                "/api/v1/data/metrics?metric_type=steps&resolution=minute",
                headers=headers,
            )
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    data = response.json()
    assert data["resolution"] == "minute"
    assert data["rollup_available"] is True
    assert data["data_points"][0]["source_id"] == source_id
    assert data["data_points"][0]["sample_count"] == 2
    assert data["data_points"][0]["is_derived"] is True


@pytest.mark.asyncio
async def test_query_metrics_merges_legacy_points_with_new_rollups():
    """Verifies Fizzbee Invariants: StrictTenantIsolationOnRead & ReturnedDataBelongsToTarget."""
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    old_timestamp = now - timedelta(days=2)
    try:
        source_id = str(uuid.uuid4())
        async with async_session_maker() as session:
            session.add(
                DataSource(
                    id=source_id,
                    tenant_id=tenant_id,
                    source_type="apple_health",
                    display_name="Apple Health",
                )
            )
            await session.flush()
            session.add(
                DataPoint(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    timestamp=old_timestamp,
                    value=10.0,
                    idempotency_key=f"legacy-{uuid.uuid4().hex}",
                )
            )
            session.add(
                MetricRollup(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    resolution="day",
                    bucket_start=now.replace(hour=0, minute=0),
                    value=50.0,
                    sample_count=2,
                    sum_value=50.0,
                    min_value=20.0,
                    max_value=30.0,
                    first_value=20.0,
                    last_value=30.0,
                    first_timestamp=now,
                    last_timestamp=now,
                    metadata_={
                        "derived_from": ["steps"],
                        "derived_by": "sum",
                        "sample_count": 2,
                    },
                )
            )
            await session.commit()

        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get(
                "/api/v1/data/metrics",
                params={
                    "metric_type": "steps",
                    "resolution": "day",
                    "start_time": (old_timestamp - timedelta(hours=1)).isoformat(),
                    "end_time": (now + timedelta(days=1)).isoformat(),
                    "limit": 10,
                },
                headers=headers,
            )
            summary_response = await ac.get(
                "/api/v1/data/metrics/summary", headers=headers
            )
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert data["rollup_available"] is True
    assert data["contains_legacy_raw"] is True
    assert [point["value"] for point in data["data_points"]] == [10.0, 50.0]
    assert data["data_points"][0]["metadata"]["compatibility_fallback"] is True

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["metrics"]["steps"]["count"] == 3
    assert summary["metrics"]["steps"]["sum"] == 60.0
    assert summary["contains_legacy_raw"] is True


@pytest.mark.asyncio
async def test_query_metrics_ignores_legacy_points_a_full_rollup_page_outranks():
    """Verifies Fizzbee Invariants: StrictTenantIsolationOnRead & ReturnedDataBelongsToTarget.

    A full page of rollups already fills the requested limit, so a legacy raw point
    older than the oldest returned bucket cannot appear in the answer. Core stops
    looking for one there, because `~_rollup_covers_point` is evaluated per row and
    an unbounded search walks the tenant's whole history to return nothing.
    """
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        source_id = str(uuid.uuid4())
        async with async_session_maker() as session:
            session.add(
                DataSource(
                    id=source_id,
                    tenant_id=tenant_id,
                    source_type="apple_health",
                    display_name="Apple Health",
                )
            )
            await session.flush()
            # Older than every bucket below, and covered by no rollup.
            session.add(
                DataPoint(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    timestamp=today - timedelta(days=30),
                    value=10.0,
                    idempotency_key=f"legacy-{uuid.uuid4().hex}",
                )
            )
            for day_offset, value in ((0, 300.0), (1, 200.0)):
                bucket = today - timedelta(days=day_offset)
                session.add(
                    MetricRollup(
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="steps",
                        resolution="day",
                        bucket_start=bucket,
                        value=value,
                        sample_count=1,
                        sum_value=value,
                        min_value=value,
                        max_value=value,
                        first_value=value,
                        last_value=value,
                        first_timestamp=bucket,
                        last_timestamp=bucket,
                        is_provider_total=True,
                    )
                )
            await session.commit()

        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get(
                "/api/v1/data/metrics",
                params={
                    "metric_type": "steps",
                    "resolution": "day",
                    "sort": "desc",
                    "limit": 2,
                },
                headers=headers,
            )
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert [point["value"] for point in data["data_points"]] == [300.0, 200.0]
    # The legacy point ranked below both buckets and was never part of the answer.
    assert data["contains_legacy_raw"] is False


@pytest.mark.asyncio
async def test_metrics_summary_stops_scanning_a_fully_covered_workspace():
    """Verifies Fizzbee Invariant: ReturnedDataBelongsToTarget.

    The compatibility scan is a proof about data written before rollups existed,
    and no import can produce another such point — every insert path updates the
    rollups for it in the same transaction. So the scan runs until it comes back
    empty once, and then stops.

    A point inserted here *behind* Core's back stands in for a scan that should no
    longer be happening: it is exactly what an ingested point can never be, and if
    the second summary counted it the memo would be re-deriving rather than
    remembering.
    """
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    bucket = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        source_id = str(uuid.uuid4())
        async with async_session_maker() as session:
            session.add(
                DataSource(
                    id=source_id,
                    tenant_id=tenant_id,
                    source_type="whoop",
                    display_name="WHOOP",
                )
            )
            await session.flush()
            session.add(
                MetricRollup(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    resolution="day",
                    bucket_start=bucket,
                    value=900.0,
                    sample_count=1,
                    sum_value=900.0,
                    min_value=900.0,
                    max_value=900.0,
                    first_value=900.0,
                    last_value=900.0,
                    first_timestamp=bucket,
                    last_timestamp=bucket,
                    is_provider_total=True,
                )
            )
            await session.commit()

        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            first = await ac.get("/api/v1/data/metrics/summary", headers=headers)

            # Uncovered, and therefore only reachable by a scan.
            async with async_session_maker() as session:
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="steps",
                        timestamp=bucket - timedelta(days=400),
                        value=7.0,
                        idempotency_key=f"behind-core-{uuid.uuid4().hex}",
                    )
                )
                await session.commit()

            second = await ac.get("/api/v1/data/metrics/summary", headers=headers)
            forget_day_rollup_coverage(tenant_id)
            third = await ac.get("/api/v1/data/metrics/summary", headers=headers)
    finally:
        forget_day_rollup_coverage(tenant_id)
        await cleanup_test_tenant(tenant_id)

    assert first.status_code == 200
    assert first.json()["contains_legacy_raw"] is False
    assert first.json()["metrics"]["steps"]["sum"] == 900.0

    # Remembered: the scan did not run again, so the point behind Core's back is
    # not in the answer and the rollup total is untouched.
    assert second.json()["contains_legacy_raw"] is False
    assert second.json()["metrics"]["steps"]["sum"] == 900.0

    # Forgetting restores the scan, which is what a Core restart does.
    assert third.json()["contains_legacy_raw"] is True
    assert third.json()["metrics"]["steps"]["sum"] == 907.0


@pytest.mark.asyncio
async def test_hour_query_still_reads_raw_points_in_a_day_covered_workspace():
    """Verifies Fizzbee Invariant: ReturnedDataBelongsToTarget.

    Day coverage does not imply coverage at the other resolutions and must never be
    read as if it did. `update_rollups_for_point` gives an ordinary raw point a day
    bucket and nothing else, so at hour resolution that point is uncovered by design
    and the compatibility query is where its value comes from — not a compensation
    for old data, but the answer itself. A workspace proven to need no *day*
    compensation must therefore still be read raw for an hour series.
    """
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hourly_at = now - timedelta(hours=5)
    raw_at = now - timedelta(hours=2)
    try:
        source_id = str(uuid.uuid4())
        async with async_session_maker() as session:
            session.add(
                DataSource(
                    id=source_id,
                    tenant_id=tenant_id,
                    source_type="home_assistant",
                    display_name="Home Assistant",
                )
            )
            await session.flush()
            # Imported at hour resolution: hour and day buckets.
            # An ordinary raw point beside it: day bucket only.
            for timestamp, value, metadata in (
                (hourly_at, 21.0, {"ingest_resolution": "hour"}),
                (raw_at, 23.0, {}),
            ):
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="home_assistant_temperature",
                        timestamp=timestamp,
                        value=value,
                        metadata_=metadata,
                        idempotency_key=f"point-{uuid.uuid4().hex}",
                    )
                )
                await update_rollups_for_point(
                    session,
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="home_assistant_temperature",
                    timestamp=timestamp,
                    value=value,
                    metadata=metadata,
                )
            await session.commit()

        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            summary = await ac.get("/api/v1/data/metrics/summary", headers=headers)
            hourly = await ac.get(
                "/api/v1/data/metrics",
                params={
                    "metric_type": "home_assistant_temperature",
                    "resolution": "hour",
                    "sort": "asc",
                    "limit": 100,
                },
                headers=headers,
            )
    finally:
        forget_day_rollup_coverage(tenant_id)
        await cleanup_test_tenant(tenant_id)

    # Every point sits in a day rollup, so the day-resolution proof holds.
    assert summary.json()["contains_legacy_raw"] is False

    # And the hour series is unaffected by it: both readings are present.
    data = hourly.json()
    assert [point["value"] for point in data["data_points"]] == [21.0, 23.0]
    assert data["contains_legacy_raw"] is True


@pytest.mark.asyncio
async def test_metrics_summary_keeps_scanning_while_legacy_points_remain():
    """Verifies Fizzbee Invariant: ReturnedDataBelongsToTarget.

    Only the empty result is remembered. A workspace that still holds legacy
    points is re-queried every time, because that set shrinks — `core.retention`
    and `core.rollup_backfill` both remove members of it — and a remembered
    aggregate would go on reporting points that are gone.
    """
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        source_id = await ensure_seeded_data(tenant_id)
        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            first = await ac.get("/api/v1/data/metrics/summary", headers=headers)

            async with async_session_maker() as session:
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="steps",
                        timestamp=datetime.now(timezone.utc) - timedelta(days=3),
                        value=500.0,
                        idempotency_key=f"legacy-{uuid.uuid4().hex}",
                    )
                )
                await session.commit()

            second = await ac.get("/api/v1/data/metrics/summary", headers=headers)
    finally:
        forget_day_rollup_coverage(tenant_id)
        await cleanup_test_tenant(tenant_id)

    assert first.json()["contains_legacy_raw"] is True
    assert first.json()["metrics"]["steps"]["count"] == 1
    assert second.json()["metrics"]["steps"]["count"] == 2


@pytest.mark.asyncio
async def test_wipe_removes_rollups_with_tenant_data():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnDelete."""
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        source_id = await ensure_seeded_data(tenant_id)
        async with async_session_maker() as session:
            session.add(
                MetricRollup(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="steps",
                    resolution="day",
                    bucket_start=datetime.now(timezone.utc).replace(
                        hour=0, minute=0, second=0, microsecond=0
                    ),
                    value=1.0,
                    sample_count=1,
                    sum_value=1.0,
                    min_value=1.0,
                    max_value=1.0,
                    first_value=1.0,
                    last_value=1.0,
                    first_timestamp=datetime.now(timezone.utc),
                    last_timestamp=datetime.now(timezone.utc),
                    metadata_={"derived_from": ["steps"], "derived_by": "sum"},
                )
            )
            await session.commit()

        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.delete(
                "/api/v1/data/wipe", headers=auth_headers(tenant_id)
            )

        async with async_session_maker() as session:
            remaining = await session.execute(
                select(MetricRollup.id).where(MetricRollup.tenant_id == tenant_id)
            )
            assert remaining.scalar_one_or_none() is None
    finally:
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    assert response.json()["deleted_rollup_count"] == 1


@pytest.mark.asyncio
async def test_ingest_policy_is_tenant_scoped_and_future_only():
    """Verifies Fizzbee Invariants: StrictTenantIsolationOnRead & ReturnedDataBelongsToTarget."""
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            update = await ac.put(
                "/api/v1/data/metrics/ingest-policy/steps",
                headers=headers,
                json={"resolution": "minute", "raw_retention_days": 30},
            )
            policies = await ac.get(
                "/api/v1/data/metrics/ingest-policy", headers=headers
            )
    finally:
        await cleanup_test_tenant(tenant_id)

    assert update.status_code == 200
    assert update.json()["applies_to"] == "future_imports"
    assert policies.status_code == 200
    assert policies.json()["tenant_id"] == tenant_id
    assert policies.json()["policies"]["steps"]["resolution"] == "minute"
    assert policies.json()["policies"]["steps"]["raw_retention_days"] == 30


@pytest.mark.asyncio
async def test_accepted_point_updates_the_rollup_hierarchy():
    """Verifies Fizzbee Invariant: AckAfterPersisted."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await ensure_seeded_data(tenant_id)
        timestamp = datetime.now(timezone.utc).replace(second=17, microsecond=0)
        async with async_session_maker() as session:
            await update_rollups_for_point(
                session,
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type="heart_rate",
                timestamp=timestamp,
                value=72.0,
                metadata={
                    "provider_value": 72,
                    "units": "bpm",
                    "ingest_resolution": "minute",
                },
            )
            await session.commit()
            rows = (
                await session.execute(
                    select(MetricRollup)
                    .where(
                        MetricRollup.tenant_id == tenant_id,
                        MetricRollup.source_id == source_id,
                        MetricRollup.metric_type == "heart_rate",
                    )
                    .order_by(MetricRollup.resolution)
                )
            ).scalars().all()
    finally:
        await cleanup_test_tenant(tenant_id)

    assert {row.resolution for row in rows} == {"minute", "hour", "day"}
    assert all(row.value == 72.0 and row.sample_count == 1 for row in rows)
