"""Tests for iCalendar parsing, recurrence expansion and timezone handling.

The calendar importer previously had no ICS support at all: it GET'd
``{base_url}/events`` and called ``.json()``, so a real ``text/calendar`` feed
raised and the error was swallowed. These tests cover the replacement against
real ICS documents.

Maps to Fizzbee Invariants:
- NoDuplicateRecords
- IdempotencyKeyDeterministic
"""

from datetime import datetime, timezone

import pytest
from calendar_importer.ics import IcsParseError, parse_ics

WINDOW_START = datetime(2026, 8, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _cal(*body: str) -> str:
    return "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN", *body, "END:VCALENDAR"]
    )


SIMPLE_EVENT = _cal(
    "BEGIN:VEVENT",
    "UID:event-1@example.test",
    "SUMMARY:Design review",
    "DTSTART:20260805T090000Z",
    "DTEND:20260805T100000Z",
    "END:VEVENT",
)


def test_parses_a_single_timed_event():
    events = parse_ics(SIMPLE_EVENT, window_start=WINDOW_START, window_end=WINDOW_END)

    assert len(events) == 1
    event = events[0]
    assert event.uid == "event-1@example.test"
    assert event.summary == "Design review"
    assert event.start == datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
    assert event.duration_minutes == 60
    assert event.all_day is False
    assert event.counts_as_busy is True


def test_rejects_a_non_calendar_payload():
    """An HTML login page must not parse as an empty calendar."""
    with pytest.raises(IcsParseError):
        parse_ics(
            "<html><body>Please sign in</body></html>",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
        )


def test_rejects_truncated_calendar():
    with pytest.raises(IcsParseError):
        parse_ics("BEGIN:VCAL", window_start=WINDOW_START, window_end=WINDOW_END)


def test_expands_a_weekly_recurring_event():
    """A weekly standup must produce one occurrence per week, not one event.

    With the old code a recurring series collapsed to a single record whose
    idempotency key was identical for every instance.
    """
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:standup@example.test",
        "SUMMARY:Standup",
        "DTSTART:20260803T080000Z",
        "DTEND:20260803T081500Z",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)

    # Mondays in August 2026: 3, 10, 17, 24, 31
    assert len(events) == 5
    assert [e.start.day for e in events] == [3, 10, 17, 24, 31]
    assert all(e.duration_minutes == 15 for e in events)


def test_honours_exdate_exclusions():
    """A cancelled occurrence of a series must not be imported."""
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:standup@example.test",
        "SUMMARY:Standup",
        "DTSTART:20260803T080000Z",
        "DTEND:20260803T081500Z",
        "RRULE:FREQ=WEEKLY;BYDAY=MO",
        "EXDATE:20260810T080000Z",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)

    assert [e.start.day for e in events] == [3, 17, 24, 31]


def test_recurrence_id_override_replaces_the_instance():
    """A moved occurrence uses its override, not the series default."""
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:series@example.test",
        "SUMMARY:Weekly sync",
        "DTSTART:20260803T080000Z",
        "DTEND:20260803T090000Z",
        "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=3",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:series@example.test",
        "RECURRENCE-ID:20260810T080000Z",
        "SUMMARY:Weekly sync (moved)",
        "DTSTART:20260810T140000Z",
        "DTEND:20260810T150000Z",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)
    moved = [e for e in events if e.start.day == 10]

    assert len(moved) == 1
    assert moved[0].start.hour == 14
    assert "moved" in moved[0].summary


def test_resolves_tzid_to_utc():
    """A Europe/Berlin event in August is UTC+2."""
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:berlin@example.test",
        "SUMMARY:Berlin meeting",
        "DTSTART;TZID=Europe/Berlin:20260805T100000",
        "DTEND;TZID=Europe/Berlin:20260805T110000",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)

    assert events[0].start == datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)


def test_all_day_event_is_anchored_in_the_display_timezone():
    """"Was I busy on Tuesday" is a local question, not a UTC one."""
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:holiday@example.test",
        "SUMMARY:Public holiday",
        "DTSTART;VALUE=DATE:20260815",
        "DTEND;VALUE=DATE:20260816",
        "END:VEVENT",
    )

    events = parse_ics(
        ics,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        display_timezone="Europe/Berlin",
    )

    assert len(events) == 1
    assert events[0].all_day is True
    # Midnight Berlin on the 15th is 22:00 UTC on the 14th.
    assert events[0].start == datetime(2026, 8, 14, 22, 0, tzinfo=timezone.utc)
    assert events[0].duration_minutes == pytest.approx(24 * 60)


def test_floating_time_uses_the_display_timezone():
    """A DTSTART with no zone and no Z is local time, per RFC 5545."""
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:floating@example.test",
        "SUMMARY:Floating",
        "DTSTART:20260805T090000",
        "DTEND:20260805T100000",
        "END:VEVENT",
    )

    events = parse_ics(
        ics,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        display_timezone="Europe/Berlin",
    )

    assert events[0].start == datetime(2026, 8, 5, 7, 0, tzinfo=timezone.utc)


def test_unknown_timezone_falls_back_to_utc_without_crashing():
    events = parse_ics(
        SIMPLE_EVENT,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        display_timezone="Mars/Olympus_Mons",
    )
    assert events[0].start == datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


def test_cancelled_event_is_parsed_but_not_busy():
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:cancelled@example.test",
        "SUMMARY:Cancelled thing",
        "DTSTART:20260805T090000Z",
        "DTEND:20260805T100000Z",
        "STATUS:CANCELLED",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)
    assert events[0].counts_as_busy is False


def test_transparent_event_does_not_count_as_busy():
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:free@example.test",
        "SUMMARY:Reminder",
        "DTSTART:20260805T090000Z",
        "DTEND:20260805T100000Z",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)
    assert events[0].counts_as_busy is False


def test_duration_is_used_when_dtend_is_absent():
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:dur@example.test",
        "SUMMARY:With duration",
        "DTSTART:20260805T090000Z",
        "DURATION:PT45M",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)
    assert events[0].duration_minutes == 45


def test_events_outside_the_window_are_excluded():
    """An incremental sync must not re-read years of history."""
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:old@example.test",
        "SUMMARY:Ancient",
        "DTSTART:20200101T090000Z",
        "DTEND:20200101T100000Z",
        "END:VEVENT",
    )

    assert parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END) == []


def test_backwards_event_is_repaired_not_dropped():
    """A VEVENT whose DTEND precedes DTSTART is normalised, not discarded.

    recurring_ical_events swaps the two, which is the more useful behaviour: the
    entry still occupies that hour of the person's day. What matters downstream is
    that the duration is never negative, since it feeds busy-time sums.
    """
    ics = _cal(
        "BEGIN:VEVENT",
        "UID:good@example.test",
        "SUMMARY:Good",
        "DTSTART:20260805T090000Z",
        "DTEND:20260805T100000Z",
        "END:VEVENT",
        "BEGIN:VEVENT",
        "UID:backwards@example.test",
        "SUMMARY:Ends before it starts",
        "DTSTART:20260806T100000Z",
        "DTEND:20260806T090000Z",
        "END:VEVENT",
    )

    events = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)

    assert {e.uid for e in events} == {"good@example.test", "backwards@example.test"}
    assert all(e.duration_minutes >= 0 for e in events)
    assert all(e.end >= e.start for e in events)


def test_event_without_uid_still_gets_stable_identity():
    ics = _cal(
        "BEGIN:VEVENT",
        "SUMMARY:No UID",
        "DTSTART:20260805T090000Z",
        "DTEND:20260805T100000Z",
        "END:VEVENT",
    )

    first = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)
    second = parse_ics(ics, window_start=WINDOW_START, window_end=WINDOW_END)

    assert first[0].uid == second[0].uid
