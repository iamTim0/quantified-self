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
