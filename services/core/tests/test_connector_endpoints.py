"""Integration tests for Core Data Service Connector Configuration & Secret Encryption endpoints.

Verifies:
- POST /api/v1/data/sources/configure
- GET /api/v1/data/sources

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- SecretMaskedInReadResponse
"""

import pytest
from core.main import app
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

app.state.testing = True

@pytest.mark.asyncio
async def test_configure_and_list_connectors():
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = {"X-Tenant-ID": tenant_id}

    # Step 1: Configure Oura Ring connector
    payload = {
        "source_type": "oura",
        "access_token": "oura_personal_token_secret_9999",
        "status": "active"
    }

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            config_res = await ac.post("/api/v1/data/sources/configure", json=payload, headers=headers)
    
        assert config_res.status_code == 200
        config_data = config_res.json()
        assert config_data["status"] == "success"
        assert config_data["source_type"] == "oura"
        assert config_data["masked_token"] == "••••••••9999"
        assert "oura_personal_token" not in config_data["masked_token"]

    # Step 2: List connectors for tenant and verify secret is masked
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            list_res = await ac.get("/api/v1/data/sources", headers=headers)

        assert list_res.status_code == 200
        list_data = list_res.json()
        assert "connectors" in list_data
        assert len(list_data["connectors"]) >= 1

        source_id = config_data["source_id"]
        oura_conn = next(c for c in list_data["connectors"] if c["id"] == source_id)
        assert oura_conn["masked_token"] == "••••••••9999"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_configure_yazio_and_delete_connector(monkeypatch):
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = {"X-Tenant-ID": tenant_id}

    # Step 1: Configure Yazio with direct Bearer Token
    payload = {
        "source_type": "yazio",
        "access_token": "yazio_token_secret_1234",
        "status": "active"
    }

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post("/api/v1/data/sources/configure", json=payload, headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            assert data["source_type"] == "yazio"

            # Verify DELETE endpoint
            del_res = await ac.delete("/api/v1/data/sources/yazio", headers=headers)
            assert del_res.status_code == 200
            del_data = del_res.json()
            assert del_data["status"] == "success"

            # Verify list is empty
            list_res = await ac.get("/api/v1/data/sources", headers=headers)
            assert list_res.status_code == 200
            assert len(list_res.json()["connectors"]) == 0
    finally:
        await cleanup_test_tenant(tenant_id)
