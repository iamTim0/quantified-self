"""Tests for the roadmap analytics engine."""

from datetime import date, datetime, timedelta, timezone

from core.analytics import detect_daily_gaps, find_cross_source_conflicts, pearson_pairs


def test_detect_daily_gaps() -> None:
    """Verifies Fizzbee Invariant: BackfillNeverCrossesTenant.

    `sleep_duration` rather than `sleep`: stored points always carry canonical
    names — Core rejects aliases on the ingest path — so a test using an alias was
    describing a state the database cannot be in.
    """
    result = detect_daily_gaps(
        [("sleep_duration", datetime(2026, 8, 1, tzinfo=timezone.utc))],
        date(2026, 8, 1),
        date(2026, 8, 3),
    )
    assert result == [
        {"metric_type": "sleep_duration", "missing_dates": ["2026-08-02", "2026-08-03"]}
    ]


def test_an_event_metric_never_reports_a_gap() -> None:
    """A rest day is not missing data.

    Judged against the calendar, `workout_duration` reported a gap for every day
    somebody did not train — which is most days, for most people, and made the
    whole gap list worthless.
    """
    result = detect_daily_gaps(
        [("workout_duration", datetime(2026, 8, 1, tzinfo=timezone.utc))],
        date(2026, 8, 1),
        date(2026, 8, 31),
    )
    assert result == []


def test_a_continuous_metric_is_not_judged_by_the_calendar() -> None:
    """A day is the wrong unit for something sampled every few minutes.

    These are judged against their observed cadence in `ingest_planning.find_gaps`
    instead; counting calendar days here would answer a question nobody asked.
    """
    result = detect_daily_gaps(
        [("heart_rate", datetime(2026, 8, 1, 12, tzinfo=timezone.utc))],
        date(2026, 8, 1),
        date(2026, 8, 5),
    )
    assert result == []


def test_a_continuous_metric_still_reports_an_interruption() -> None:
    """Leaving them out of the daily check must not mean leaving them unwatched.

    Heart rate and the eight weather series are all CONTINUOUS. Skipping them in
    `detect_daily_gaps` without this would have meant a watch that stopped syncing
    for a week reported nothing at all — a regression wearing the costume of a fix.
    """
    from core.analytics import detect_cadence_gaps
    from core.ingest_planning import TimeRange

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    hourly = [("heart_rate", start + timedelta(hours=n)) for n in range(6)]
    after_a_long_silence = [("heart_rate", start + timedelta(hours=48 + n)) for n in range(6)]

    gaps = detect_cadence_gaps(
        hourly + after_a_long_silence, TimeRange(start, start + timedelta(hours=54))
    )

    assert [g["metric_type"] for g in gaps] == ["heart_rate"]
    assert gaps[0]["missing_ranges"]


def test_an_event_metric_reports_no_cadence_gap_either() -> None:
    """Neither check may invent a gap for something that happens when it happens."""
    from core.analytics import detect_cadence_gaps
    from core.ingest_planning import TimeRange

    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert detect_cadence_gaps(
        [("workout_duration", start), ("workout_duration", start + timedelta(days=20))],
        TimeRange(start, start + timedelta(days=30)),
    ) == []


def test_days_are_bucketed_in_the_reader_s_timezone() -> None:
    """Bucketing on UTC made the edge of every window wrong.

    A reading taken at 00:30 in Berlin is 22:30 the previous day in UTC, so the day
    it belongs to looked empty and the day before looked covered — the first and
    last day of every window were systematically misreported.
    """
    berlin = timezone(timedelta(hours=2))
    midnight_thirty_local = datetime(2026, 8, 2, 0, 30, tzinfo=berlin)

    utc_view = detect_daily_gaps(
        [("steps", midnight_thirty_local)], date(2026, 8, 1), date(2026, 8, 2)
    )
    local_view = detect_daily_gaps(
        [("steps", midnight_thirty_local)],
        date(2026, 8, 1),
        date(2026, 8, 2),
        local_timezone=berlin,
    )

    assert utc_view[0]["missing_dates"] == ["2026-08-02"]
    assert local_view[0]["missing_dates"] == ["2026-08-01"]


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
