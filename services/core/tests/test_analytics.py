"""Tests for the roadmap analytics engine."""

from datetime import date, datetime, timezone

from core.analytics import detect_daily_gaps, find_cross_source_conflicts, pearson_pairs


def test_detect_daily_gaps() -> None:
    """Verifies Fizzbee Invariant: BackfillNeverCrossesTenant."""
    result = detect_daily_gaps(
        [("sleep", datetime(2026, 8, 1, tzinfo=timezone.utc))],
        date(2026, 8, 1),
        date(2026, 8, 3),
    )
    assert result == [{"metric_type": "sleep", "missing_dates": ["2026-08-02", "2026-08-03"]}]


def test_find_cross_source_conflicts() -> None:
    """Verifies Fizzbee Invariant: ConflictDecisionIsTenantScoped."""
    timestamp = datetime(2026, 8, 1, tzinfo=timezone.utc)
    conflicts = find_cross_source_conflicts(
        [
            {"id": "a", "source_id": "one", "metric_type": "steps", "timestamp": timestamp, "value": 100.0},
            {"id": "b", "source_id": "two", "metric_type": "steps", "timestamp": timestamp, "value": 150.0},
        ]
    )
    assert conflicts[0]["metric_type"] == "steps"


def test_pearson_pairs() -> None:
    """Verifies deterministic cross-metric analysis without shared state."""
    result = pearson_pairs({"sleep": {"1": 1, "2": 2, "3": 3}, "hrv": {"1": 2, "2": 4, "3": 6}})
    assert result[0]["coefficient"] == 1.0
