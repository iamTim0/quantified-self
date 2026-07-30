import pytest
from core.main import app
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

app.state.testing = True

class MockNATSClient:
    def __init__(self):
        self.published = []
    
    async def publish(self, subject, payload):
        self.published.append((subject, payload))

@pytest.fixture
def mock_nats():
    nc = MockNATSClient()
    app.state.nats_client = nc
    return nc

@pytest.mark.asyncio
async def test_manual_sync_trigger_returns_202(mock_nats):
    tenant_id = await create_test_tenant()
    auth_headers = {"X-Tenant-ID": tenant_id}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # First configure so it exists
            payload = {
                "source_type": "oura",
                "access_token": "test-token",
                "status": "active",
                "config": {"lookback_days": 30}
            }
            await ac.post("/api/v1/data/sources/configure", json=payload, headers=auth_headers)

            res = await ac.post("/api/v1/data/sources/oura/sync", headers=auth_headers)
            assert res.status_code == 202
            data = res.json()
            assert data["status"] == "sync_queued"
            assert data["source_type"] == "oura"
        
            # Check task published
            assert len(mock_nats.published) > 0
            subject, _msg_payload = mock_nats.published[-1]
            assert subject == "qs.task.sync.oura"
    finally:
        await cleanup_test_tenant(tenant_id)

@pytest.mark.asyncio
async def test_configure_source_stores_custom_config_and_publishes_task(mock_nats):
    tenant_id = await create_test_tenant()
    auth_headers = {"X-Tenant-ID": tenant_id}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "source_type": "oura",
                "access_token": "test-token",
                "status": "active",
                "config": {"lookback_days": 30}
            }
            res = await ac.post("/api/v1/data/sources/configure", json=payload, headers=auth_headers)
            assert res.status_code == 200
            
            # Check task published
            assert len(mock_nats.published) > 0
            subject, _msg_payload = mock_nats.published[-1]
            assert subject == "qs.task.sync.oura"
    finally:
        await cleanup_test_tenant(tenant_id)

@pytest.mark.asyncio
async def test_internal_token_endpoint_returns_token_and_config():
    tenant_id = await create_test_tenant()
    auth_headers = {"X-Tenant-ID": tenant_id}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            payload = {
                "source_type": "oura",
                "access_token": "test-token",
                "status": "active",
                "config": {"lookback_days": 30}
            }
            await ac.post("/api/v1/data/sources/configure", json=payload, headers=auth_headers)

            res = await ac.get("/api/v1/internal/data/sources/oura/token", headers=auth_headers)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "active"
            assert data["source_type"] == "oura"
            assert data["access_token"] == "test-token"
            assert data["config"]["lookback_days"] == 30
    finally:
        await cleanup_test_tenant(tenant_id)
