"""Tests for calendar event transformation into ingestion events.

Maps to Fizzbee Invariants:
- NoDuplicateRecords
- IdempotencyKeyDeterministic
"""

from datetime import datetime, timedelta, timezone

from calendar_importer.ics import CalendarEvent
from calendar_importer.transformer import transform_events
from shared_schemas.metrics import canonical_metric_type

TENANT = "tenant-1"
SOURCE = "source-1"


def _event(uid: str, hour: int, minutes: int = 60, **kwargs) -> CalendarEvent:
    start = datetime(2026, 8, 5, hour, 0, tzinfo=timezone.utc)
    return CalendarEvent(
        uid=uid,
        summary=kwargs.pop("summary", uid),
        start=start,
        end=start + timedelta(minutes=minutes),
        all_day=kwargs.pop("all_day", False),
        **kwargs,
    )


def test_emits_the_documented_metric_names():
    """Every emitted name is the registry's canonical one.

    `calendar_busy_hours` used to be here too: the same quantity as
    `calendar_busy_duration` in a different unit, which existed only because the unit
    lived in the metric name. The registry holds the unit now, so one metric is enough.
    """
    points = transform_events([_event("a", 9), _event("b", 14, 30)], TENANT, SOURCE)
    metrics = {p["metric_type"] for p in points}

    assert metrics == {
        "calendar_meeting_duration",
        "calendar_event_count",
        "calendar_busy_duration",
    }
    assert all(canonical_metric_type(m) == m for m in metrics)


def test_daily_aggregates_are_correct():
    points = transform_events([_event("a", 9, 60), _event("b", 14, 30)], TENANT, SOURCE)
    by_metric = {p["metric_type"]: p for p in points if p["metric_type"] != "calendar_meeting_duration"}

    assert by_metric["calendar_event_count"]["value"] == 2
    assert by_metric["calendar_busy_duration"]["value"] == 90


def test_transparent_events_count_but_do_not_occupy_time():
    points = transform_events(
        [_event("busy", 9, 60), _event("free", 11, 60, transparent=True)], TENANT, SOURCE
    )
    by_metric = {
        p["metric_type"]: p
        for p in points
        if p["metric_type"] != "calendar_meeting_duration"
    }

    assert by_metric["calendar_event_count"]["value"] == 2
    assert by_metric["calendar_busy_duration"]["value"] == 60


def test_idempotency_keys_are_deterministic():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic."""
    first = transform_events([_event("a", 9)], TENANT, SOURCE)
    second = transform_events([_event("a", 9)], TENANT, SOURCE)

    assert [p["idempotency_key"] for p in first] == [
        p["idempotency_key"] for p in second
    ]


def test_two_meetings_at_the_same_instant_do_not_collide():
    """A timestamp-only key would merge these into one row."""
    points = transform_events([_event("a", 9), _event("b", 9)], TENANT, SOURCE)
    occurrence_keys = [
        p["idempotency_key"]
        for p in points
        if p["metric_type"] == "calendar_meeting_duration"
    ]

    assert len(occurrence_keys) == 2
    assert len(set(occurrence_keys)) == 2


def test_recurring_instances_get_distinct_keys():
    """Every occurrence of a series must be its own row."""
    base = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
    events = [
        CalendarEvent(
            uid="standup@example.test",
            summary="Standup",
            start=base + timedelta(weeks=w),
            end=base + timedelta(weeks=w, minutes=15),
            all_day=False,
        )
        for w in range(4)
    ]

    points = transform_events(events, TENANT, SOURCE)
    keys = [
        p["idempotency_key"]
        for p in points
        if p["metric_type"] == "calendar_meeting_duration"
    ]

    assert len(set(keys)) == 4


def test_tenant_isolation_in_keys():
    """Verifies Fizzbee Invariant: TenantIsolation."""
    a = transform_events([_event("a", 9)], "tenant-a", SOURCE)
    b = transform_events([_event("a", 9)], "tenant-b", SOURCE)

    assert a[0]["idempotency_key"] != b[0]["idempotency_key"]
    assert a[0]["tenant_id"] == "tenant-a"


def test_events_carry_top_level_source_type():
    """shared_schemas.IngestEvent requires it; the old transformer omitted it."""
    points = transform_events([_event("a", 9)], TENANT, SOURCE)
    assert all(p["source_type"] == "calendar" for p in points)


def test_keys_are_stable_across_runs():
    """The same occurrence must produce the same key every sync (rule 4).

    This replaces a test of `transform()`, the JSON entry point removed with the
    calendar's API mode -- the importer never called it, and the mode it existed
    for could not work.
    """
    events = [_event("a", 9), _event("b", 11)]

    first = transform_events(events, TENANT, SOURCE)
    second = transform_events(events, TENANT, SOURCE)

    assert [e["idempotency_key"] for e in first] == [e["idempotency_key"] for e in second]
