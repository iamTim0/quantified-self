"""Inbound API key authentication for the Apple Health webhook.

The previous implementation took the tenant from a client-supplied ``X-Tenant-ID``
header, looked up that tenant's connector token, and compared it to the presented
key with ``if expected_key and x_api_key != expected_key``. When the tenant had no
connector configured — or when Core was simply unreachable — ``expected_key`` was
falsy, the comparison was skipped, and unauthenticated data was accepted for any
tenant the caller cared to name.

Authentication now runs the other way round: the key *is* the identity. The
presented key is hashed locally, Core resolves the hash to its owning tenant, and
a failure to resolve is a rejection. No tenant header is read, so none can be
forged, and the raw key never leaves this service.

Maps to Fizzbee Invariants:
- WebhookMappedToCorrectTenant
- UnauthenticatedWebhookRejected
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx
from fastapi import HTTPException

from apple_health_importer.config import settings

logger = logging.getLogger(__name__)

# Dev-only fallback. Mirrors core.security.tokens._internal_secret so a default
# local environment works without extra configuration. Production must set
# INTERNAL_SERVICE_SECRET explicitly on both Core and every importer.
_DEV_JWT_SECRET = "dev-secret-key-quantified-self-2026"


def internal_service_credential() -> str:
    """The bearer credential this importer presents to Core's internal API."""
    if settings.INTERNAL_SERVICE_SECRET:
        return settings.INTERNAL_SERVICE_SECRET
    return hashlib.sha256(f"internal-service::{_DEV_JWT_SECRET}".encode()).hexdigest()


def internal_headers(req_id: str, tenant_id: str | None = None) -> dict[str, str]:
    """Standard headers for a call to Core's internal API."""
    headers = {
        "Authorization": f"Bearer {internal_service_credential()}",
        "X-Request-ID": req_id,
    }
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


async def record_api_key_failure(
    presented_key: str,
    *,
    req_id: str,
    status_code: int,
    message: str,
) -> None:
    """Ask Core to attribute a rejected key to its connector, without the key itself."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/auth/api-keys/failure"
    payload = {
        "key_hash": hashlib.sha256(presented_key.encode("utf-8")).hexdigest(),
        "source_type": settings.SOURCE_TYPE,
        "request_id": req_id,
        "status_code": status_code,
        "message": message[:512],
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, headers=internal_headers(req_id), json=payload)
    except Exception as exc:
        logger.debug("[req_id=%s] Could not record rejected Apple Health request: %s", req_id, exc)


@dataclass(frozen=True)
class ApiKeyIdentity:
    """The tenant and connector an accepted API key resolves to."""

    tenant_id: str
    source_id: str | None
    key_prefix: str


def extract_presented_key(
    authorization: str | None, x_api_key: str | None
) -> str | None:
    """Read the inbound key from ``Authorization: Bearer`` or the legacy header.

    ``Authorization`` is the documented form; ``X-Api-Key`` stays supported because
    existing Health Auto Export and Streak configurations use it.
    """
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate:
            return candidate
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    return None


async def resolve_api_key(presented_key: str | None, req_id: str) -> ApiKeyIdentity:
    """Resolve a presented key to its owning tenant, or reject the request.

    Fails closed in every branch: an unknown key, a revoked key, a key minted for a
    different connector, and an unreachable Core all produce a rejection rather than
    an accepted anonymous ingest.
    """
    if not presented_key:
        logger.warning("[req_id=%s] Ingest attempt with no API key.", req_id)
        raise HTTPException(status_code=401, detail="Missing API key.")

    key_hash = hashlib.sha256(presented_key.encode("utf-8")).hexdigest()
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/auth/api-keys/resolve"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                url,
                headers=internal_headers(req_id),
                json={"key_hash": key_hash, "source_type": settings.SOURCE_TYPE},
            )
    except Exception as exc:
        # Never fall back to "allow" when the authority is unavailable.
        logger.error("[req_id=%s] Could not reach Core to resolve API key: %s", req_id, exc)
        raise HTTPException(
            status_code=503, detail="Authentication service unavailable. Please retry."
        )

    if res.status_code != 200:
        await record_api_key_failure(
            presented_key,
            req_id=req_id,
            status_code=res.status_code,
            message="The API key was rejected by Core.",
        )
        logger.warning(
            "[req_id=%s] Rejected ingest: API key not accepted (core status=%s).",
            req_id,
            res.status_code,
        )
        raise HTTPException(status_code=401, detail="Invalid API key.")

    data = res.json()
    tenant_id = data.get("tenant_id")
    if not tenant_id:
        await record_api_key_failure(
            presented_key,
            req_id=req_id,
            status_code=401,
            message="Core returned no tenant for the API key.",
        )
        raise HTTPException(status_code=401, detail="Invalid API key.")

    return ApiKeyIdentity(
        tenant_id=tenant_id,
        source_id=data.get("source_id"),
        key_prefix=data.get("key_prefix", ""),
    )
