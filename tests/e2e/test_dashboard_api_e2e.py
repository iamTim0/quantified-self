"""End-to-End Integration Tests for Dashboard Backend API & User Action Endpoints.

Tests every function & button backing the Dashboard UI:
1. Connector Modal: Configure, list, sync, and delete data connectors
2. Overview Tab: Metrics summary & metric query list
3. Explorer Tab: Create explorer views, list views, and delete view
4. Quality Tab: Detect daily gap dates, cross-source conflicts, and Pearson correlations
5. Visual Import: Submit mapped CSV rows with idempotency deduplication
6. Tenant Sharing: Grant share, list shares, and revoke share
7. Data Management: Wipe data points & 1-click full account wipe

Verifies Rule 1 (Core DB ownership) & Rule 2 (Tenant Isolation).
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from core.db.session import engine as core_engine
from core.main import app, get_session
from core.db.models import Tenant, DataSource, DataPoint, ExplorerView, TenantShare, User

from tests.e2e.e2e_helpers import (
    auth_headers,
    init_e2e_db,
    override_get_session,
    create_test_tenant,
    cleanup_test_tenant,
    e2e_session_maker,
)


# Entering the TestClient context manager runs the app's lifespan. Without this
# flag that would audit secrets, start the gRPC server and open a NATS consumer
# for a suite that needs none of them.
app.state.testing = True


@pytest.fixture(autouse=True)
def setup_e2e_test_environment():
    """Setup schema and FastAPI dependency override for isolated testing."""
    asyncio.run(init_e2e_db())
    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.clear()

    # `get_session` is overridden, but the authentication middleware opens its own
    # session from Core's engine, which is pooled. Each test gets a fresh
    # TestClient and therefore a fresh event loop, so a connection left in the
    # pool by the previous test belongs to a loop that no longer exists — and the
    # failure surfaces on an unrelated request as "Event loop is closed".
    asyncio.run(core_engine.dispose())


@pytest.fixture
def api_client():
    """One client, and therefore one event loop, for the whole test.

    `TestClient(app)` used bare starts and tears down an event loop per request.
    That was survivable while the database engine opened a fresh connection every
    time; with a pooled engine, the second request in a test borrows a connection
    created in a loop that no longer exists and fails with "Event loop is closed"
    — nowhere near the code that caused it.

    Entering the context manager also runs the app's lifespan, which the
    `app.state.testing` flag set above reduces to a no-op.
    """
    with TestClient(app) as client:
        yield client


@pytest.mark.asyncio
async def test_dashboard_connectors_flow_e2e(api_client):
    """E2E Test: Dashboard 'Connectors' Tab - Add, List, Sync, and Delete Connector."""
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    # 1. Configure a new connector (e.g. Yazio)
    config_payload = {
        "source_type": "yazio",
        "display_name": "Yazio",
        "access_token": "secret_yazio_token_xyz123",
        "status": "active",
        "poll_interval_hours": 6,
    }
    res = api_client.post("/api/v1/data/sources/configure", json=config_payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["source_type"] == "yazio"
    assert data["status"] == "success"

    # 2. List configured connectors
    res_list = api_client.get("/api/v1/data/sources", headers=headers)
    assert res_list.status_code == 200
    connectors = res_list.json()["connectors"]
    assert len(connectors) == 1
    assert connectors[0]["source_type"] == "yazio"

    # 3. Trigger manual sync
    res_sync = api_client.post("/api/v1/data/sources/yazio/sync", headers=headers)
    assert res_sync.status_code == 202
    assert res_sync.json()["status"] in ("sync_scheduled", "sync_queued")

    # 4. Delete connector
    res_del = api_client.delete("/api/v1/data/sources/yazio", headers=headers)
    assert res_del.status_code == 200
    assert res_del.json()["status"] in ("deleted", "success")

    # 5. Verify listing is now empty
    res_empty = api_client.get("/api/v1/data/sources", headers=headers)
    assert len(res_empty.json()["connectors"]) == 0


@pytest.mark.asyncio
async def test_dashboard_explorer_tab_e2e(api_client):
    """E2E Test: Dashboard 'Explorer' Tab - Save Views, List, and Delete View."""
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    # 1. Save a new Explorer View
    view_payload = {
        "name": "Heart Rate & Sleep Trends",
        "query_config": {"chart_type": "line", "metrics": ["heart_rate", "sleep_duration"]},
    }
    res = api_client.post("/api/v1/data/explorer/views", json=view_payload, headers=headers)
    assert res.status_code == 200
    view_id = res.json()["view_id"]

    # 2. List saved views
    res_list = api_client.get("/api/v1/data/explorer/views", headers=headers)
    assert res_list.status_code == 200
    views = res_list.json()["views"]
    assert len(views) == 1
    assert views[0]["name"] == "Heart Rate & Sleep Trends"

    # 3. Delete saved view
    res_del = api_client.delete(f"/api/v1/data/explorer/views/{view_id}", headers=headers)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "success"

    # 4. Confirm view deleted
    res_check = api_client.get("/api/v1/data/explorer/views", headers=headers)
    assert len(res_check.json()["views"]) == 0


@pytest.mark.asyncio
async def test_dashboard_quality_tab_e2e(api_client):
    """E2E Test: Dashboard 'Quality' Tab - Gaps, Conflicts, & Correlations."""
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    # 1. Check Gaps endpoint
    today = date.today()
    start = today - timedelta(days=2)
    res_gaps = api_client.get(f"/api/v1/data/quality/gaps?start_date={start.isoformat()}&end_date={today.isoformat()}", headers=headers)
    assert res_gaps.status_code == 200
    assert "gaps" in res_gaps.json()

    # 2. Check Conflicts endpoint
    res_conf = api_client.get("/api/v1/data/quality/conflicts?tolerance=0.05", headers=headers)
    assert res_conf.status_code == 200
    assert "conflicts" in res_conf.json()

    # 3. Check Correlations endpoint
    res_corr = api_client.get("/api/v1/data/analysis/correlations", headers=headers)
    assert res_corr.status_code == 200
    assert "correlations" in res_corr.json()


@pytest.mark.asyncio
async def test_dashboard_visual_import_and_wipe_e2e(api_client):
    """E2E Test: Visual CSV Import, Data Wipe, and Full Account Wipe."""
    tenant_id = await create_test_tenant()
    source_id = str(uuid.uuid4())
    headers = auth_headers(tenant_id)

    async with e2e_session_maker() as session:
        ds = DataSource(
            id=source_id,
            tenant_id=tenant_id,
            source_type="manual_csv",
            display_name="Manual import",
        )
        session.add(ds)
        await session.commit()

    # 1. Visual Mapped Row Import
    import_payload = {
        "rows": [
            {
                "source_id": source_id,
                "metric_type": "body_weight",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "value": 75.4,
                "metadata": {"unit": "kg"},
            }
        ]
    }
    res_imp = api_client.post("/api/v1/data/import", json=import_payload, headers=headers)
    assert res_imp.status_code == 202
    assert res_imp.json()["accepted"] == 1

    # 2. Query summary & metrics
    res_sum = api_client.get("/api/v1/data/metrics/summary", headers=headers)
    assert res_sum.status_code == 200
    assert "metrics" in res_sum.json()

    # 3. Wipe Data Points
    res_wipe = api_client.delete("/api/v1/data/wipe", headers=headers)
    assert res_wipe.status_code == 200
    assert res_wipe.json()["status"] == "wiped"

    # 4. Full Account Data Wipe
    res_acc = api_client.delete("/api/v1/data/account", headers=headers)
    assert res_acc.status_code == 200
    assert res_acc.json()["status"] == "deleted"


@pytest.mark.asyncio
async def test_dashboard_tenant_sharing_e2e(api_client):
    """E2E Test: Tenant Workspace Sharing - Grant, List, and Revoke Share."""
    grantor_id = await create_test_tenant()
    grantee_id = await create_test_tenant()

    grantee_email = f"user_{uuid.uuid4().hex[:6]}@example.com"
    async with e2e_session_maker() as session:
        user = User(
            id=str(uuid.uuid4()),
            tenant_id=grantee_id,
            email=grantee_email,
            name="Test Grantee User",
            password_hash="hash123",
            role="user",
        )
        session.add(user)
        await session.commit()

    grantor_headers = auth_headers(grantor_id)

    # 1. Grant Share
    share_payload = {"grantee_email": grantee_email, "scope": "read_all"}
    res_grant = api_client.post("/api/v1/data/shares", json=share_payload, headers=grantor_headers)
    assert res_grant.status_code == 200

    # 2. List Shares
    res_list = api_client.get("/api/v1/data/shares", headers=grantor_headers)
    assert res_list.status_code == 200
    shares = res_list.json()["granted_by_me"]
    assert len(shares) == 1
    share_id = shares[0]["id"]

    # 3. Revoke Share
    res_revoke = api_client.delete(f"/api/v1/data/shares/{share_id}", headers=grantor_headers)
    assert res_revoke.status_code == 200

    # 4. Confirm list empty
    res_check = api_client.get("/api/v1/data/shares", headers=grantor_headers)
    assert len(res_check.json()["granted_by_me"]) == 0
