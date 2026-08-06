"""Unit tests for Core Data Service Tenant Context and Async Scope.

Verifies the Fizzbee TenantIsolation invariant in Python application code.
"""

import asyncio

import pytest
from core.db.tenant import (
    _current_tenant_id,
    get_current_tenant_id,
    set_current_tenant_id,
)


def test_tenant_context_default_raises_runtime_error():
    """Verify that accessing tenant_id without setting it raises RuntimeError.
    
    Fizzbee Invariant: TenantIsolation
    """
    token = _current_tenant_id.set(None)
    try:
        with pytest.raises(RuntimeError, match="tenant_id not set in context"):
            get_current_tenant_id()
    finally:
        _current_tenant_id.reset(token)

def test_tenant_context_set_and_get():
    """Verify contextvar set and get behavior within same coroutine scope."""
    token = _current_tenant_id.set("tenant-uuid-1234")
    try:
        assert get_current_tenant_id() == "tenant-uuid-1234"
    finally:
        _current_tenant_id.reset(token)

@pytest.mark.asyncio
async def test_tenant_context_async_concurrency_isolation():
    """Verify that concurrent async tasks maintain isolated tenant_ids.
    
    Fizzbee Invariant: TenantIsolation (under concurrent request load)
    """
    results = {}

    async def worker(tenant_id: str, delay: float):
        set_current_tenant_id(tenant_id)
        await asyncio.sleep(delay)
        # Verify tenant_id remained untouched by other concurrent tasks
        results[tenant_id] = get_current_tenant_id()

    await asyncio.gather(
        worker("tenant-A", 0.05),
        worker("tenant-B", 0.02),
        worker("tenant-C", 0.01),
    )

    assert results["tenant-A"] == "tenant-A"
    assert results["tenant-B"] == "tenant-B"
    assert results["tenant-C"] == "tenant-C"

async def _dispatch(path: str, headers: list[tuple[bytes, bytes]]):
    """Run AuthenticationMiddleware over a synthetic request and return the response."""
    from starlette.requests import Request
    from starlette.responses import Response

    from core.security.auth import AuthenticationMiddleware

    async def call_next(_request: Request) -> Response:
        return Response("ok")

    scope = {"type": "http", "method": "GET", "path": path, "headers": headers}
    request = Request(scope, receive=lambda: None)
    middleware = AuthenticationMiddleware(app=call_next)
    return await middleware.dispatch(request, call_next)


@pytest.mark.asyncio
async def test_auth_middleware_rejects_missing_credential():
    """Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked."""
    response = await _dispatch("/api/v1/data/metrics", [])
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_rejects_bare_tenant_header():
    """A bare X-Tenant-ID must never authenticate anybody.

    This is the regression guard for the defect where Core derived the tenant from
    an unauthenticated header and verified nothing.

    Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked
    """
    response = await _dispatch(
        "/api/v1/data/metrics",
        [(b"x-tenant-id", b"11111111-1111-1111-1111-111111111111")],
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_middleware_rejects_tenant_header_mismatch():
    """A header may agree with the token, never override it.

    Verifies Fizzbee Invariant: TenantIdAlwaysPresent
    """
    from core.security.tokens import create_access_token

    token, _jti, _exp = create_access_token(
        user_id="22222222-2222-2222-2222-222222222222",
        tenant_id="11111111-1111-1111-1111-111111111111",
        email="user@example.test",
        role="owner",
    )
    response = await _dispatch(
        "/api/v1/data/metrics",
        [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-tenant-id", b"99999999-9999-9999-9999-999999999999"),
        ],
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_user_token_rejected_on_internal_path():
    """A user token must not reach internal service endpoints.

    Verifies Fizzbee Invariant: ServiceTokenScopedToInternalPaths
    """
    from core.security.tokens import create_access_token

    token, _jti, _exp = create_access_token(
        user_id="22222222-2222-2222-2222-222222222222",
        tenant_id="11111111-1111-1111-1111-111111111111",
        email="user@example.test",
        role="owner",
    )
    response = await _dispatch(
        "/api/v1/internal/data/sources/oura/token",
        [
            (b"authorization", f"Bearer {token}".encode()),
            (b"x-tenant-id", b"11111111-1111-1111-1111-111111111111"),
        ],
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_service_token_rejected_on_user_path():
    """A service credential must not stand in for a user session.

    Verifies Fizzbee Invariant: ServiceTokenScopedToInternalPaths
    """
    from core.security.tokens import create_service_token

    response = await _dispatch(
        "/api/v1/data/metrics",
        [(b"authorization", f"Bearer {create_service_token()}".encode())],
    )
    assert response.status_code == 401
