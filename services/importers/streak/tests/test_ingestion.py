"""Integration/unit tests for Streak Importer FastAPI server.

The webhook authenticates by resolving the presented API key to a tenant. These
tests exercise that contract so the fail-open regression cannot come back unnoticed.

Maps to Fizzbee Invariants:
- WebhookMappedToCorrectTenant
- UnauthenticatedWebhookRejected
"""

import hashlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from streak_importer.auth import ApiKeyIdentity, extract_presented_key
from streak_importer.main import app

app.state.testing = True
client = TestClient(app)

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
VALID_KEY = "qsk_valid_test_key_for_tenant_a"

SAMPLE_PAYLOAD = {
    "workouts": [
        {
            "id": 1,
            "title": "Push",
            "createdAt": "2026-08-03T18:00:00Z",
            "sets": [
                {"id": 101, "weight": 60.0, "reps": 12, "createdAt": "2026-08-03T18:05:00Z"}
            ],
        }
    ]
}


def _identity(tenant_id: str = TENANT_A) -> ApiKeyIdentity:
    return ApiKeyIdentity(
        tenant_id=tenant_id, source_id="streak_src_123", key_prefix="qsk_valid"
    )


def test_health_check_endpoint():
    """Verifies GET /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "qs-importer-streak"


def test_head_and_get_ingest_server_checks():
    """HEAD/GET reachability probes stay unauthenticated — they expose no data."""
    head_res = client.head("/ingest")
    assert head_res.status_code == 200

    get_res = client.get("/ingest")
    assert get_res.status_code == 200
    assert get_res.json()["ok"] is True


@patch("streak_importer.main.resolve_api_key", new_callable=AsyncMock)
@patch("streak_importer.main.close_sync_run", new_callable=AsyncMock)
@patch("streak_importer.main.report_sync_progress", new_callable=AsyncMock)
@patch("streak_importer.main.open_sync_run", new_callable=AsyncMock)
def test_post_ingest_with_valid_key(mock_open, mock_progress, mock_close, mock_resolve):
    """A recognised key ingests into the tenant the key belongs to."""
    mock_resolve.return_value = _identity()
    mock_open.return_value = "run-1"

    response = client.post(
        "/ingest",
        json=SAMPLE_PAYLOAD,
        headers={"Authorization": f"Bearer {VALID_KEY}", "X-Request-ID": "test_req_001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["tenant_id"] == TENANT_A
    assert data["workoutCount"] == 1
    assert data["published_count"] > 0


@patch("streak_importer.main.resolve_api_key", new_callable=AsyncMock)
@patch("streak_importer.main.close_sync_run", new_callable=AsyncMock)
@patch("streak_importer.main.report_sync_progress", new_callable=AsyncMock)
@patch("streak_importer.main.open_sync_run", new_callable=AsyncMock)
def test_post_ingest_accepts_legacy_api_key_header(mock_open, mock_progress, mock_close, mock_resolve):
    """Existing Streak 2.0 configs send X-Api-Key; that must keep working."""
    mock_resolve.return_value = _identity()
    mock_open.return_value = "run-1"

    response = client.post(
        "/ingest", json=SAMPLE_PAYLOAD, headers={"X-Api-Key": VALID_KEY}
    )

    assert response.status_code == 200
    assert mock_resolve.await_args.args[0] == VALID_KEY


def test_post_ingest_without_any_key_is_rejected():
    """No key means no ingest — this is the fail-open regression guard."""
    response = client.post("/ingest", json=SAMPLE_PAYLOAD)
    assert response.status_code == 401


def test_post_ingest_with_tenant_header_but_no_key_is_rejected():
    """Naming a tenant must not be a substitute for proving you own it."""
    response = client.post(
        "/ingest", json=SAMPLE_PAYLOAD, headers={"X-Tenant-ID": TENANT_A}
    )
    assert response.status_code == 401


@patch("streak_importer.main.resolve_api_key", new_callable=AsyncMock)
def test_post_ingest_rejects_contradicting_tenant_header(mock_resolve):
    """A key for tenant A plus a header naming tenant B is a 403, not a silent fix."""
    mock_resolve.return_value = _identity(TENANT_A)

    response = client.post(
        "/ingest",
        json=SAMPLE_PAYLOAD,
        headers={"Authorization": f"Bearer {VALID_KEY}", "X-Tenant-ID": TENANT_B},
    )

    assert response.status_code == 403


def test_extract_presented_key_prefers_bearer():
    """Authorization is the documented form; X-Api-Key is the legacy fallback."""
    assert extract_presented_key("Bearer abc", "xyz") == "abc"
    assert extract_presented_key(None, "xyz") == "xyz"
    assert extract_presented_key(None, None) is None


@pytest.mark.asyncio
async def test_resolver_sends_only_the_hash_never_the_key():
    """The raw key must not leave this service.

    Verifies Fizzbee Invariant: NeverExposePlaintextSecretsInBroker
    """
    from streak_importer import auth as auth_module

    captured: dict = {}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"tenant_id": TENANT_A, "source_id": "src-1", "key_prefix": "qsk_valid"}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    with patch.object(httpx, "AsyncClient", lambda **kw: _FakeClient()):
        identity = await auth_module.resolve_api_key(VALID_KEY, req_id="req_test")

    assert identity.tenant_id == TENANT_A
    assert captured["json"]["key_hash"] == hashlib.sha256(VALID_KEY.encode()).hexdigest()
    assert VALID_KEY not in str(captured["json"])
    assert VALID_KEY not in str(captured["headers"])


@pytest.mark.asyncio
async def test_resolver_fails_closed_when_core_unreachable():
    """An unreachable authority must never mean "allow"."""
    from fastapi import HTTPException
    from streak_importer import auth as auth_module

    class _ExplodingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **kw):
            raise httpx.ConnectError("core is down")

    with (
        patch.object(httpx, "AsyncClient", lambda **kw: _ExplodingClient()),
        pytest.raises(HTTPException) as excinfo,
    ):
        await auth_module.resolve_api_key(VALID_KEY, req_id="req_test")

    assert excinfo.value.status_code == 503
