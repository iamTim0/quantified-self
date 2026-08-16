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
    role: str = "owner",
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
        "role": role,
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
async def test_gateway_health_reports_observed_metadata(monkeypatch):
    """Verifies Fizzbee Invariant: VersionComesFromObservedService."""
    from gateway import main as gateway_main
    from gateway.metadata import RELEASE_SERVICES

    monkeypatch.setenv("QS_SERVICE_VERSION", "test-release")
    monkeypatch.setenv("QS_SOURCE_COMMIT", "test-commit")

    services = [
        {
            "service": service,
            "status": "expected" if service == "core-migrate" else "ok",
            "observed": service != "core-migrate",
            "version": "test-release",
            "commit": "test-commit",
        }
        for service in RELEASE_SERVICES
    ]

    async def observed_health():
        return services

    monkeypatch.setattr(gateway_main, "_observe_service_health", observed_health)
    transport = ASGITransport(app=gateway_main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "qs-api-gateway"
    assert payload["version"] == "test-release"
    assert payload["commit"] == "test-commit"
    assert payload["expected_release"] == {
        "version": "test-release",
        "commit": "test-commit",
    }
    assert {entry["service"] for entry in payload["services"]} == set(RELEASE_SERVICES)
    assert all(
        entry["version"] == "test-release" and entry["commit"] == "test-commit"
        for entry in payload["services"]
    )
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_gateway_observer_matches_the_release_manifest(monkeypatch):
    """Verifies Fizzbee Invariant: VersionComesFromObservedService."""
    from gateway import main as gateway_main
    from gateway.metadata import RELEASE_SERVICES

    monkeypatch.setenv("QS_SERVICE_VERSION", "gateway-release")
    monkeypatch.setenv("QS_SOURCE_COMMIT", "gateway-commit")

    async def observed_probe(_client, target):
        result = {
            "service": target.service,
            "status": "ok",
            "observed": True,
            "version": f"{target.service}-release",
            "commit": f"{target.service}-commit",
        }
        if target.role is not None:
            result["role"] = target.role
        return result

    monkeypatch.setattr(gateway_main, "_probe_health", observed_probe)

    services = await gateway_main._observe_service_health()

    assert [entry["service"] for entry in services] == list(RELEASE_SERVICES)
    by_name = {entry["service"]: entry for entry in services}
    assert by_name["api-gateway"] == {
        "service": "api-gateway",
        "status": "ok",
        "observed": True,
        "version": "gateway-release",
        "commit": "gateway-commit",
    }
    assert by_name["core-migrate"]["status"] == "expected"
    assert by_name["core-migrate"]["observed"] is False
    assert by_name["core"]["role"] == "api"


@pytest.mark.asyncio
async def test_gateway_probe_preserves_exact_service_metadata(monkeypatch):
    """Verifies Fizzbee Invariant: VersionComesFromObservedService."""
    from gateway import main as gateway_main
    from gateway.metadata import HealthTarget

    monkeypatch.setattr(gateway_main.settings, "CORE_SERVICE_URL", "http://core:8001")

    class FakeClient:
        async def get(self, url, *, timeout):
            assert url == "http://core:8001/health"
            assert timeout == gateway_main.HEALTH_PROBE_TIMEOUT_SECONDS
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "service": "qs-core-service",
                    "version": "0.3.0",
                    "commit": "abc123",
                },
            )

    result = await gateway_main._probe_health(
        FakeClient(), HealthTarget("core", "CORE_SERVICE_URL")
    )

    assert result == {
        "service": "core",
        "status": "ok",
        "observed": True,
        "version": "0.3.0",
        "commit": "abc123",
    }


@pytest.mark.asyncio
async def test_gateway_health_exposes_an_unavailable_dependency(monkeypatch):
    """Verifies Fizzbee Invariant: UnhealthyDependencyIsVisible."""
    from gateway import main as gateway_main
    from gateway.metadata import RELEASE_SERVICES

    services = [
        {
            "service": service,
            "status": "expected" if service == "core-migrate" else "ok",
            "observed": service != "core-migrate",
            "version": "test-release",
            "commit": "test-commit",
        }
        for service in RELEASE_SERVICES
    ]
    services[1] = {
        "service": "core",
        "status": "unavailable",
        "observed": False,
        "version": None,
        "commit": None,
        "error_code": "health_unreachable",
        "role": "api",
    }

    async def observed_health():
        return services

    monkeypatch.setattr(gateway_main, "_observe_service_health", observed_health)
    transport = ASGITransport(app=gateway_main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["services"][1]["error_code"] == "health_unreachable"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_gateway_liveness_does_not_probe_dependencies():
    """Verifies Fizzbee Invariant: LivenessDoesNotWaitForDependencies."""
    from gateway.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        response = await ac.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["cache-control"] == "no-store"


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
async def test_ingestion_reset_uses_core_ingest_and_preserves_security_headers(monkeypatch):
    """Verifies Fizzbee Invariants: OwnerOnlyReset and RequestCorrelationTracing."""
    from gateway import main as gateway_main

    monkeypatch.setattr(gateway_main.settings, "CORE_INGEST_URL", "http://core-ingest:8001")
    token = _make_token()
    observed: dict[str, str] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        observed.update(
            {
                "url": str(request.url),
                "authorization": request.headers.get("authorization", ""),
                "cookie": request.headers.get("cookie", ""),
                "csrf": request.headers.get("x-csrf-token", ""),
                "tenant": request.headers.get("x-tenant-id", ""),
                "request_id": request.headers.get("x-request-id", ""),
            }
        )
        return httpx.Response(
            409,
            json={
                "code": "ingestion_reset_pending_events",
                "detail": "pending",
                "num_pending": 4,
                "num_ack_pending": 1,
            },
        )

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/v1/data/system/ingestion/reset",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Tenant-ID": "11111111-1111-1111-1111-111111111111",
                    "X-CSRF-Token": "csrf-value",
                    "X-Request-ID": "req_gateway_reset",
                },
                cookies={
                    "qs_access": "cookie-value",
                    "qs_csrf": "csrf-value",
                },
            )

    assert response.status_code == 409
    assert response.json()["code"] == "ingestion_reset_pending_events"
    assert response.json()["num_pending"] == 4
    assert observed == {
        "url": "http://core-ingest:8001/api/v1/data/system/ingestion/reset",
        "authorization": f"Bearer {token}",
        "cookie": "qs_access=cookie-value; qs_csrf=csrf-value",
        "csrf": "csrf-value",
        "tenant": "11111111-1111-1111-1111-111111111111",
        "request_id": "req_gateway_reset",
    }
    assert response.headers["x-request-id"] == "req_gateway_reset"


@pytest.mark.asyncio
async def test_ingestion_reset_is_owner_only_and_csrf_protected():
    """Verifies Fizzbee Invariants: OwnerOnlyReset and UnauthenticatedRequestsBlocked."""
    from gateway import main as gateway_main

    token = _make_token(role="member")
    transport = ASGITransport(app=gateway_main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        member = await client.post(
            "/api/v1/data/system/ingestion/reset",
            headers={"Authorization": f"Bearer {token}"},
        )

        cookie_token = _make_token()
        csrf = await client.post(
            "/api/v1/data/system/ingestion/reset",
            cookies={"qs_access": cookie_token, "qs_csrf": "cookie-csrf"},
            headers={"X-CSRF-Token": "wrong-csrf"},
        )

    assert member.status_code == 403
    assert member.json()["code"] == "owner_required"
    assert csrf.status_code == 403
    assert csrf.json()["code"] == "csrf_required"


def test_ingestion_reset_route_precedes_the_generic_core_proxy():
    """Verifies Fizzbee Invariant: SpecificRoutesPrecedeDashboard."""
    from gateway import main as gateway_main

    assert (
        _resolved_endpoint("/api/v1/data/system/ingestion/reset", "POST")
        is gateway_main.proxy_ingestion_reset
    )


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


@pytest.mark.asyncio
async def test_an_upload_reaches_the_importer_that_can_read_it():
    """The edge routes the file; the importer owns what its columns mean (rule 3)."""
    from gateway import main as gateway_main

    seen: dict[str, str] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["tenant"] = request.headers.get("X-Tenant-ID", "")
        seen["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(202, json={"status": "accepted", "sync_run_id": "run-1"})

    token = _make_token()
    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/import/whoop/upload",
                params={"source_id": "44444444-4444-4444-4444-444444444444"},
                content=b"PK\x03\x04 pretend archive",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 202, response.text
    assert seen["url"].endswith("/upload?source_id=44444444-4444-4444-4444-444444444444")
    assert "8007" in seen["url"]
    # The importer cannot validate a session itself -- Core keeps the signing key
    # away from it -- so the token has to travel, and the tenant with it.
    assert seen["tenant"] == "11111111-1111-1111-1111-111111111111"
    assert seen["authorization"] == f"Bearer {token}"


@pytest.mark.asyncio
async def test_an_upload_for_an_unknown_source_is_not_proxied_anywhere():
    """`/api/v1/import/{source}/upload` must not become a way to reach arbitrary hosts."""
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"nothing should have been proxied, got {request.url}")

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/import/oura/upload",
                params={"source_id": "44444444-4444-4444-4444-444444444444"},
                content=b"x",
                headers={"Authorization": f"Bearer {_make_token()}"},
            )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_cookie_upload_without_the_csrf_pair_is_refused():
    """A cookie rides along on a cross-site POST; the header it must match does not."""
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request without CSRF proof must not be proxied")

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/import/whoop/upload",
                params={"source_id": "44444444-4444-4444-4444-444444444444"},
                content=b"x",
                cookies={"qs_access": _make_token(), "qs_csrf": "a-token"},
            )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_cookie_upload_with_the_csrf_pair_goes_through():
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"status": "accepted"})

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/import/apple-health/upload",
                params={"source_id": "44444444-4444-4444-4444-444444444444"},
                content=b"x",
                cookies={"qs_access": _make_token(), "qs_csrf": "a-token"},
                headers={"X-CSRF-Token": "a-token"},
            )

    assert response.status_code == 202


@pytest.mark.asyncio
async def test_every_step_of_a_chunked_upload_reaches_the_importer():
    """A large archive arrives in parts, and each step is proxied to the same service.

    The parts exist because the hops in front of this Gateway refuse a body of the size
    an export reaches — Cloudflare answers 413 at the edge past 100 MB — so this route
    carries `begin`, `chunk` and `complete` as well as the whole file.
    """
    from gateway import main as gateway_main

    seen: list[str] = []

    async def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"received": 1})

    token = _make_token()
    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            for step, params in (
                ("begin", {"source_id": "44444444-4444-4444-4444-444444444444"}),
                ("chunk", {"upload_id": "u-1", "offset": "0"}),
                ("complete", {"upload_id": "u-1"}),
                ("abort", {"upload_id": "u-1"}),
            ):
                response = await ac.post(
                    f"/api/v1/import/apple-health/upload/{step}",
                    params=params,
                    content=b"part",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 200, response.text

    assert [url.split("?")[0].rsplit("/", 2)[-2:] for url in seen] == [
        ["upload", "begin"],
        ["upload", "chunk"],
        ["upload", "complete"],
        ["upload", "abort"],
    ]
    assert all("8005" in url for url in seen)


@pytest.mark.asyncio
async def test_an_invented_upload_step_is_not_proxied_anywhere():
    """The path segment ends up in a URL, so what it may spell is decided here."""
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"nothing should have been proxied, got {request.url}")

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/import/apple-health/upload/token",
                params={"upload_id": "u-1"},
                content=b"x",
                headers={"Authorization": f"Bearer {_make_token()}"},
            )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_chunk_without_the_csrf_pair_is_refused():
    """Every step is a write, so every step needs the proof the whole upload needs."""
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a request without CSRF proof must not be proxied")

    transport = ASGITransport(app=gateway_main.app)
    with _upstreams(upstream):
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/import/apple-health/upload/chunk",
                params={"upload_id": "u-1", "offset": "0"},
                content=b"part",
                cookies={"qs_access": _make_token(), "qs_csrf": "a-token"},
            )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_chat_turn_streams_with_verified_tenant_and_request_id():
    """Verifies Fizzbee Invariants: ChatRequiresValidPlatformSession, ChatRequestIdReachesCore"""
    from gateway import main as gateway_main

    seen: dict[str, str] = {}

    async def upstream(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["tenant"] = request.headers.get("X-Tenant-ID", "")
        seen["authorization"] = request.headers.get("Authorization", "")
        seen["request_id"] = request.headers.get("X-Request-ID", "")
        return httpx.Response(
            200,
            headers={"content-type": "application/x-ndjson"},
            content=_emit(
                [
                    b'{"type":"delta","delta":"one"}\n',
                    b'{"type":"done"}\n',
                ]
            ),
        )

    token = _make_token()
    with _upstreams(upstream):
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/chat/turn",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": "req_chat_gateway",
                },
                json={"message": "Analyse my sleep"},
            )

    assert response.status_code == 200
    assert response.text.endswith('{"type":"done"}\n')
    assert seen["url"].endswith("/api/v1/chat/turn")
    assert seen["tenant"] == "11111111-1111-1111-1111-111111111111"
    assert seen["authorization"] == f"Bearer {token}"
    assert seen["request_id"] == "req_chat_gateway"


@pytest.mark.asyncio
async def test_cookie_chat_post_requires_csrf_pair():
    """Verifies Fizzbee Invariant: ChatRequiresValidPlatformSession"""
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a chat request without CSRF proof must not be proxied")

    with _upstreams(upstream):
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/chat/login",
                cookies={"qs_access": _make_token(), "qs_csrf": "csrf-token"},
            )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unknown_chat_operation_is_not_proxied():
    from gateway import main as gateway_main

    async def upstream(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"nothing should have been proxied, got {request.url}")

    with _upstreams(upstream):
        async with AsyncClient(
            transport=ASGITransport(app=gateway_main.app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/api/v1/chat/arbitrary",
                headers={"Authorization": f"Bearer {_make_token()}"},
            )
    assert response.status_code == 404
