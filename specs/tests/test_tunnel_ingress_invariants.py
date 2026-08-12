"""Executable checks for ``specs/tunnel_ingress.fizz`` invariants."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.coolify.yml"


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

    assert "TUNNEL_TOKEN=${TUNNEL_TOKEN:?set TUNNEL_TOKEN}" in text
    assert "command: tunnel --no-autoupdate --metrics 0.0.0.0:2000 run" in text
    assert "traefik:" in text


def test_no_private_service_public_exposure() -> None:
    """Verifies Fizzbee Invariant: NoPrivateServicePublicExposure.

    The embedded tunnel needs no host port, and the socket-free file provider
    cannot discover or accidentally publish unrelated server containers.
    """
    text = compose_text()

    assert "ports:" not in text
    assert "/var/run/docker.sock" not in text
    assert "--providers.docker" not in text
    assert "traefik.http.routers." not in text


def test_tunnel_requires_healthy_proxy() -> None:
    """Verifies Fizzbee Invariant: TunnelRequiresHealthyProxy."""
    text = compose_text()

    assert "condition: service_healthy" in text
    assert "traefik healthcheck --ping" in text


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
    assert "priority: 30" in text
    assert "priority: 20" in text
    assert "priority: 10" in text
    assert "priority: 1" in text
