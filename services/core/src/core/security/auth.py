"""Request authentication for the Core Data Service.

Before this module existed, Core derived the tenant from a bare ``X-Tenant-ID``
header and verified nothing. Because Core is published on ``:8001`` in both compose
files, anybody able to reach the port could read or write any tenant's data and pull
decrypted connector secrets. Core now authenticates every request itself; the Gateway
remains a useful edge filter but is no longer the only guard.

Two principal kinds are recognised:

* **user** — a signed access token (``aud=qs-api``), presented either in the
  ``qs_access`` httpOnly cookie (browsers) or as an ``Authorization: Bearer``
  header (tests, scripts, anything that is not a browser). The tenant comes from
  the ``tenant_id`` claim. A supplied ``X-Tenant-ID`` may only *agree* with the
  claim; disagreement is 403, never a silent override. Cookie-authenticated
  writes additionally carry a double-submit CSRF token — see
  :mod:`core.security.cookies` for why the header path does not need one.
* **service** — an internal mesh credential (``aud=qs-internal``), accepted only on
  ``/api/v1/internal/*``. Here ``X-Tenant-ID`` *is* honoured, because an authenticated
  importer legitimately acts on behalf of many tenants in turn.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantIdAlwaysPresent
- TenantHeaderAlwaysInjected
- RevokedTokenRejected
- ServiceTokenScopedToInternalPaths
- AcceptedLogoutLeavesNothingItCoveredAlive
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar, Literal

from core.db.tenant import _current_tenant_id
from core.security.cookies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    SAFE_METHODS,
    csrf_token_matches,
)
from core.security.tokens import (
    TokenError,
    decode_access_token,
    verify_service_credential,
)
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

PrincipalKind = Literal["user", "service"]

INTERNAL_PATH_PREFIX = "/api/v1/internal/"

# Internal endpoints whose whole job is to *establish* which tenant is involved,
# so they cannot be asked to name one up front. They still require a valid service
# credential, and the tenant contextvar is deliberately left unset so that any
# accidental tenant-scoped query inside them raises instead of leaking.
TENANTLESS_INTERNAL_PATHS: set[str] = {
    "/api/v1/internal/auth/api-keys/resolve",
    "/api/v1/internal/auth/api-keys/failure",
}


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


async def _revocation_reason(claims: dict) -> str | None:
    """Why this token must be refused, or None if it stands.

    Two independent mechanisms, because one cannot do the other's job:

    * the ``jti`` denylist ends *this* session, and is the only thing that can —
      the token is otherwise indistinguishable from any other;
    * ``users.sessions_valid_from`` ends *every* session, which the denylist
      cannot express, since a ``jti`` is only ever learned by being presented.

    Both fail closed: an exception here propagates rather than being swallowed
    into "not revoked", so a database outage cannot silently re-enable every
    logged-out token.
    """
    from core.db.models import RevokedAccessToken, User
    from core.db.session import async_session_maker

    jti = claims["jti"]
    async with async_session_maker() as session:
        revoked = await session.execute(
            select(RevokedAccessToken.jti).where(RevokedAccessToken.jti == jti)
        )
        if revoked.scalar_one_or_none() is not None:
            return "Token has been revoked"

        issued_at = claims.get("iat")
        if issued_at is None:
            return None

        cutoff = (
            await session.execute(
                select(User.sessions_valid_from).where(
                    User.id == claims["user_id"],
                    User.tenant_id == claims["tenant_id"],
                )
            )
        ).scalar_one_or_none()
        # No row means no cutoff to apply. Deliberately not "reject": tokens are
        # minted for users that no test necessarily materialises, and turning a
        # missing row into a 401 here would be a much larger behaviour change than
        # this column is for. /auth/me already refuses a deleted account.
        if cutoff is None:
            return None

        # PyJWT hands back `iat` as an integer of seconds.
        if datetime.fromtimestamp(int(issued_at), tz=timezone.utc) < cutoff:
            return "Session has been ended"

    return None


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
        # Listing enabled login providers must work before anyone is signed in.
        "/api/v1/auth/oidc/providers",
    }

    # Sign-in flows with a provider slug in the path. These are how a session is
    # obtained, so requiring one would be circular; each validates its own
    # single-use, server-side state instead.
    EXEMPT_PREFIXES: ClassVar[tuple[str, ...]] = ("/api/v1/auth/oidc/",)

    def _is_exempt(self, path: str) -> bool:
        return path in self.EXEMPT_PATHS or path.startswith(self.EXEMPT_PREFIXES)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)

        # The Authorization header wins when present: that is how services,
        # importers and API keys authenticate. The cookie is the browser path.
        auth_header = request.headers.get("Authorization") or ""
        raw_credential = ""
        from_cookie = False

        if auth_header.startswith("Bearer "):
            raw_credential = auth_header[7:].strip()
        else:
            raw_credential = (request.cookies.get(ACCESS_COOKIE) or "").strip()
            from_cookie = bool(raw_credential)

        if not raw_credential:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing session cookie or Authorization Bearer credential"},
            )

        # CSRF only concerns the cookie path. A browser never attaches an
        # Authorization header on its own, so header-authenticated callers cannot
        # be made to act by a hostile page.
        needs_csrf = from_cookie and request.method not in SAFE_METHODS
        if needs_csrf and not csrf_token_matches(
            request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing or invalid CSRF token"},
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

        reason = await _revocation_reason(claims)
        if reason:
            raise TokenError(reason)

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
