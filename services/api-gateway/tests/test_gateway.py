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

import contextlib
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.routing import Match


@contextlib.contextmanager
def _upstreams(handler):
    """Answer every upstream the Gateway talks to from memory.

    Any path an API route does not claim lands on the catch-all UI proxy, which
    tries three *real* addresses in turn. A test that lets it do that asserts on
    the machine it runs on: it pays a DNS failure for the container name plus a
    full connect timeout for ``host.docker.internal`` -- about 13s per request on
    Windows -- and it can hang outright, because the UI proxy deliberately has no
    read deadline, so a dev server that accepts the connection and then compiles
    holds the test open for as long as it likes. It also passes for the wrong
    reason whenever something *is* listening on port 3000.

    ``handler`` sees the requests to Core and Analysis too, since those handlers
    construct their clients from the same module attribute. That is the point:
    a test can assert which upstream was reached, not merely what came back.
    """
    from gateway import main as gateway_main

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def patched(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    remembered = gateway_main._ui_base
    gateway_main.httpx.AsyncClient = patched
    try:
        yield
    finally:
        gateway_main.httpx.AsyncClient = original
        # Which base answered is cached across requests on purpose; leaking a
        # mocked one into the next test is not.
        gateway_main._ui_base = remembered


def _resolved_endpoint(path: str, method: str = "GET"):
    """The handler the router would dispatch to, without sending anything.

    Which handler answers *is* the security property for the internal paths, and
    asking the router directly states it without depending on any upstream.
    """
    from gateway.main import app

    scope = {"type": "http", "path": path, "method": method, "headers": [], "root_path": ""}
    for route in app.routes:
        match, _ = route.matches(scope)
        if match is Match.FULL:
            return route.endpoint
    return None


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
    from gateway import main as gateway_main

    # The backdoor was a route the *Gateway* served itself, so that is what this
    # pins: the path must resolve to the ordinary auth proxy and to nothing
    # special. Re-adding a handler for it here would take this endpoint away from
    # `proxy_auth_service` and fail on the next line — which asserting only on the
    # response body would not, since the body depends on whatever Core answers.
    assert (
        _resolved_endpoint("/api/v1/auth/dev-token") is gateway_main.proxy_auth_service
    )

    # Core does not serve it either, so the upstream answers as the real one does.
    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get("/api/v1/auth/dev-token")

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
    Core proxy route at all -- so this asserts on the routing decision, and then on
    the answer with Core standing by to hand out a credential to anyone who asks.

    Verifies Fizzbee Invariant: SecretMaskedInReadResponse
    """
    from gateway import main as gateway_main

    internal = "/api/v1/internal/data/sources/oura/token"

    # The Core proxy claims `/api/v1/data/*` only; an internal path must fall
    # through to the UI catch-all instead. A route resolves to exactly one
    # endpoint, so naming the one that answers also rules Core out — and says
    # which handler it was when it fails.
    assert _resolved_endpoint(internal) is gateway_main.proxy_dashboard_ui
    # ...and the sibling path it must not be confused with still reaches Core.
    assert _resolved_endpoint("/api/v1/data/metrics") is gateway_main.proxy_core_service

    # The UI proxy is passed the same path, so the two upstreams are told apart by
    # where the request went, not by what it asked for.
    core = httpx.URL(gateway_main.settings.CORE_SERVICE_URL)
    reached: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        if (request.url.host, request.url.port) == (core.host, core.port):
            # Core answers this path with a decrypted token. If the Gateway ever
            # forwards here again, the assertion below fails on the real payload
            # rather than on a stand-in for it.
            return httpx.Response(200, json={"access_token": "plaintext-provider-secret"})
        return httpx.Response(404, text="not found")

    token = _make_token()
    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.get(internal, headers={"Authorization": f"Bearer {token}"})

    assert "access_token" not in response.text
    assert not any(httpx.URL(url).host == core.host and httpx.URL(url).port == core.port
                   for url in reached), reached


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
    from gateway import main as gateway_main

    chunks = [f"chunk-{i:04d}:".encode() + b"x" * 4096 for i in range(64)]
    expected = b"".join(chunks)

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=_emit(chunks),
        )

    with _upstreams(upstream):
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as ac:
            response = await ac.get("/some/page")

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
    from gateway import main as gateway_main

    attempted: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        attempted.append(request.url.host)
        if request.url.host != "127.0.0.1":
            raise httpx.ConnectError("no route to host", request=request)
        return httpx.Response(200, content=b"ok")

    # The container-name-first case, which is what a Compose deployment has.
    monkeypatch.setattr(gateway_main.settings, "DASHBOARD_URL", "http://dashboard:3000")
    monkeypatch.setattr(gateway_main, "_ui_base", None)
    with _upstreams(upstream):
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as ac:
            first = await ac.get("/")
            after_first = list(attempted)
            second = await ac.get("/")

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
