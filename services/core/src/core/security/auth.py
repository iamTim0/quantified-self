"""Request authentication for the Core Data Service.

Before this module existed, Core derived the tenant from a bare ``X-Tenant-ID``
header and verified nothing. Because Core is published on ``:8001`` in both compose
files, anybody able to reach the port could read or write any tenant's data and pull
decrypted connector secrets. Core now authenticates every request itself; the Gateway
remains a useful edge filter but is no longer the only guard.

Two principal kinds are recognised:

* **user** — a signed access token (``aud=qs-api``). The tenant comes from the
  ``tenant_id`` claim. A supplied ``X-Tenant-ID`` may only *agree* with the claim;
  disagreement is 403, never a silent override.
* **service** — an internal mesh credential (``aud=qs-internal``), accepted only on
  ``/api/v1/internal/*``. Here ``X-Tenant-ID`` *is* honoured, because an authenticated
  importer legitimately acts on behalf of many tenants in turn.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantIdAlwaysPresent
- TenantHeaderAlwaysInjected
- RevokedTokenRejected
- ServiceTokenScopedToInternalPaths
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar, Literal

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.db.tenant import _current_tenant_id
from core.security.tokens import TokenError, decode_access_token, verify_service_credential

logger = logging.getLogger(__name__)

PrincipalKind = Literal["user", "service"]

INTERNAL_PATH_PREFIX = "/api/v1/internal/"

# Internal endpoints whose whole job is to *establish* which tenant is involved,
# so they cannot be asked to name one up front. They still require a valid service
# credential, and the tenant contextvar is deliberately left unset so that any
# accidental tenant-scoped query inside them raises instead of leaking.
TENANTLESS_INTERNAL_PATHS: set[str] = {"/api/v1/internal/auth/api-keys/resolve"}


@dataclass(frozen=True)
class Principal:
    """Who is making the current request, as established by verified credentials."""

    kind: PrincipalKind
    tenant_id: str
    user_id: str | None = None
    role: str = "member"
    jti: str | None = None
    email: str | None = None


_current_principal: ContextVar[Principal | None] = ContextVar(
    "current_principal", default=None
)


def get_current_principal() -> Principal:
    """Return the authenticated principal for this request."""
    principal = _current_principal.get()
    if principal is None:
        raise RuntimeError("principal not set in context")
    return principal


def set_current_principal(principal: Principal) -> None:
    _current_principal.set(principal)


def require_role(*allowed_roles: str):
    """FastAPI dependency: allow only the named roles.

    Service principals bypass role checks — they are not people and carry no role.
    """

    def _dependency() -> Principal:
        principal = get_current_principal()
        if principal.kind == "service":
            return principal
        if principal.role not in allowed_roles:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=403,
                detail="Insufficient role for this operation",
            )
        return principal

    return _dependency


async def _is_token_revoked(jti: str) -> bool:
    """Check the logout denylist. Fails closed if the database is unreachable."""
    from core.db.models import RevokedAccessToken
    from core.db.session import async_session_maker

    async with async_session_maker() as session:
        result = await session.execute(
            select(RevokedAccessToken.jti).where(RevokedAccessToken.jti == jti)
        )
        return result.scalar_one_or_none() is not None


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Authenticate the caller and bind tenant + principal to the async context."""

    EXEMPT_PATHS: ClassVar[set[str]] = {
        "/health",
        "/healthz",
        "/readyz",
        "/docs",
        "/openapi.json",
        "/api/v1/auth/signup",
        "/api/v1/auth/login",
        # Refresh and logout validate their own credentials: the access token is
        # expected to be expired or already invalid by the time they are called.
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    }

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if path in self.EXEMPT_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization") or ""
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization Bearer credential"},
            )
        raw_credential = auth_header[7:].strip()
        if not raw_credential:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing Authorization Bearer credential"},
            )

        header_tenant = request.headers.get("X-Tenant-ID")
        is_internal = path.startswith(INTERNAL_PATH_PREFIX)

        needs_tenant = path not in TENANTLESS_INTERNAL_PATHS

        try:
            principal = (
                self._authenticate_service(raw_credential, header_tenant, needs_tenant)
                if is_internal
                else await self._authenticate_user(raw_credential, header_tenant)
            )
        except TokenError as exc:
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )

        tenant_token = (
            _current_tenant_id.set(principal.tenant_id) if needs_tenant else None
        )
        principal_token = _current_principal.set(principal)
        try:
            return await call_next(request)
        finally:
            if tenant_token is not None:
                _current_tenant_id.reset(tenant_token)
            _current_principal.reset(principal_token)

    @staticmethod
    def _authenticate_service(
        raw_credential: str, header_tenant: str | None, needs_tenant: bool
    ) -> Principal:
        verify_service_credential(raw_credential)
        if not needs_tenant:
            return Principal(kind="service", tenant_id="", role="service")
        if not header_tenant:
            raise TokenError(
                "Internal requests must name the delegated tenant via X-Tenant-ID"
            )
        return Principal(kind="service", tenant_id=header_tenant, role="service")

    @staticmethod
    async def _authenticate_user(raw_credential: str, header_tenant: str | None) -> Principal:
        claims = decode_access_token(raw_credential)
        tenant_id = claims["tenant_id"]

        # A header may agree with the token, never override it.
        if header_tenant and header_tenant != tenant_id:
            raise TokenError(
                "X-Tenant-ID does not match the authenticated tenant", status_code=403
            )

        if await _is_token_revoked(claims["jti"]):
            raise TokenError("Token has been revoked")

        return Principal(
            kind="user",
            tenant_id=tenant_id,
            user_id=claims["user_id"],
            role=claims.get("role", "member"),
            jti=claims["jti"],
            email=claims.get("email"),
        )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
