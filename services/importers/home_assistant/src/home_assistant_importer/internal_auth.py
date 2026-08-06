"""Internal service credential for calls to Core's internal API.

Core no longer accepts a bare ``X-Tenant-ID`` header as proof of anything. Every
call to ``/api/v1/internal/*`` must present a service credential; the tenant is
then supplied alongside it as explicit delegation.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- ServiceTokenScopedToInternalPaths
"""

from __future__ import annotations

import hashlib

from home_assistant_importer.config import settings

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
