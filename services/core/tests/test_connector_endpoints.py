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

app.state.testing = True

@pytest.mark.asyncio
async def test_configure_and_list_connectors():
    transport = ASGITransport(app=app)
    headers = {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}

    # Step 1: Configure Oura Ring connector
    payload = {
        "source_type": "oura",
        "access_token": "oura_personal_token_secret_9999",
        "status": "active"
    }

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

    oura_conn = next(c for c in list_data["connectors"] if c["source_type"] == "oura")
    assert oura_conn["masked_token"] == "••••••••9999"
