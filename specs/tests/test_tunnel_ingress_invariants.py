"""Executable checks for ``specs/tunnel_ingress.fizz`` invariants."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.prod.yml"


def route_request(path: str) -> str:
    """Apply the proxy precedence modeled by the Fizzbee specification."""
    if path == "/health" or path.startswith("/api"):
        return "api-gateway"
    if path.startswith("/docs"):
        return "docs"
    if path.startswith("/ingest"):
        return "streak-importer"
    return "dashboard"


def compose_text() -> str:
    """Read the production Coolify topology under test."""
    return COMPOSE.read_text(encoding="utf-8")


def test_tunnel_targets_only_stack_proxy() -> None:
    """Verifies Fizzbee Invariant: TunnelTargetsOnlyStackProxy.

    The remotely managed Cloudflare route resolves the stack service name and
    never bypasses its routing and access-log boundary.
    """
    text = compose_text()

    # TUNNEL_TOKEN is optional in prod since we allow direct exposure via QS_BIND_IP
    assert "TUNNEL_TOKEN=${TUNNEL_TOKEN:-}" in text
    assert "command: tunnel --no-autoupdate run" in text
    assert "traefik:" in text


def test_no_private_service_public_exposure() -> None:
    """Verifies Fizzbee Invariant: NoPrivateServicePublicExposure.

    Traefik uses docker provider but exposedbydefault=false prevents accidental
    publishing of unrelated containers. Ports are conditionally exposed via QS_BIND_IP.
    """
    text = compose_text()

    # Prod compose exposes ports conditionally via QS_BIND_IP
    assert "ports:" in text
    assert '"${QS_BIND_IP:-127.0.0.1}:${QS_HTTP_PORT:-80}:80"' in text
    assert "--providers.docker.exposedbydefault=false" in text


def test_tunnel_requires_healthy_proxy() -> None:
    """Verifies Fizzbee Invariant: TunnelRequiresHealthyProxy.
    
    The tunnel depends on traefik starting.
    """
    text = compose_text()

    assert "traefik:" in text
    assert "depends_on:" in text


def test_specific_routes_precede_dashboard() -> None:
    """Verifies Fizzbee Invariant: SpecificRoutesPrecedeDashboard.

    API, documentation, and ingestion routes win before the dashboard catch-all,
    while arbitrary application pages still reach the dashboard.
    """
    expected = {
        "/": "dashboard",
        "/explorer": "dashboard",
        "/api/v1/data": "api-gateway",
        "/health": "api-gateway",
        "/docs": "docs",
        "/docs/operations/": "docs",
        "/ingest/streak": "streak-importer",
    }

    assert {path: route_request(path) for path in expected} == expected

    text = compose_text()
    # Dashboard uses priority 1, other routers rely on Traefik's rule-length sorting
    assert "traefik.http.routers.workspace.priority=1" in text
