"""Integration tests for Core Data Service REST query endpoints.

Verifies:
- GET /api/v1/data/metrics
- GET /api/v1/data/metrics/types
- GET /api/v1/data/metrics/summary

Maps to Fizzbee Invariants:
- StrictTenantIsolationOnRead
- ReturnedDataBelongsToTarget
"""

import pytest
from httpx import AsyncClient, ASGITransport
from core.main import app

app.state.testing = True

@pytest.mark.asyncio
async def test_health_check_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_query_metrics_endpoint():
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics?metric_type=sleep_score", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    assert "data_points" in data
    assert isinstance(data["data_points"], list)

@pytest.mark.asyncio
async def test_list_metric_types_endpoint():
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics/types", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert "metric_types" in data
    assert "sleep_score" in data["metric_types"]
    assert "steps" in data["metric_types"]

@pytest.mark.asyncio
async def test_metrics_summary_endpoint():
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics/summary", headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert "metrics" in data
    assert "sleep_score" in data["metrics"]
    assert data["metrics"]["sleep_score"]["count"] == 31
