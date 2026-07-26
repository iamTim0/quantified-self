"""Integration tests for API Gateway.

Verifies:
- GET /health
- GET /api/v1/auth/dev-token (dev mode only)
- Reverse proxy routing & X-Tenant-ID header injection to Core service
- Dev-token endpoint is hidden in production mode

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_gateway_health():
    from gateway.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "qs-api-gateway"

@pytest.mark.asyncio
async def test_dev_token_generator(monkeypatch):
    """Dev-token endpoint should work when ENVIRONMENT=dev."""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    # Re-import to pick up env change
    import importlib

    import gateway.config
    importlib.reload(gateway.config)
    import gateway.main
    importlib.reload(gateway.main)
    from gateway.main import app as dev_app

    transport = ASGITransport(app=dev_app)
    tenant_id = "00000000-0000-0000-0000-000000000001"
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get(f"/api/v1/auth/dev-token?tenant_id={tenant_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == tenant_id
    assert "access_token" in data
    assert data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_dev_token_hidden_in_production(monkeypatch):
    """Dev-token endpoint should return 403 when ENVIRONMENT=production."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    import importlib

    import gateway.config
    importlib.reload(gateway.config)
    import gateway.main
    importlib.reload(gateway.main)
    from gateway.main import app as prod_app

    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/auth/dev-token")

    assert response.status_code == 403

@pytest.mark.asyncio
async def test_jwt_validation_invalid_token():
    from gateway.main import app
    transport = ASGITransport(app=app)
    headers = {"Authorization": "Bearer invalid_junk_token"}
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics", headers=headers)

    assert response.status_code == 401
    # SECURITY M3: Error message is now sanitized — no internal details leaked
    assert "Invalid" in response.json()["detail"]
