"""Integration/unit tests for Apple Health Importer FastAPI ingestion service.

The webhook authenticates by resolving the presented API key to a tenant. These
tests exercise that contract end to end with the resolver stubbed at the HTTP
boundary, so the fail-open regression cannot come back unnoticed.

Maps to Fizzbee Invariants:
- WebhookMappedToCorrectTenant
- UnauthenticatedWebhookRejected
"""

import hashlib
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from apple_health_importer.auth import ApiKeyIdentity, extract_presented_key
from apple_health_importer.main import app
from fastapi.testclient import TestClient

app.state.testing = True
client = TestClient(app)

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"
VALID_KEY = "qsk_valid_test_key_for_tenant_a"

SAMPLE_PAYLOAD = {
    "data": {
        "metrics": [
            {
                "name": "step_count",
                "units": "count",
                "data": [{"qty": 500, "date": "2026-08-03T10:00:00Z"}],
            }
        ]
    }
}


def _identity(tenant_id: str = TENANT_A) -> ApiKeyIdentity:
    return ApiKeyIdentity(
        tenant_id=tenant_id, source_id="apple_health_src_123", key_prefix="qsk_valid"
    )


def test_health_check_endpoint():
    """Verifies GET /health endpoint response."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "qs-importer-apple-health"


@patch("apple_health_importer.main.resolve_api_key", new_callable=AsyncMock)
def test_ingest_with_valid_key(mock_resolve):
    """A recognised key ingests into the tenant the key belongs to."""
    mock_resolve.return_value = _identity()

    response = client.post(
        "/ingest",
        json=SAMPLE_PAYLOAD,
        headers={"Authorization": f"Bearer {VALID_KEY}", "X-Request-ID": "test_req_001"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    # Tenant comes from the key, never from a header.
    assert data["tenant_id"] == TENANT_A
    assert data["total_transformed"] == 1


@patch("apple_health_importer.main.resolve_api_key", new_callable=AsyncMock)
def test_ingest_accepts_legacy_api_key_header(mock_resolve):
    """Existing Health Auto Export configs send X-Api-Key; that must keep working."""
    mock_resolve.return_value = _identity()

    response = client.post(
        "/ingest", json=SAMPLE_PAYLOAD, headers={"X-Api-Key": VALID_KEY}
    )

    assert response.status_code == 200
    assert mock_resolve.await_args.args[0] == VALID_KEY


def test_ingest_without_any_key_is_rejected():
    """No key means no ingest — this is the fail-open regression guard.

    Previously, a tenant with no configured connector made ``expected_key`` falsy
    and the whole check was skipped, so an anonymous POST was accepted.
    """
    response = client.post("/ingest", json=SAMPLE_PAYLOAD)
    assert response.status_code == 401


def test_ingest_with_tenant_header_but_no_key_is_rejected():
    """Naming a tenant must not be a substitute for proving you own it."""
    response = client.post(
        "/ingest", json=SAMPLE_PAYLOAD, headers={"X-Tenant-ID": TENANT_A}
    )
    assert response.status_code == 401


@patch("apple_health_importer.main.resolve_api_key", new_callable=AsyncMock)
def test_ingest_rejects_contradicting_tenant_header(mock_resolve):
    """A key for tenant A plus a header naming tenant B is a 403, not a silent fix."""
    mock_resolve.return_value = _identity(TENANT_A)

    response = client.post(
        "/ingest",
        json=SAMPLE_PAYLOAD,
        headers={"Authorization": f"Bearer {VALID_KEY}", "X-Tenant-ID": TENANT_B},
    )

    assert response.status_code == 403


@patch("apple_health_importer.main.resolve_api_key", new_callable=AsyncMock)
def test_ingest_rejects_unknown_key(mock_resolve):
    """An unresolvable key is a 401 from the resolver, propagated unchanged."""
    from fastapi import HTTPException

    mock_resolve.side_effect = HTTPException(status_code=401, detail="Invalid API key.")

    response = client.post(
        "/ingest", json=SAMPLE_PAYLOAD, headers={"X-Api-Key": "qsk_not_a_real_key"}
    )
    assert response.status_code == 401


def test_extract_presented_key_prefers_bearer():
    """Authorization is the documented form; X-Api-Key is the legacy fallback."""
    assert extract_presented_key("Bearer abc", "xyz") == "abc"
    assert extract_presented_key("bearer abc", None) == "abc"
    assert extract_presented_key(None, "xyz") == "xyz"
    assert extract_presented_key("Bearer   ", "xyz") == "xyz"
    assert extract_presented_key(None, None) is None
    assert extract_presented_key("Basic abc", None) is None


@pytest.mark.asyncio
async def test_resolver_sends_only_the_hash_never_the_key():
    """The raw key must not leave this service.

    Verifies Fizzbee Invariant: NeverExposePlaintextSecretsInBroker
    """
    from apple_health_importer import auth as auth_module

    captured: dict = {}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "tenant_id": TENANT_A,
                "source_id": "src-1",
                "key_prefix": "qsk_valid",
            }

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
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
    from apple_health_importer import auth as auth_module
    from fastapi import HTTPException

    class _ExplodingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **kw):
            raise httpx.ConnectError("core is down")

    with patch.object(httpx, "AsyncClient", lambda **kw: _ExplodingClient()):
        with pytest.raises(HTTPException) as excinfo:
            await auth_module.resolve_api_key(VALID_KEY, req_id="req_test")

    assert excinfo.value.status_code == 503
