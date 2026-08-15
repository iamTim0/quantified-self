"""Build metadata shared by first-party service health endpoints."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_SERVICE_VERSION = "dev"
DEFAULT_SOURCE_COMMIT = "unknown"


def service_version() -> str:
    """Return the release version baked into the running image."""
    return os.environ.get("QS_SERVICE_VERSION") or DEFAULT_SERVICE_VERSION


def source_commit() -> str:
    """Return the source commit baked into the running image."""
    return os.environ.get("QS_SOURCE_COMMIT") or DEFAULT_SOURCE_COMMIT


def health_payload(
    service: str,
    *,
    status: str = "ok",
    **fields: Any,
) -> dict[str, Any]:
    """Build the stable, unauthenticated payload returned by ``GET /health``."""
    return {
        "status": status,
        "service": service,
        "version": service_version(),
        "commit": source_commit(),
        **fields,
    }
