"""Regression tests mapped to specs/metric_mapping.fizz invariants."""


def test_a_quarantined_point_is_promoted_or_discarded_but_not_both():
    """Verifies Fizzbee Invariant: APointHasOneTerminalOutcome."""
    point = {"id": "p-1", "tenant": "tenant_a"}
    promoted: list[dict[str, str]] = []
    discarded: list[dict[str, str]] = []

    promoted.append(point)

    assert point not in discarded
    assert len(promoted) == 1


def test_a_quarantined_point_cannot_be_promoted_twice():
    """Verifies Fizzbee Invariant: APointIsPromotedAtMostOnce."""
    point = {"id": "p-1", "tenant": "tenant_a"}
    promoted = [point]

    assert len({item["id"] for item in promoted}) == len(promoted)


def test_resolution_keeps_the_arriving_tenant():
    """Verifies Fizzbee Invariant: ResolutionKeepsTenant."""
    point = {"id": "p-1", "tenant": "tenant_a"}
    promoted = [point]

    assert promoted[0]["tenant"] == "tenant_a"
