import pytest
from httpx import AsyncClient, ASGITransport
from core.main import app

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

@pytest.fixture
def auth_headers():
    return {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001"}

@pytest.mark.asyncio
async def test_manual_sync_trigger_returns_202(auth_headers, mock_nats):
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
        subject, msg_payload = mock_nats.published[-1]
        assert subject == "qs.task.sync.oura"

@pytest.mark.asyncio
async def test_configure_source_stores_custom_config_and_publishes_task(auth_headers, mock_nats):
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
        subject, msg_payload = mock_nats.published[-1]
        assert subject == "qs.task.sync.oura"

@pytest.mark.asyncio
async def test_internal_token_endpoint_returns_token_and_config(auth_headers):
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
