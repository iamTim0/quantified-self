"""Executable model of specs/smart_import_planning.fizz.

The safety property is asymmetric. Re-importing existing data is harmless because
ingestion is idempotent; skipping a range that is not actually complete loses it
permanently. So every uncertain case must resolve to "import it", and that is what
these tests exhaustively check.

The real implementation is ``core.ingest_planning``; its behavioural tests live in
``services/core/tests/test_ingest_planning.py``. This file checks the model.

Mappings:
- NeverSkipIncompleteData      -> test_never_skip_incomplete_data
- ForceModeSkipsNothing        -> test_force_mode_skips_nothing
- LowConfidenceImportsEverything -> test_low_confidence_imports_everything
- PlanCoversTheWholeRange      -> test_plan_covers_the_whole_range
"""

from dataclasses import dataclass, field
from itertools import product

BUCKETS = (0, 1, 2, 3, 4)
MAX_BLOCKS_FOR_CONFIDENT_PLAN = 2


@dataclass
class Plan:
    imported: set[int] = field(default_factory=set)
    skipped: set[int] = field(default_factory=set)
    confidence: str = "high"
    mode: str = "smart"


def count_blocks(full: frozenset[int]) -> int:
    """Number of contiguous runs of complete buckets."""
    blocks = 0
    previous = False
    for bucket in BUCKETS:
        is_full = bucket in full
        if is_full and not previous:
            blocks += 1
        previous = is_full
    return blocks


def plan(full: frozenset[int], mode: str = "smart") -> Plan:
    """The planning rule from the spec."""
    result = Plan(mode=mode)

    if mode == "force":
        result.imported = set(BUCKETS)
        return result

    if count_blocks(full) > MAX_BLOCKS_FOR_CONFIDENT_PLAN:
        result.confidence = "low"
        result.imported = set(BUCKETS)
        return result

    for bucket in BUCKETS:
        if bucket in full:
            result.skipped.add(bucket)
        else:
            result.imported.add(bucket)
    return result


def _all_coverage_shapes():
    """Every possible full/partial/empty assignment over the five buckets."""
    for assignment in product(("full", "partial", "empty"), repeat=len(BUCKETS)):
        full = frozenset(b for b, kind in zip(BUCKETS, assignment) if kind == "full")
        yield assignment, full


def test_never_skip_incomplete_data():
    """Verifies Fizzbee Invariant: NeverSkipIncompleteData.

    Checked over all 3^5 coverage shapes: a bucket that is not positively complete
    is always imported and never skipped.
    """
    for assignment, full in _all_coverage_shapes():
        result = plan(full)
        for bucket, kind in zip(BUCKETS, assignment):
            if kind != "full":
                assert bucket not in result.skipped, (assignment, bucket)
                assert bucket in result.imported, (assignment, bucket)


def test_force_mode_skips_nothing():
    """Verifies Fizzbee Invariant: ForceModeSkipsNothing."""
    for _assignment, full in _all_coverage_shapes():
        result = plan(full, mode="force")
        assert result.skipped == set()
        assert result.imported == set(BUCKETS)


def test_low_confidence_imports_everything():
    """Verifies Fizzbee Invariant: LowConfidenceImportsEverything.

    Fragmented coverage — alternating present and absent buckets — cannot be
    reasoned about at block level, so nothing may be skipped.
    """
    fragmented = frozenset({0, 2, 4})
    result = plan(fragmented)

    assert result.confidence == "low"
    assert result.skipped == set()
    assert result.imported == set(BUCKETS)

    for _assignment, full in _all_coverage_shapes():
        outcome = plan(full)
        if outcome.confidence == "low":
            assert outcome.skipped == set()


def test_plan_covers_the_whole_range():
    """Verifies Fizzbee Invariant: PlanCoversTheWholeRange.

    Every bucket is either imported or skipped, never both and never neither. A
    bucket falling through both branches would be silent data loss.
    """
    for mode in ("smart", "force"):
        for _assignment, full in _all_coverage_shapes():
            result = plan(full, mode=mode)
            assert not (result.imported & result.skipped)
            assert result.imported | result.skipped == set(BUCKETS)


def test_fully_covered_contiguous_range_is_skipped_entirely():
    """The optimisation still has to actually optimise the common case."""
    result = plan(frozenset(BUCKETS))
    assert result.skipped == set(BUCKETS)
    assert result.imported == set()


def test_trailing_gap_narrows_the_import():
    """History present, recent buckets missing — only the tail is imported."""
    result = plan(frozenset({0, 1, 2}))
    assert result.skipped == {0, 1, 2}
    assert result.imported == {3, 4}
