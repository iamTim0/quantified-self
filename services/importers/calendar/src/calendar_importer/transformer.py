"""Transform calendar occurrences into canonical ingestion events.

The previous transformer emitted only ``calendar_busy_minutes`` while the docs
promised ``calendar_event_count``, ``calendar_busy_hours`` and
``calendar_meeting_duration_minutes``. It also passed the raw ``start`` value
straight through and fell back to ``datetime.now()`` when it was missing, which
produced a different idempotency key on every sync and therefore a duplicate row
every time.

Timestamps are now always normalised UTC instants, and the idempotency key is
derived from the event's stable identity (UID plus recurrence id), so re-importing
the same occurrence is genuinely a no-op.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from calendar_importer.ics import CalendarEvent

SOURCE_TYPE = "calendar"


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4."""
    raw = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event(
    *,
    tenant_id: str,
    source_id: str,
    metric_type: str,
    timestamp: datetime,
    value: float,
    metadata: dict[str, Any],
    key_source_id: str | None = None,
) -> dict[str, Any]:
    iso = timestamp.astimezone(timezone.utc).isoformat()
    return {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "source_type": SOURCE_TYPE,
        "metric_type": metric_type,
        "timestamp": iso,
        "value": float(value),
        "metadata": {"source_type": SOURCE_TYPE, **metadata},
        "idempotency_key": generate_idempotency_key(
            tenant_id, key_source_id or source_id, metric_type, iso
        ),
    }


def transform_events(
    events: Sequence[CalendarEvent], tenant_id: str, source_id: str
) -> list[dict[str, Any]]:
    """Build per-occurrence and per-day metrics from expanded calendar events.

    Per-occurrence metrics use the occurrence's own identity in the idempotency
    key, so two different meetings starting at the same minute do not collide —
    which a timestamp-only key would cause.
    """
    out: list[dict[str, Any]] = []
    busy_minutes_per_day: dict[str, float] = defaultdict(float)
    count_per_day: dict[str, int] = defaultdict(int)

    for event in events:
        occurrence_id = f"{source_id}_{event.uid}"
        if event.recurrence_id:
            occurrence_id = f"{occurrence_id}_{event.recurrence_id}"

        out.append(
            _event(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type="calendar_meeting_duration_minutes",
                timestamp=event.start,
                value=event.duration_minutes,
                metadata={
                    "uid": event.uid,
                    "summary": event.summary,
                    "all_day": event.all_day,
                    "busy": event.counts_as_busy,
                    "status": event.status,
                    "has_location": event.location_present,
                    "end": event.end.astimezone(timezone.utc).isoformat(),
                },
                key_source_id=occurrence_id,
            )
        )

        day = event.start.astimezone(timezone.utc).date().isoformat()
        count_per_day[day] += 1
        if event.counts_as_busy:
            busy_minutes_per_day[day] += event.duration_minutes

    for day, count in sorted(count_per_day.items()):
        midnight = datetime.fromisoformat(f"{day}T00:00:00+00:00")
        out.append(
            _event(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type="calendar_event_count",
                timestamp=midnight,
                value=count,
                metadata={"day": day},
            )
        )
        minutes = busy_minutes_per_day.get(day, 0.0)
        out.append(
            _event(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type="calendar_busy_minutes",
                timestamp=midnight,
                value=minutes,
                metadata={"day": day},
            )
        )
        out.append(
            _event(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type="calendar_busy_hours",
                timestamp=midnight,
                value=round(minutes / 60.0, 4),
                metadata={"day": day},
            )
        )

    return out


def transform(
    records: list[dict[str, Any]], tenant_id: str, source_id: str
) -> list[dict[str, Any]]:
    """Backwards-compatible entry point for pre-parsed JSON records.

    Retained because a provider that exposes JSON rather than ICS still needs a
    path, and because the existing e2e suite calls it.
    """
    events: list[dict[str, Any]] = []
    for record in records:
        raw_start = record.get("start")
        if not raw_start:
            # No timestamp means no deterministic key; skip rather than invent
            # one from the current time, which used to duplicate on every sync.
            continue
        try:
            timestamp = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        metric = str(record.get("metric_type") or "calendar_busy_minutes")
        raw_value = record.get("duration_minutes", record.get("value"))
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        events.append(
            _event(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type=metric,
                timestamp=timestamp,
                value=value,
                metadata={},
            )
        )
    return events
