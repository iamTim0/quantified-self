"""Release and health metadata used by the unauthenticated gateway endpoints."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

DEFAULT_SERVICE_VERSION = "dev"
DEFAULT_SOURCE_COMMIT = "unknown"


@dataclass(frozen=True, slots=True)
class HealthTarget:
    """Describe one internal service health endpoint."""

    service: str
    setting: str
    path: str = "/health"
    role: str | None = None

# These are the first-party images published together by the release workflow.
# Infrastructure images are intentionally not listed: their upstream image tags
# are independent of the Quantified Self release version.
RELEASE_SERVICES = (
    "core-migrate",
    "core",
    "core-ingest",
    "core-scheduler",
    "analysis",
    "api-gateway",
    "dashboard",
    "docs",
    "importer-yazio",
    "importer-dawarich",
    "importer-whoop",
    "importer-apple-health",
    "importer-streak",
    "importer-home-assistant",
    "importer-weather",
    "importer-calendar",
)

# The Gateway observes these targets over the private Compose network. The
# Gateway itself is added from its own process metadata, and core-migrate is a
# one-shot job, so neither belongs in this live probe list.
HEALTH_TARGETS = (
    HealthTarget("core", "CORE_SERVICE_URL", path="/readyz", role="api"),
    HealthTarget("core-ingest", "CORE_INGEST_URL", path="/readyz", role="ingest"),
    HealthTarget("core-scheduler", "CORE_SCHEDULER_URL", path="/readyz", role="scheduler"),
    HealthTarget("analysis", "ANALYSIS_SERVICE_URL"),
    HealthTarget("dashboard", "DASHBOARD_URL", path="/healthz"),
    HealthTarget("docs", "DOCS_URL", path="/healthz"),
    HealthTarget("importer-yazio", "YAZIO_IMPORTER_URL"),
    HealthTarget("importer-dawarich", "DAWARICH_IMPORTER_URL"),
    HealthTarget("importer-whoop", "WHOOP_IMPORTER_URL"),
    HealthTarget("importer-apple-health", "APPLE_HEALTH_IMPORTER_URL"),
    HealthTarget("importer-streak", "STREAK_IMPORTER_URL"),
    HealthTarget("importer-home-assistant", "HOME_ASSISTANT_IMPORTER_URL"),
    HealthTarget("importer-weather", "WEATHER_IMPORTER_URL"),
    HealthTarget("importer-calendar", "CALENDAR_IMPORTER_URL"),
)


def service_version() -> str:
    """Return the release version baked into the running gateway image."""
    return os.environ.get("QS_SERVICE_VERSION") or DEFAULT_SERVICE_VERSION


def source_commit() -> str:
    """Return the source commit baked into the running gateway image."""
    return os.environ.get("QS_SOURCE_COMMIT") or DEFAULT_SOURCE_COMMIT


def expected_release_manifest() -> list[dict[str, Any]]:
    """Describe expected first-party image metadata without claiming liveness."""
    version = service_version()
    commit = source_commit()
    return [
        {
            "service": service,
            "status": "expected",
            "observed": False,
            "version": version,
            "commit": commit,
        }
        for service in RELEASE_SERVICES
    ]


def health_payload(service: str, *, status: str = "ok", **fields: Any) -> dict[str, Any]:
    """Build a stable health response without exposing runtime configuration."""
    return {
        "status": status,
        "service": service,
        "version": service_version(),
        "commit": source_commit(),
        **fields,
    }
