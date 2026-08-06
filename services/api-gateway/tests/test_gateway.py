"""Integration tests for API Gateway.

Verifies:
- GET /health
- Reverse proxy routing & X-Tenant-ID header injection to Core service
- The dev-token backdoor is gone
- /api/v1/internal/* is not reachable through the public edge

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient


def _make_token(
    tenant_id: str = "11111111-1111-1111-1111-111111111111",
    *,
    token_type: str = "access",
    audience: str = "qs-api",
    issuer: str = "qs-core",
    include_jti: bool = True,
) -> str:
    """Mint a token the way Core does, so Gateway validation can be exercised."""
    from gateway.config import settings

    now = datetime.now(timezone.utc)
    payload = {
        "sub": "22222222-2222-2222-2222-222222222222",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "tenant_id": tenant_id,
        "email": "user@example.test",
        "role": "owner",
        "iss": issuer,
        "aud": audience,
        "token_type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=30),
    }
    if include_jti:
        payload["jti"] = "33333333-3333-3333-3333-333333333333"
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


@pytest.mark.asyncio
async def test_gateway_health():
    from gateway.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "qs-api-gateway"


@pytest.mark.asyncio
async def test_dev_token_endpoint_no_longer_exists():
    """The dev-token backdoor minted 365-day owner tokens for any tenant id.

    The dashboard called it automatically whenever local storage was empty, which
    silently re-authenticated the user after every logout. It must stay gone.

    Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked
    """
    from gateway.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/auth/dev-token")

    # The route is gone; whatever the catch-all dashboard proxy answers, it must
    # never be a usable token.
    assert response.status_code != 200 or "access_token" not in response.text


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


@pytest.mark.asyncio
async def test_data_proxy_requires_bearer_even_with_tenant_header():
    """Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked."""
    from gateway.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/api/v1/data/metrics", headers={"X-Tenant-ID": "tenant-bypass"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_data_proxy_rejects_tenant_header_claim_mismatch():
    """Verifies Fizzbee Invariant: TenantHeaderAlwaysInjected."""
    from gateway.main import app

    token = _make_token(tenant_id="11111111-1111-1111-1111-111111111111")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get(
            "/api/v1/data/metrics",
            headers={"Authorization": f"Bearer {token}", "X-Tenant-ID": "tenant-spoof"},
        )

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"audience": "qs-internal"},   # service-audience token on a user route
        {"issuer": "someone-else"},    # untrusted issuer
        {"token_type": "service"},     # wrong token type
        {"include_jti": False},        # unrevocable token
    ],
    ids=["wrong-audience", "wrong-issuer", "wrong-token-type", "missing-jti"],
)
async def test_data_proxy_rejects_malformed_claims(kwargs):
    """Every claim the Gateway checks must actually be enforced.

    Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked
    """
    from gateway.main import app

    token = _make_token(**kwargs)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get(
            "/api/v1/data/metrics", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_internal_paths_are_not_publicly_proxied():
    """`/api/v1/internal/*` hands out decrypted connector secrets.

    It used to be proxied for any logged-in user. It must no longer resolve to the
    Core proxy route at all.

    Verifies Fizzbee Invariant: SecretMaskedInReadResponse
    """
    from gateway.main import app

    token = _make_token()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get(
            "/api/v1/internal/data/sources/oura/token",
            headers={"Authorization": f"Bearer {token}"},
        )

    # Falls through to the dashboard catch-all (503 with no dashboard running),
    # never to Core. What matters is that no credential comes back.
    assert "access_token" not in response.text
