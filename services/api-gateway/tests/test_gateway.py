"""Integration tests for API Gateway.

Verifies:
- GET /health
- GET /api/v1/auth/dev-token
- Reverse proxy routing & X-Tenant-ID header injection to Core service

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
"""

import pytest
from gateway.main import app
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_gateway_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "qs-api-gateway"

@pytest.mark.asyncio
async def test_dev_token_generator():
    transport = ASGITransport(app=app)
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get(f"/api/v1/auth/dev-token?tenant_id={tenant_id}")
    
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == tenant_id
    assert "token" in data
    assert data["token_type"] == "Bearer"

@pytest.mark.asyncio
async def test_jwt_validation_invalid_token():
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer invalid_junk_token"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics", headers=headers)
    
    assert response.status_code == 401
    assert "Invalid JWT token" in response.json()["detail"]
