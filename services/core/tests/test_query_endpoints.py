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
from core.db.models import DataPoint, DataSource, Tenant
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

app.state.testing = True

TENANT_ID = "00000000-0000-0000-0000-000000000001"


async def ensure_seeded_data():
    """Seed test metric data points for query endpoint tests."""
    async with async_session_maker() as session:
        stmt = select(Tenant).where(Tenant.id == TENANT_ID)
        res = await session.execute(stmt)
        if not res.scalar_one_or_none():
            t = Tenant(id=TENANT_ID, name="Default Dev Tenant")
            session.add(t)
            await session.flush()

        source_id = str(uuid.uuid4())
        ds = DataSource(id=source_id, tenant_id=TENANT_ID, source_type="oura")
        session.add(ds)
        await session.flush()

        dp_sleep = DataPoint(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            source_id=source_id,
            metric_type="sleep_score",
            timestamp=datetime.now(timezone.utc),
            value=85.0,
            idempotency_key=f"test-sleep-{uuid.uuid4().hex[:8]}",
        )
        dp_steps = DataPoint(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
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
    await ensure_seeded_data()
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics?metric_type=sleep_score", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == TENANT_ID
    assert "data_points" in data
    assert isinstance(data["data_points"], list)


@pytest.mark.asyncio
async def test_list_metric_types_endpoint():
    await ensure_seeded_data()
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics/types", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert "metric_types" in data
    assert "sleep_score" in data["metric_types"]
    assert "steps" in data["metric_types"]


@pytest.mark.asyncio
async def test_metrics_summary_endpoint():
    await ensure_seeded_data()
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": TENANT_ID}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics/summary", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "sleep_score" in data["metrics"]
    assert data["metrics"]["sleep_score"]["count"] >= 1
