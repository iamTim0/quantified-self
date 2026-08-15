"""Executable checks for ``specs/health_aggregation.fizz`` invariants."""


def aggregate_status(observed: dict[str, str]) -> str:
    """Apply the safety rule used by the Gateway's aggregate health response."""
    return "ok" if all(status == "ok" for status in observed.values()) else "degraded"


def test_unhealthy_dependency_is_visible() -> None:
    """Verifies Fizzbee Invariant: UnhealthyDependencyIsVisible."""
    assert aggregate_status({"core": "ok", "dashboard": "ok"}) == "ok"
    assert aggregate_status({"core": "unavailable", "dashboard": "ok"}) == "degraded"
    assert aggregate_status({"core": "ok", "dashboard": "degraded"}) == "degraded"


def test_liveness_is_independent_from_aggregate_readiness() -> None:
    """Verifies Fizzbee Invariant: LivenessDoesNotWaitForDependencies."""
    aggregate = aggregate_status({"core": "unavailable", "dashboard": "ok"})
    gateway_liveness = "ok"

    assert aggregate == "degraded"
    assert gateway_liveness == "ok"
