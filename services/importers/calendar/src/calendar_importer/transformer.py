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

``calendar_busy_hours`` is gone. It carried the same number as
``calendar_busy_minutes`` in a different unit, purely because the unit lived in the
metric name -- the correlation analysis duly reported the two as perfectly correlated
series. The unit now lives in the registry
(packages/shared-schemas/src/shared_schemas/metrics.py), so one metric suffices and
the dashboard formats hours where hours read better.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from shared_schemas import idempotency_key
from shared_schemas.metrics import canonical_metric_type

from calendar_importer.ics import CalendarEvent

SOURCE_TYPE = "calendar"


#: SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4, defined once
#: in `shared_schemas`. An alias rather than a wrapper: a wrapper would be a fifth
#: identical docstring to keep in step, and its `timestamp: str` annotation would hide
#: that the shared function also takes a `datetime`.
generate_idempotency_key = idempotency_key


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
    metric_type = canonical_metric_type(metric_type)
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
                metric_type="calendar_meeting_duration",
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
        out.append(
            _event(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type="calendar_busy_duration",
                timestamp=midnight,
                value=busy_minutes_per_day.get(day, 0.0),
                metadata={"day": day},
            )
        )

    return out
