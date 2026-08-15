"""Token minting and verification for the Core Data Service.

Two credential families share nothing but the signing algorithm:

* **User access tokens** — signed with ``JWT_SECRET``, ``aud=qs-api``,
  ``token_type=access``. They carry ``user_id``, ``tenant_id``, ``role`` and a
  ``jti`` so a single session can be revoked on logout.
* **Internal service credentials** — signed with the *separate*
  ``INTERNAL_SERVICE_SECRET``, ``aud=qs-internal``, ``token_type=service``. They
  authenticate an importer or other mesh peer, never a person, and Core accepts
  them only on ``/api/v1/internal/*``.

Keeping the two secrets disjoint means a compromised importer cannot mint a user
token for an arbitrary tenant — the worst it can do is what an importer may
already do.

Refresh tokens are deliberately *not* JWTs. They are opaque random strings whose
SHA-256 hash is the only thing Core stores, so a database leak cannot be replayed
against the API.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantIdAlwaysPresent
- RevokedTokenRejected
- ServiceTokenScopedToInternalPaths
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from core.config import settings

ISSUER = "qs-core"
AUDIENCE_USER = "qs-api"
AUDIENCE_INTERNAL = "qs-internal"

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_SERVICE = "service"

PrincipalKind = Literal["user", "service"]


class TokenError(Exception):
    """Raised when a presented credential is missing, malformed or rejected.

    Carries the HTTP status the caller should surface: ``401`` for "we do not
    know who you are", ``403`` for "we know, and you may not do this".
    """

    def __init__(self, detail: str, status_code: int = 401) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _internal_secret() -> str:
    secret = getattr(settings, "INTERNAL_SERVICE_SECRET", "") or ""
    if not secret:
        # Deterministic dev fallback, derived from — but not equal to — JWT_SECRET
        # so that the two credential families never share a signing key.
        secret = hashlib.sha256(
            f"internal-service::{settings.JWT_SECRET}".encode()
        ).hexdigest()
    return secret


def hash_token(raw: str) -> str:
    """Return the storage form of an opaque credential (refresh token / API key)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ─── User access tokens ──────────────────────────────────────


def create_access_token(
    *,
    user_id: str,
    tenant_id: str,
    email: str,
    role: str,
    ttl_minutes: int | None = None,
) -> tuple[str, str, datetime]:
    """Mint a signed user access token.

    Returns ``(token, jti, expires_at)``. The ``jti`` is what the logout denylist
    keys on, so callers must persist it alongside the session.
    """
    now = datetime.now(timezone.utc)
    ttl = ttl_minutes if ttl_minutes is not None else settings.ACCESS_TOKEN_TTL_MINUTES
    expires_at = now + timedelta(minutes=ttl)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "sub": user_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "role": role,
        "jti": jti,
        "iss": ISSUER,
        "aud": AUDIENCE_USER,
        "token_type": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, jti, expires_at


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate signature, issuer, audience, expiry, token type and claims.

    Raises:
        TokenError: on any validation failure. The message is deliberately
            generic so it cannot be used as an oracle.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=AUDIENCE_USER,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or malformed token") from exc

    if payload.get("token_type") != TOKEN_TYPE_ACCESS:
        raise TokenError("Invalid or malformed token")

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise TokenError("Token missing tenant_id claim")

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise TokenError("Token missing user_id claim")
    payload["user_id"] = user_id

    if not payload.get("jti"):
        raise TokenError("Token missing jti claim")

    if not payload.get("role"):
        # A token without an explicit role gets the least privilege we model,
        # never the most — the previous implementation defaulted to "owner".
        payload["role"] = "member"

    return payload


# ─── Refresh tokens ──────────────────────────────────────────


def create_refresh_token() -> tuple[str, str, datetime]:
    """Mint an opaque refresh token.

    Returns ``(raw_token, token_hash, expires_at)``. Only the hash is ever stored.
    """
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_TTL_DAYS
    )
    return raw, hash_token(raw), expires_at


# ─── Inbound API keys ────────────────────────────────────────

API_KEY_PREFIX = "qsk"


def create_api_key() -> tuple[str, str, str]:
    """Mint a tenant-bound inbound API key.

    Returns ``(raw_key, key_prefix, key_hash)``. The raw key is returned to the
    caller exactly once and never persisted; the tenant is later recovered from
    the hash alone, which is why no tenant header is needed at ingest time.
    """
    raw = f"{API_KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return raw, raw[:12], hash_token(raw)


# ─── Internal service credentials ────────────────────────────


def create_service_token(
    subject: str = "qs-internal-service", ttl_minutes: int = 60
) -> str:
    """Mint a short-lived internal service token (used by tooling and tests)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iss": ISSUER,
        "aud": AUDIENCE_INTERNAL,
        "token_type": TOKEN_TYPE_SERVICE,
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
    }
    return jwt.encode(payload, _internal_secret(), algorithm=settings.JWT_ALGORITHM)


def verify_service_credential(
    raw: str,
    *,
    service_name: str | None = None,
) -> dict[str, Any]:
    """Authenticate an internal mesh peer.

    Accepts either a service JWT (preferred — it expires) or the raw shared
    ``INTERNAL_SERVICE_SECRET``, compared in constant time. The shared-secret form
    exists so importers need no JWT-minting code of their own; it is a service
    credential in the same class as a database password, never a user credential.

    Raises:
        TokenError: if the credential is neither a valid service JWT nor the
            configured shared secret.
    """
    configured = getattr(settings, "internal_service_secrets", {})
    if configured and not service_name:
        raise TokenError("Internal service identity is required")
    if service_name and configured:
        secret = configured.get(service_name)
        if secret is None:
            raise TokenError("Unknown internal service identity")
        candidates = [(service_name, secret)]
    else:
        candidates = [(name, secret) for name, secret in configured.items()]
        candidates.append((None, _internal_secret()))

    for configured_name, secret in candidates:
        try:
            payload = jwt.decode(
                raw,
                secret,
                algorithms=[settings.JWT_ALGORITHM],
                audience=AUDIENCE_INTERNAL,
                issuer=ISSUER,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError:
            payload = None
        if payload is not None and payload.get("token_type") == TOKEN_TYPE_SERVICE:
            if service_name and payload.get("sub") != service_name:
                raise TokenError("Internal service identity does not match credential")
            return payload

        if hmac.compare_digest(raw, secret):
            return {
                "sub": configured_name or "qs-internal-shared-secret",
                "token_type": TOKEN_TYPE_SERVICE,
                "iss": ISSUER,
                "aud": AUDIENCE_INTERNAL,
            }

    raise TokenError("Invalid internal service credential")
