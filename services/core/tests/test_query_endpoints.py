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
from datetime import datetime, timezone

import pytest
from core.db.models import DataPoint, DataSource
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

async def ensure_seeded_data(tenant_id: str):
    """Seed test metric data points for query endpoint tests."""
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        ds = DataSource(id=source_id, tenant_id=tenant_id, source_type="oura")
        session.add(ds)
        await session.flush()

        dp_sleep = DataPoint(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source_id,
            metric_type="sleep_score",
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


@pytest.mark.asyncio
async def test_health_check_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_query_metrics_endpoint():
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        await ensure_seeded_data(tenant_id)
        headers = auth_headers(tenant_id)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get("/api/v1/data/metrics?metric_type=sleep_score", headers=headers)
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
    assert "sleep_score" in data["metric_types"]
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
    assert "sleep_score" in data["metrics"]
    assert data["metrics"]["sleep_score"]["count"] >= 1
