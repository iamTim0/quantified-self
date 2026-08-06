"""iCalendar (RFC 5545) parsing for the calendar importer.

The importer previously did a JSON ``GET {base_url}/events`` and called
``.json()`` on the result, which cannot read a calendar at all: an ICS feed
returns ``text/calendar``, so the parse raised and the exception was swallowed.
It also demanded a bearer token, so a plain public ``.ics`` URL was not even
expressible.

This module does the real thing:

* **Recurring events** are expanded, honouring ``RRULE``, ``EXDATE`` and
  ``RECURRENCE-ID`` overrides, so a weekly standup produces one occurrence per
  week rather than a single event whose idempotency key collides with itself.
* **Time zones** are resolved from ``DTSTART;TZID=`` and ``VTIMEZONE``. All-day
  events (``VALUE=DATE``) and floating times are anchored to a configurable
  display timezone rather than silently treated as UTC.
* **Malformed feeds** raise :class:`IcsParseError` instead of producing partial
  nonsense.

Nothing here logs a URL or its query string: a private tokenized feed URL *is*
the credential.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar
import recurring_ical_events

logger = logging.getLogger(__name__)

# Guard against a feed with an unbounded RRULE producing millions of instances.
MAX_OCCURRENCES = 10_000


class IcsParseError(ValueError):
    """Raised when a payload is not usable iCalendar data."""


@dataclass(frozen=True)
class CalendarEvent:
    """One concrete occurrence, already resolved to absolute UTC instants."""

    uid: str
    summary: str
    start: datetime
    end: datetime
    all_day: bool
    status: str | None = None
    transparent: bool = False
    recurrence_id: str | None = None
    location_present: bool = False

    @property
    def duration_minutes(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds() / 60.0)

    @property
    def counts_as_busy(self) -> bool:
        """Whether this occurrence should contribute to busy time.

        Cancelled events and those explicitly marked ``TRANSP:TRANSPARENT``
        (free) are real calendar entries but do not occupy the person.
        """
        if self.status and self.status.upper() == "CANCELLED":
            return False
        return not self.transparent


def _resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        logger.warning("Unknown timezone %r in calendar config; falling back to UTC.", name)
        return ZoneInfo("UTC")


def _to_utc(value: Any, display_tz: ZoneInfo, *, end_of_day: bool = False) -> datetime:
    """Normalise an ICS date/datetime to an absolute UTC instant.

    A bare ``DATE`` (all-day event) has no instant of its own; it is anchored in
    the viewer's timezone, because "was I busy on Tuesday" is a local question.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Floating time: RFC 5545 says interpret in local time.
            value = value.replace(tzinfo=display_tz)
        return value.astimezone(timezone.utc)

    if isinstance(value, date):
        anchor = time(0, 0) if not end_of_day else time(0, 0)
        local = datetime.combine(value, anchor, tzinfo=display_tz)
        return local.astimezone(timezone.utc)

    raise IcsParseError(f"Unsupported date value in calendar feed: {value!r}")


def parse_ics(
    payload: str | bytes,
    *,
    window_start: datetime,
    window_end: datetime,
    display_timezone: str = "UTC",
) -> list[CalendarEvent]:
    """Parse an ICS document and expand it over ``[window_start, window_end)``.

    Only occurrences inside the window are returned, so a feed containing years of
    history costs nothing extra for an incremental sync.
    """
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="replace")

    stripped = payload.lstrip("﻿ \r\n\t")
    if not stripped.upper().startswith("BEGIN:VCALENDAR"):
        raise IcsParseError("Response is not an iCalendar document (no BEGIN:VCALENDAR)")

    try:
        calendar = icalendar.Calendar.from_ical(stripped)
    except Exception as exc:  # icalendar raises a variety of types
        raise IcsParseError(f"Could not parse iCalendar document: {exc}") from exc

    display_tz = _resolve_timezone(display_timezone)

    try:
        # recurring_ical_events applies RRULE / EXDATE / RECURRENCE-ID for us.
        occurrences = recurring_ical_events.of(calendar).between(window_start, window_end)
    except Exception as exc:
        raise IcsParseError(f"Could not expand recurring events: {exc}") from exc

    events: list[CalendarEvent] = []
    for component in occurrences:
        if component.name != "VEVENT":
            continue
        if len(events) >= MAX_OCCURRENCES:
            logger.warning(
                "Calendar feed produced more than %d occurrences; truncating.",
                MAX_OCCURRENCES,
            )
            break

        try:
            event = _build_event(component, display_tz)
        except IcsParseError as exc:
            # One broken VEVENT must not discard the rest of the calendar.
            logger.warning("Skipping unusable calendar entry: %s", exc)
            continue
        if event is not None:
            events.append(event)

    events.sort(key=lambda e: (e.start, e.uid))
    return events


def _build_event(component: Any, display_tz: ZoneInfo) -> CalendarEvent | None:
    dtstart = component.get("DTSTART")
    if dtstart is None:
        raise IcsParseError("VEVENT without DTSTART")

    raw_start = dtstart.dt
    all_day = isinstance(raw_start, date) and not isinstance(raw_start, datetime)
    start = _to_utc(raw_start, display_tz)

    dtend = component.get("DTEND")
    if dtend is not None:
        end = _to_utc(dtend.dt, display_tz, end_of_day=True)
    elif component.get("DURATION") is not None:
        duration = component.get("DURATION").dt
        if not isinstance(duration, timedelta):
            raise IcsParseError("VEVENT DURATION is not a duration")
        end = start + duration
    elif all_day:
        end = start + timedelta(days=1)
    else:
        # RFC 5545: a DTSTART-only timed event is zero length.
        end = start

    if end < start:
        raise IcsParseError("VEVENT ends before it starts")

    uid = str(component.get("UID") or "")
    if not uid:
        # Without a UID there is no stable identity; synthesise one from the
        # instant and summary so the idempotency key stays deterministic.
        uid = f"no-uid:{start.isoformat()}:{component.get('SUMMARY') or ''}"

    recurrence_id = component.get("RECURRENCE-ID")

    return CalendarEvent(
        uid=str(uid),
        summary=str(component.get("SUMMARY") or ""),
        start=start,
        end=end,
        all_day=all_day,
        status=str(component.get("STATUS")) if component.get("STATUS") else None,
        transparent=str(component.get("TRANSP") or "").upper() == "TRANSPARENT",
        recurrence_id=(
            _to_utc(recurrence_id.dt, display_tz).isoformat() if recurrence_id else None
        ),
        location_present=bool(component.get("LOCATION")),
    )
