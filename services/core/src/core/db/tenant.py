"""Tenant context management for multi-tenant query isolation.

Uses Python's contextvars for async-safe per-request tenant scoping.
This is the enforcement layer for the Fizzbee TenantIsolation invariant:
every query MUST be scoped to a tenant_id.
"""

from contextvars import ContextVar
from typing import Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from sqlalchemy import Select

# Async-safe context variable — each concurrent request gets its own value
_current_tenant_id: ContextVar[Optional[str]] = ContextVar(
    "current_tenant_id", default=None
)


def get_current_tenant_id() -> str:
    """Get the current tenant_id from the async context.

    Raises:
        RuntimeError: If no tenant_id is set (programming error / missing middleware).
    """
    tenant_id = _current_tenant_id.get()
    if tenant_id is None:
        raise RuntimeError(
            "tenant_id not set in context. Ensure TenantMiddleware is active "
            "or tenant_id is explicitly set for background tasks."
        )
    return tenant_id


def set_current_tenant_id(tenant_id: str) -> None:
    """Set the tenant_id for the current async context.

    Use this for background tasks (e.g., NATS consumers) where
    the middleware doesn't apply.
    """
    _current_tenant_id.set(tenant_id)


class TenantMiddleware(BaseHTTPMiddleware):
    """Extract tenant_id from X-Tenant-ID header and bind to async context.

    The API Gateway is responsible for extracting tenant_id from the JWT
    and injecting it as the X-Tenant-ID header before forwarding to
    downstream services.
    """

    # Paths that don't require tenant context
    EXEMPT_PATHS: set[str] = {"/health", "/healthz", "/readyz", "/docs", "/openapi.json"}

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            raise HTTPException(
                status_code=400,
                detail="X-Tenant-ID header is required",
            )

        # Set in contextvars — async-safe, scoped to this request
        token = _current_tenant_id.set(tenant_id)
        try:
            return await call_next(request)
        finally:
            _current_tenant_id.reset(token)


def apply_tenant_filter(stmt: Select, tenant_id_column) -> Select:
    """Apply WHERE tenant_id = :tid to a SQLAlchemy Select statement.

    This is the application-level enforcement of tenant isolation.
    Always use this instead of manually adding WHERE clauses.

    Args:
        stmt: A SQLAlchemy Select statement.
        tenant_id_column: The tenant_id column from the model
                          (e.g., DataPoint.tenant_id).

    Returns:
        The filtered Select statement.

    Raises:
        RuntimeError: If no tenant_id is in the current context.
    """
    tenant_id = get_current_tenant_id()
    return stmt.where(tenant_id_column == tenant_id)
