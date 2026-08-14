"""Executable checks for ``metric_aware_import_planning.fizz``."""


def should_skip(
    *,
    complete_metrics: set[str],
    required_metrics: set[str],
    coverage_revision: str,
    current_revision: str,
) -> bool:
    """Return whether the planner may safely skip a range."""
    return (
        complete_metrics == required_metrics
        and coverage_revision == current_revision
    )


def test_missing_metric_cannot_be_hidden_by_a_dense_metric():
    """Verifies Fizzbee Invariant: NeverSkipIncompleteMetric."""
    assert not should_skip(
        complete_metrics={"steps"},
        required_metrics={"steps", "sleep"},
        coverage_revision="v1",
        current_revision="v1",
    )


def test_revision_change_invalidates_historical_coverage():
    """Verifies Fizzbee Invariant: RevisionChangeInvalidatesCoverage."""
    assert not should_skip(
        complete_metrics={"steps", "sleep"},
        required_metrics={"steps", "sleep"},
        coverage_revision="v1",
        current_revision="v2",
    )


def test_unknown_coverage_is_imported():
    """Verifies Fizzbee Invariant: UnknownCoverageImports."""
    assert not should_skip(
        complete_metrics=set(),
        required_metrics={"steps", "sleep"},
        coverage_revision="unknown",
        current_revision="v1",
    )
