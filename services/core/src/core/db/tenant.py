"""Tenant context management for multi-tenant query isolation.

Uses Python's contextvars for async-safe per-request tenant scoping.
This is the enforcement layer for the Fizzbee TenantIsolation invariant:
every query MUST be scoped to a tenant_id.
"""

from contextvars import ContextVar
from typing import ClassVar

from sqlalchemy import Select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Async-safe context variable — each concurrent request gets its own value
_current_tenant_id: ContextVar[str | None] = ContextVar(
    "current_tenant_id", default=None
)

def get_current_tenant_id() -> str:
    """Get the current tenant_id from the async context."""
    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        raise RuntimeError("tenant_id not set in context")
    return tenant_id

def set_current_tenant_id(tenant_id: str) -> None:
    """Set the tenant_id for the current async context."""
    _current_tenant_id.set(tenant_id)

class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from X-Tenant-ID header and bind to async context."""

    EXEMPT_PATHS: ClassVar[set[str]] = {"/health", "/healthz", "/readyz", "/docs", "/openapi.json"}

    async def dispatch(
        self, request: RequestResponseEndpoint, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        tenant_id = request.headers.get("X-Tenant-ID") or "00000000-0000-0000-0000-000000000001"
        token = _current_tenant_id.set(tenant_id)
        try:
            return await call_next(request)
        finally:
            _current_tenant_id.reset(token)

def apply_tenant_filter(stmt: Select, tenant_id_column) -> Select:
    """Apply WHERE tenant_id = :tid to a SQLAlchemy Select statement."""
    tenant_id = get_current_tenant_id()
    return stmt.where(tenant_id_column == tenant_id)
