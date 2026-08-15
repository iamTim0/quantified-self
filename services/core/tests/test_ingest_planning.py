"""Unit tests for adaptive import windows, coverage analysis and gap detection.

These are pure-function tests with a fake bucket fetcher, so they run without a
database and assert on the decisions rather than on SQL.

The property that matters most is the safety rule: the planner may only skip a
range it positively knows to be complete. Several tests below exist purely to prove
it does not skip when uncertain.

Maps to Fizzbee Invariants:
- NoDuplicateData
- BackfillNeverCrossesTenant
- SmartSkipOnlyWhenComplete
"""

from datetime import datetime, timedelta, timezone

import pytest
from core.ingest_planning import (
    MAX_OVERLAP_HOURS,
    MIN_OVERLAP_HOURS,
    BucketCount,
    TimeRange,
    analyse_coverage,
    choose_bucket_seconds,
    classify_buckets,
    compute_sync_window,
    detect_expected_interval,
    find_gaps,
    merge_adjacent,
    overlap_for_interval,
    plan_import,
    subtract,
)

DAY = 86_400
HOUR = 3_600
BASE = datetime(2026, 8, 1, tzinfo=timezone.utc)


def _fetcher(points: list[datetime]):
    """Build a bucket fetcher backed by an in-memory list of timestamps."""

    async def fetch(start: datetime, end: datetime, bucket_seconds: int):
        buckets: list[BucketCount] = []
        cursor = start
        step = timedelta(seconds=bucket_seconds)
        while cursor < end:
            bucket_end = min(cursor + step, end)
            count = sum(1 for p in points if cursor <= p < bucket_end)
            buckets.append(BucketCount(start=cursor, end=bucket_end, count=count))
            cursor = bucket_end
        return buckets

    return fetch


def _hourly(day_offset: int, hours: int = 24) -> list[datetime]:
    """`hours` hourly points on the given day."""
    day = BASE + timedelta(days=day_offset)
    return [day + timedelta(hours=h) for h in range(hours)]


# ─── Adaptive windows ────────────────────────────────────────


@pytest.mark.parametrize(
    ("interval_hours", "expected_hours"),
    [
        (1, 2),      # the brief's worked example
        (3, 6),
        (6, 12),     # "correspondingly larger"
        (12, 24),
        (24, 48),
        (168, MAX_OVERLAP_HOURS),  # capped
        (0, MIN_OVERLAP_HOURS),    # degenerate config
    ],
)
def test_overlap_scales_with_poll_interval(interval_hours, expected_hours):
    """Overlap tracks polling frequency and stays inside sane bounds."""
    assert overlap_for_interval(interval_hours) == timedelta(hours=expected_hours)


def test_first_sync_uses_the_full_lookback():
    """With no prior success there is nothing to resume from."""
    now = BASE + timedelta(days=40)
    window, reason = compute_sync_window(
        now=now, poll_interval_hours=6, lookback_days=30, last_success_end=None
    )
    assert window.end == now
    assert window.start == now - timedelta(days=30)
    assert "First import" in reason


def test_first_sync_supports_a_sub_day_lookback():
    """A high-frequency connector can request only the last few hours."""
    now = BASE + timedelta(days=40)
    window, reason = compute_sync_window(
        now=now,
        poll_interval_hours=1,
        lookback_days=7,
        lookback_hours=6,
        last_success_end=None,
    )
    assert window.start == now - timedelta(hours=6)
    assert window.end == now
    assert "6 hours" in reason


def test_subsequent_sync_resumes_with_overlap():
    """A resumed sync starts before the last success, not at it."""
    now = BASE + timedelta(days=10)
    last = now - timedelta(hours=6)
    window, reason = compute_sync_window(
        now=now, poll_interval_hours=1, lookback_days=30, last_success_end=last
    )
    assert window.start == last - timedelta(hours=2)
    assert window.end == now
    assert "overlap" in reason


def test_window_is_clamped_to_configured_lookback():
    """A very old last-success must not silently request a year of data."""
    now = BASE + timedelta(days=400)
    window, reason = compute_sync_window(
        now=now,
        poll_interval_hours=24,
        lookback_days=30,
        last_success_end=BASE,
    )
    assert window.start == now - timedelta(days=30)
    assert "lookback" in reason


def test_window_extends_to_cover_a_known_gap():
    """A known gap older than the overlap pulls the window back to include it."""
    now = BASE + timedelta(days=10)
    last = now - timedelta(hours=2)
    gap_at = now - timedelta(days=4)
    window, reason = compute_sync_window(
        now=now,
        poll_interval_hours=1,
        lookback_days=30,
        last_success_end=last,
        earliest_known_gap=gap_at,
    )
    assert window.start == gap_at
    assert "oldest known gap" in reason


def test_window_never_inverts_when_last_success_is_in_the_future():
    """Clock skew must not produce a window that ends before it starts."""
    now = BASE
    window, _ = compute_sync_window(
        now=now,
        poll_interval_hours=6,
        lookback_days=30,
        last_success_end=now + timedelta(days=2),
    )
    assert window.start < window.end


# ─── Range algebra ───────────────────────────────────────────


def test_merge_adjacent_collapses_touching_ranges():
    merged = merge_adjacent(
        [
            TimeRange(BASE, BASE + timedelta(days=1)),
            TimeRange(BASE + timedelta(days=1), BASE + timedelta(days=2)),
            TimeRange(BASE + timedelta(days=5), BASE + timedelta(days=6)),
        ]
    )
    assert len(merged) == 2
    assert merged[0] == TimeRange(BASE, BASE + timedelta(days=2))


def test_subtract_returns_the_holes():
    outer = TimeRange(BASE, BASE + timedelta(days=10))
    holes = [TimeRange(BASE + timedelta(days=2), BASE + timedelta(days=4))]
    remaining = subtract(outer, holes)
    assert remaining == [
        TimeRange(BASE, BASE + timedelta(days=2)),
        TimeRange(BASE + timedelta(days=4), BASE + timedelta(days=10)),
    ]


def test_choose_bucket_seconds_scales_with_span():
    assert choose_bucket_seconds(TimeRange(BASE, BASE + timedelta(hours=6))) <= HOUR
    assert choose_bucket_seconds(TimeRange(BASE, BASE + timedelta(days=365))) >= DAY


def test_classify_buckets_uses_median_density():
    """A day with a handful of points among full days is partial, not full."""
    buckets = [
        BucketCount(BASE, BASE + timedelta(days=1), 24),
        BucketCount(BASE + timedelta(days=1), BASE + timedelta(days=2), 24),
        BucketCount(BASE + timedelta(days=2), BASE + timedelta(days=3), 3),
        BucketCount(BASE + timedelta(days=3), BASE + timedelta(days=4), 0),
    ]
    labels, expectation = classify_buckets(buckets)
    assert labels == ["full", "full", "partial", "empty"]
    assert expectation == 24


# ─── Coverage analysis ───────────────────────────────────────


@pytest.mark.asyncio
async def test_fully_covered_range_is_skipped():
    """Complete data means nothing needs importing."""
    points = [t for d in range(5) for t in _hourly(d)]
    window = TimeRange(BASE, BASE + timedelta(days=5))

    plan = await plan_import(_fetcher(points), window, coarse_bucket_seconds=DAY)

    assert plan.missing == []
    assert plan.recommended is None
    assert "already complete" in plan.reason
    assert plan.covered


@pytest.mark.asyncio
async def test_empty_range_is_imported_whole():
    window = TimeRange(BASE, BASE + timedelta(days=5))
    plan = await plan_import(_fetcher([]), window, coarse_bucket_seconds=DAY)

    assert plan.missing == [window]
    assert plan.recommended == window
    assert plan.covered == []


@pytest.mark.asyncio
async def test_trailing_gap_narrows_the_import_to_the_new_range():
    """The common case: history is present, only recent days are missing."""
    points = [t for d in range(5) for t in _hourly(d)]
    window = TimeRange(BASE, BASE + timedelta(days=8))

    plan = await plan_import(_fetcher(points), window, coarse_bucket_seconds=DAY)

    assert plan.recommended is not None
    assert plan.recommended.start == BASE + timedelta(days=5)
    assert plan.recommended.end == BASE + timedelta(days=8)
    assert "Only the new period" in plan.reason


@pytest.mark.asyncio
async def test_interior_gap_is_reported_and_not_skipped():
    """A hole in the middle must appear in missing, and must not be merged away."""
    points = [t for d in (0, 1, 2, 6, 7) for t in _hourly(d)]
    window = TimeRange(BASE, BASE + timedelta(days=8))

    plan = await plan_import(_fetcher(points), window, coarse_bucket_seconds=DAY)

    assert any(
        r.start == BASE + timedelta(days=3) and r.end == BASE + timedelta(days=6)
        for r in plan.missing
    ), plan.missing


@pytest.mark.asyncio
async def test_metric_coverage_requires_every_supported_metric():
    """Verifies Fizzbee Invariant: NeverSkipIncompleteMetric.

    A dense metric cannot make a range complete when another supported metric is
    absent. Completeness is the intersection of canonical metric coverage.
    """
    window = TimeRange(BASE, BASE + timedelta(days=5))
    metric_fetchers = {
        "steps": _fetcher([t for d in range(5) for t in _hourly(d)]),
        "energy_active": _fetcher([t for d in range(3) for t in _hourly(d)]),
    }

    plan = await plan_import(
        _fetcher([]),
        window,
        metric_fetchers=metric_fetchers,
        coverage_scope="metric_set",
        coarse_bucket_seconds=DAY,
    )

    assert plan.covered == [TimeRange(BASE, BASE + timedelta(days=3))]
    assert plan.recommended == TimeRange(BASE + timedelta(days=3), window.end)
    assert plan.coverage_metrics == ["energy_active", "steps"]


@pytest.mark.asyncio
async def test_unknown_metric_contract_replans_the_whole_window():
    """Verifies Fizzbee Invariant: UnknownCoverageImports.

    Without a supported-metric/schema contract, existing aggregate density is not
    evidence that every metric was imported.
    """
    window = TimeRange(BASE, BASE + timedelta(days=2))
    full_points = [t for d in range(2) for t in _hourly(d)]

    plan = await plan_import(
        _fetcher(full_points),
        window,
        coverage_scope="unknown",
        coverage_reason="Coverage contract changed; revalidate the window.",
        coarse_bucket_seconds=DAY,
    )

    assert plan.covered == []
    assert plan.missing == [window]
    assert plan.recommended == window
    assert plan.confidence == "low"
    assert plan.reason.startswith("Coverage contract changed")


@pytest.mark.asyncio
async def test_partial_day_is_never_treated_as_covered():
    """A day with only a few points must not be skipped.

    This is the safety rule: skipping a partially-imported day would lose the rest
    of it permanently.
    """
    points = _hourly(0) + _hourly(1, hours=4)
    window = TimeRange(BASE, BASE + timedelta(days=2))

    plan = await plan_import(_fetcher(points), window, coarse_bucket_seconds=DAY)

    day_two = BASE + timedelta(days=1)
    assert any(r.end > day_two for r in plan.missing), plan.missing


@pytest.mark.asyncio
async def test_heavily_fragmented_data_falls_back_to_full_import():
    """Alternating present/absent days are not safe to reason about in blocks."""
    points = [t for d in range(0, 40, 2) for t in _hourly(d)]
    window = TimeRange(BASE, BASE + timedelta(days=40))

    plan = await plan_import(_fetcher(points), window, coarse_bucket_seconds=DAY)

    assert plan.confidence == "low"
    assert plan.missing == [window]
    assert "too irregular" in plan.reason


@pytest.mark.asyncio
async def test_force_mode_skips_nothing_and_warns():
    """Force must re-process everything and say why that costs more."""
    points = [t for d in range(5) for t in _hourly(d)]
    window = TimeRange(BASE, BASE + timedelta(days=5))

    plan = await plan_import(
        _fetcher(points), window, mode="force", coarse_bucket_seconds=DAY
    )

    assert plan.mode == "force"
    assert plan.covered == []
    assert plan.missing == [window]
    assert plan.recommended == window
    assert "costs the work" in plan.reason


@pytest.mark.asyncio
async def test_boundary_is_refined_below_the_coarse_grid():
    """A half-full boundary day resolves to sub-day precision.

    Without refinement the reported boundary would snap to the day grid and either
    re-import a full covered day or skip half an empty one.
    """
    points = [t for d in range(3) for t in _hourly(d)] + _hourly(3, hours=12)
    window = TimeRange(BASE, BASE + timedelta(days=5))

    covered, missing, confidence, _expectation, _total = await analyse_coverage(
        _fetcher(points), window, coarse_bucket_seconds=DAY
    )

    assert confidence == "high"
    assert covered, "expected at least one covered block"
    boundary = covered[-1].end
    day_three = BASE + timedelta(days=3)
    # The boundary moved past the last full day but not to the end of the partial one.
    assert day_three <= boundary < day_three + timedelta(days=1)
    assert missing and missing[0].start == boundary


# ─── Gap detection ───────────────────────────────────────────


def test_detect_expected_interval_is_robust_to_one_outage():
    """A single long gap must not inflate the cadence estimate."""
    points = [BASE + timedelta(hours=h) for h in range(12)]
    points += [BASE + timedelta(days=5) + timedelta(hours=h) for h in range(12)]
    assert detect_expected_interval(points) == pytest.approx(HOUR)


def test_detect_expected_interval_needs_enough_samples():
    assert detect_expected_interval([BASE]) is None
    assert detect_expected_interval([]) is None


def test_find_gaps_reports_interior_outage():
    points = [BASE + timedelta(hours=h) for h in range(6)]
    points += [BASE + timedelta(hours=h) for h in range(20, 26)]
    window = TimeRange(BASE, BASE + timedelta(hours=26))

    gaps = find_gaps(points, window, expected_interval_seconds=HOUR)

    assert len(gaps) == 1
    assert gaps[0].start == BASE + timedelta(hours=5)
    assert gaps[0].end == BASE + timedelta(hours=20)


def test_find_gaps_tolerates_jitter():
    """Slightly irregular sampling is normal and must not be reported as loss."""
    points = [BASE + timedelta(minutes=5 * i + (i % 2)) for i in range(40)]
    window = TimeRange(points[0], points[-1])

    assert find_gaps(points, window) == []


def test_find_gaps_on_empty_series_returns_the_whole_window():
    window = TimeRange(BASE, BASE + timedelta(days=1))
    assert find_gaps([], window) == [window]


def test_find_gaps_flags_leading_and_trailing_absence():
    points = [BASE + timedelta(days=1) + timedelta(hours=h) for h in range(6)]
    window = TimeRange(BASE, BASE + timedelta(days=3))

    gaps = find_gaps(points, window, expected_interval_seconds=HOUR)

    assert gaps[0].start == BASE
    assert gaps[-1].end == BASE + timedelta(days=3)
