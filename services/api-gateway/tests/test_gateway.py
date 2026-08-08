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


async def _emit(parts):
    """Yield the chunks one at a time, as a real upstream would."""
    for part in parts:
        yield part


@pytest.mark.asyncio
async def test_the_ui_proxy_streams_the_whole_body_through():
    """The response must arrive complete, and not before the upstream finishes.

    The proxy used to read the entire upstream response before sending any of it,
    which defeats streaming SSR and holds every response in memory in full.

    The trap in the streaming version is lifetime. The `httpx.AsyncClient` now has
    to outlive the handler that created it, because the body is still being pulled
    through it while Starlette writes to the socket. Closing it on the way out --
    which `async with` would do -- truncates every response to whatever had
    already arrived. A short body would very likely survive that, so this sends
    enough chunks to fail if the connection is dropped early.
    """
    import httpx
    from gateway import main as gateway_main

    chunks = [f"chunk-{i:04d}:".encode() + b"x" * 4096 for i in range(64)]
    expected = b"".join(chunks)

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=_emit(chunks),
        )

    transport = httpx.MockTransport(upstream)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    gateway_main.httpx.AsyncClient = patched
    try:
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as ac:
            response = await ac.get("/some/page")
    finally:
        gateway_main.httpx.AsyncClient = original

    assert response.status_code == 200
    assert response.content == expected
    # Rewritten by the proxy: the bytes it forwards are decoded, so the upstream's
    # own framing headers no longer describe them.
    assert "content-encoding" not in {k.lower() for k in response.headers}


@pytest.mark.asyncio
async def test_the_ui_proxy_stops_paying_for_a_base_that_does_not_answer(monkeypatch):
    """A base that fails must cost one attempt in total, not one per request.

    The proxy tries several addresses because the dashboard sits at a different
    one in each environment. It used to rebuild that list per request and always
    start at the top, so outside a container every single proxied request first
    spent a DNS failure on the container name and then the full 10s connect
    timeout on `host.docker.internal`, where nothing listens. Measured: 12.7s
    added to each request, for a page the dev server renders in 50ms.

    Also pins the order: loopback is attempted before `host.docker.internal`,
    because outside a container loopback is the answer and inside one it is
    refused immediately rather than stalling.
    """
    import httpx
    from gateway import main as gateway_main

    attempted: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.host)
        if request.url.host != "127.0.0.1":
            raise httpx.ConnectError("no route to host", request=request)
        return httpx.Response(200, content=b"ok")

    transport = httpx.MockTransport(upstream)
    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    # The container-name-first case, which is what a Compose deployment has.
    monkeypatch.setattr(gateway_main.settings, "DASHBOARD_URL", "http://dashboard:3000")
    monkeypatch.setattr(gateway_main, "_ui_base", None)
    gateway_main.httpx.AsyncClient = patched
    try:
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as ac:
            first = await ac.get("/")
            after_first = list(attempted)
            second = await ac.get("/")
    finally:
        gateway_main.httpx.AsyncClient = original

    assert first.status_code == 200
    assert second.status_code == 200
    assert after_first == ["dashboard", "127.0.0.1"]
    assert attempted[len(after_first):] == ["127.0.0.1"]


@pytest.mark.asyncio
async def test_the_gateway_refuses_to_start_in_production_with_a_published_secret(
    monkeypatch,
):
    """The deployment compose file used to default JWT_SECRET to a value printed
    in this repository, so forgetting to set it did not fail -- it silently
    verified real sessions against a public string."""
    from gateway import main as gateway_main
    from gateway.config import settings

    monkeypatch.setattr(
        settings, "JWT_SECRET", "dev-secret-key-quantified-self-2026", raising=False
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        gateway_main.audit_secrets()


@pytest.mark.asyncio
async def test_a_development_gateway_warns_instead(monkeypatch, caplog):
    """A laptop and CI must keep working, or the check gets deleted."""
    import logging

    from gateway import main as gateway_main
    from gateway.config import settings

    monkeypatch.setattr(
        settings, "JWT_SECRET", "dev-secret-key-quantified-self-2026", raising=False
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "dev", raising=False)

    with caplog.at_level(logging.WARNING):
        gateway_main.audit_secrets()
    assert any("JWT_SECRET" in r.getMessage() for r in caplog.records)
