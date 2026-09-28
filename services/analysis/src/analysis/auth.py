"""Request-scoped user authentication for Analysis HTTP and MCP endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

import jwt
from fastapi import HTTPException, Request

from analysis.config import settings
from analysis.core_client import CoreClient, CoreUnavailable

ISSUER = "qs-core"
AUDIENCE_USER = "qs-api"
TOKEN_TYPE_ACCESS = "access"


@dataclass(frozen=True)
class McpPrincipal:
    """Identity derived from a verified credential, never from tool arguments."""

    tenant_id: str
    user_id: str
    role: str
    scopes: tuple[str, ...]
    jti: str
    issued_at: datetime


class McpPrincipalResolver(Protocol):
    """Authentication seam for internal JWTs and future external credentials."""

    def resolve(self, authorization: str) -> McpPrincipal:
        """Authenticate one request without retaining protocol session state."""
        ...


@dataclass(frozen=True)
class BearerPrincipalResolver:
    """Adapt any bearer-token verifier to the MCP principal interface."""

    verifier: Callable[[str], McpPrincipal]

    def resolve(self, authorization: str) -> McpPrincipal:
        return self.verifier(authorization)


def principal_from_authorization(authorization: str) -> McpPrincipal:
    """Validate one bearer credential and return its tenant-bound principal."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing Authorization Bearer credential"
        )

    try:
        claims = jwt.decode(
            authorization[7:].strip(),
            settings.JWT_SECRET,
            algorithms=["HS256"],
            audience=AUDIENCE_USER,
            issuer=ISSUER,
            options={
                "require": [
                    "exp",
                    "iat",
                    "jti",
                    "tenant_id",
                    "user_id",
                    "token_type",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc

    if claims.get("token_type") != TOKEN_TYPE_ACCESS:
        raise HTTPException(
            status_code=401, detail="Credential is not a user access token"
        )

    tenant_id = claims.get("tenant_id")
    user_id = claims.get("user_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HTTPException(status_code=401, detail="Token carries no tenant")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Token carries no user")
    jti = claims.get("jti")
    issued_at = claims.get("iat")
    if not isinstance(jti, str) or not jti or issued_at is None:
        raise HTTPException(status_code=401, detail="Token carries no session identity")

    raw_scopes = claims.get("scopes", ())
    scopes = (
        tuple(scope for scope in raw_scopes if isinstance(scope, str))
        if isinstance(raw_scopes, list)
        else ()
    )
    return McpPrincipal(
        tenant_id=tenant_id,
        user_id=user_id,
        role=str(claims.get("role") or "member"),
        scopes=scopes,
        jti=jti,
        issued_at=datetime.fromtimestamp(int(issued_at), tz=UTC),
    )


mcp_principal_resolver: McpPrincipalResolver = BearerPrincipalResolver(
    principal_from_authorization
)


def resolve_principal(request: Request) -> McpPrincipal:
    """Resolve identity and reject a contradictory legacy tenant header."""
    principal = principal_from_authorization(request.headers.get("Authorization") or "")
    claimed = request.headers.get("X-Tenant-ID")
    if claimed and claimed != principal.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="X-Tenant-ID does not match the authenticated tenant",
        )
    return principal


async def require_live_tenant(request: Request) -> str:
    """Reject a signed token whose session Core has since revoked."""
    principal = resolve_principal(request)
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id
    try:
        valid, code = await CoreClient().validate_user_session(
            principal.tenant_id,
            user_id=principal.user_id,
            jti=principal.jti,
            issued_at=principal.issued_at,
            request_id=request_id,
        )
    except CoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Session validation is temporarily unavailable"
        ) from exc
    if not valid:
        raise HTTPException(status_code=401, detail=code)
    return principal.tenant_id
