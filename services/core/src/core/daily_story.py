"""One day, assembled as something a person can read.

The overview page showed whole-history averages in a grid of cards: the mean of
every step count ever recorded, next to the mean of every sleep score ever
recorded. That answers a question nobody asks. What a reader wants in the morning
is what happened — last night, then yesterday, then today so far.

**Yesterday is complete and today is not, and the difference is stated rather
than hidden.** Yesterday's importers have run; today's may not have. A page that
renders both the same way invites the reader to read a gap as a fact — "no
workout today" when the truth is "the workout connector last ran at 06:00". Each
lane therefore carries `complete`, derived from whether that connector's most
recent successful import covers the end of the window being shown.

**Local days, not UTC days.** Day rollups are bucketed with `date_trunc('day')`
in UTC (`core.rollups`), so for a reader at UTC+2 a rollup "day" runs 22:00 to
22:00 and a meal at 23:30 belongs to the wrong one. `/api/v1/data/metrics` takes
no timezone at all. This module takes the reader's offset and computes the UTC
window their calendar day actually spans, which is the whole reason it is a
separate endpoint rather than a client assembling `/metrics` calls.

**One source answers per metric.** Two connectors reporting `steps` produce two
buckets for the same day, and the REST path had no guidance on which to believe —
the resolution existed only over gRPC. It reuses `core.reports.resolve_primary_source`
here, so the story and the analysis cannot disagree about which connector spoke.

**Sessions are regrouped, not exploded.** A workout is stored as a fan of
metrics sharing a timestamp and a `workout_name`; a meal is an item with a
`food_name`. Presenting those as twelve unrelated numbers is what made the old
page a card collection. They are grouped back into events here, where the
metadata that joins them is already in hand.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from shared_schemas.metrics import Aggregation, MetricCategory, describe
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import DataPoint, DataSource, SyncRun
from core.reports import (
    REASON_ONLY_SOURCE,
    metric_source_coverage,
    primary_source_preferences,
    resolve_primary_source,
)
from core.sessions import END_FIELDS, STREAM_METRICS, session_group_key, session_title

logger = logging.getLogger(__name__)

#: Metrics that describe a moment rather than a day, and can therefore be shown
#: on a timeline. Everything else is a daily figure.
EVENT_PREFIXES = ("workout_", "strength_set_", "strength_session_")
EVENT_METRICS = frozenset({
    "nutrition_item_energy",
    "nutrition_meal_energy",
    "calendar_meeting_duration",
})

#: How many discrete events one day may contribute. A day with a GPS trace and
#: per-minute samples can hold tens of thousands of rows; a timeline that tried
#: to render them all would hang the browser to say nothing extra.
MAX_EVENTS = 200

#: Rows the event scan may read. Bounded separately from the event count
#: because one session contributes a dozen rows, and a flag that only knew
#: about the event cap could not report a scan cut short by the row cap.
MAX_EVENT_ROWS = MAX_EVENTS * 20

#: The lanes a day is told in, in the order a day happens.
LANE_ORDER: tuple[MetricCategory, ...] = (
    MetricCategory.SLEEP,
    MetricCategory.ACTIVITY,
    MetricCategory.WORKOUT,
    MetricCategory.STRENGTH,
    MetricCategory.HEART,
    MetricCategory.NUTRITION,
    MetricCategory.BODY,
    MetricCategory.LOCATION,
    MetricCategory.CALENDAR,
    MetricCategory.ENVIRONMENT,
    MetricCategory.HOME,
    # Last, but present: a metric adopted under the `custom_` namespace is a
    # metric the workspace deliberately created, and leaving it out of the
    # order silently dropped it from the day after aggregating it.
    MetricCategory.CUSTOM,
)


@dataclass(frozen=True)
class DayWindow:
    """The UTC span of one calendar day as the reader experiences it."""

    day: date
    start: datetime
    end: datetime
    offset_minutes: int

    @property
    def is_today(self) -> bool:
        reader_now = datetime.now(timezone.utc) + timedelta(minutes=self.offset_minutes)
        return reader_now.date() == self.day


def day_window(day: date, offset_minutes: int) -> DayWindow:
    """The UTC window a reader's calendar day covers.

    A fixed offset rather than an IANA zone, because that is what a browser can
    state without being asked: `-new Date().getTimezoneOffset()`. It is wrong
    only across a DST boundary within the same day, which shifts that one day's
    window by an hour — visible, bounded, and better than being wrong by a whole
    day everywhere, which is what UTC buckets do.
    """
    shift = timedelta(minutes=offset_minutes)
    local_midnight = datetime.combine(day, time.min)
    start = (local_midnight - shift).replace(tzinfo=timezone.utc)
    return DayWindow(
        day=day, start=start, end=start + timedelta(days=1), offset_minutes=offset_minutes
    )


def _is_event_metric(metric_type: str) -> bool:
    if metric_type in STREAM_METRICS:
        return False
    return metric_type in EVENT_METRICS or metric_type.startswith(EVENT_PREFIXES)


def _event_metric_predicate():
    """The same rule as `_is_event_metric`, expressed for the database.

    Kept next to it so the two cannot drift: a metric the Python helper counts as
    an event and the SQL one does not would simply never reach the timeline.
    """
    return or_(
        DataPoint.metric_type.in_(sorted(EVENT_METRICS)),
        # `startswith(..., autoescape=True)`, not `like(f"{prefix}%")`: `_` is a
        # single-character wildcard in SQL, so a plain LIKE on `strength_set_`
        # also matches names the Python rule rejects. No registry key collides
        # today, which is exactly how a filter drifts from the rule it mirrors.
        *(
            DataPoint.metric_type.startswith(prefix, autoescape=True)
            for prefix in EVENT_PREFIXES
        ),
    )


def _stream_metric_predicate():
    """Intra-session series, which belong to neither half of a day story.

    `workout_heart_rate` begins with `workout_`, so the prefix rule above would
    call it an event — and a 90-minute workout at second resolution is 5,400 rows
    against `MAX_EVENT_ROWS`, so the timeline would come back truncated for anyone
    who trains, with `event_limit_reached` set and nothing else to show for it.

    Exact names, not a prefix, so the `_`-is-a-wildcard trap does not arise.
    """
    return DataPoint.metric_type.in_(sorted(STREAM_METRICS))


def _category_of(metric_type: str) -> str:
    try:
        return describe(metric_type).category.value
    except ValueError:
        return MetricCategory.CUSTOM.value


def _collapse(metric_type: str, values: list[float]) -> float:
    """Several readings of one metric within one session, as a single figure.

    By the registry's own aggregation, because the right answer differs per metric
    and guessing produces a plausible wrong one: the heaviest set is a `max`, the
    session's reps are a `sum`, its pulse is an `average`. A metric the registry
    does not know averages, which is the choice that invents the least.
    """
    if not values:
        return 0.0
    try:
        aggregation = describe(metric_type).aggregation
    except ValueError:
        return sum(values) / len(values)
    if aggregation is Aggregation.SUM:
        return sum(values)
    if aggregation is Aggregation.MAX:
        return max(values)
    if aggregation is Aggregation.LAST:
        return values[-1]
    return sum(values) / len(values)


async def metric_totals(
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    *,
    exclude=None,
) -> dict[str, dict[str, Any]]:
    """One number per metric over a window, aggregated in SQL.

    Grouped by source as well as metric, because two connectors reporting the
    same metric must not be added together — that is rule 19's double count. The
    winner is picked afterwards by the same rule the analysis uses.

    Takes a bare window rather than a `DayWindow` so the workout detail can ask
    the same question about a 45-minute run that the day story asks about a day.
    Sharing the function is the point: the two pages must not name different
    connectors for the same number, and they cannot if there is one query.
    """
    predicates = list(exclude or ())
    rows = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.source_id,
                func.sum(DataPoint.value).label("sum_value"),
                func.avg(DataPoint.value).label("avg_value"),
                func.max(DataPoint.value).label("max_value"),
                # The newest value, which `max` is not: a standing measurement
                # like body weight or a coordinate is meaningful only as its last
                # reading, and averaging a day of latitudes names a place the
                # reader was never at.
                (
                    func.array_agg(
                        aggregate_order_by(DataPoint.value, DataPoint.timestamp.desc())
                    )[1]
                ).label("last_value"),
                func.count(DataPoint.value).label("samples"),
                func.max(DataPoint.timestamp).label("last_at"),
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
                DataPoint.value.is_not(None),
                *predicates,
            )
            .group_by(DataPoint.metric_type, DataPoint.source_id)
        )
    ).all()

    by_metric: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_metric[row.metric_type][str(row.source_id)] = {
            "sum": float(row.sum_value) if row.sum_value is not None else None,
            "avg": float(row.avg_value) if row.avg_value is not None else None,
            "max": float(row.max_value) if row.max_value is not None else None,
            "last": float(row.last_value) if row.last_value is not None else None,
            "samples": int(row.samples or 0),
            "last_at": row.last_at,
        }
    return by_metric


async def _events(
    session: AsyncSession, tenant_id: str, window: DayWindow
) -> tuple[list[dict[str, Any]], bool]:
    """The day's discrete moments, and whether the scan was cut short.

    A workout arrives as a dozen metrics sharing one timestamp and one
    `workout_name`; that join key is the only thing tying them together, because
    the stored points carry no session identifier. Grouping on it here is what
    turns twelve numbers back into "a 45-minute run".
    """
    rows = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.timestamp,
                DataPoint.value,
                DataPoint.metadata_,
                DataPoint.source_id,
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= window.start,
                DataPoint.timestamp < window.end,
                # Filtered in SQL, not after the limit. Applying `limit` first and
                # then discarding non-event rows in Python meant a day whose early
                # hours held a GPS trace or per-minute heart rate spent the entire
                # budget before reaching the evening — the timeline came back short
                # or empty, and `event_limit_reached` stayed false because fewer
                # than MAX_EVENTS had been *grouped*. A quietly truncated timeline
                # is indistinguishable from a quiet day.
                _event_metric_predicate(),
                ~_stream_metric_predicate(),
            )
            .order_by(DataPoint.timestamp)
            # One more than the budget, so the caller can tell a scan that hit
            # its ceiling from one that simply ran out of events.
            .limit(MAX_EVENT_ROWS + 1)
        )
    ).all()

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        metadata = row.metadata_ or {}
        title = session_title(metadata)
        category = _category_of(row.metric_type)
        # One rule, in `core.sessions`, so the day timeline and the workout list
        # cannot disagree about what a session is. A point that carries a session
        # id groups by it; one that does not falls back to the timestamp-and-title
        # key this function has always used, unchanged.
        key = session_group_key(row.timestamp, metadata, category)
        event = grouped.setdefault(
            key,
            {
                "at": row.timestamp.isoformat(),
                "title": title,
                "category": category,
                "source_id": str(row.source_id),
                "measures": {},
                # How many points each figure stands on, so a collapsed measure is
                # auditable rather than indistinguishable from a stated one.
                "measure_counts": {},
                "_values": defaultdict(list),
            },
        )
        if row.value is not None:
            # Collected, then collapsed by the registry's own aggregation below.
            #
            # This used to add them up unconditionally, which was defensible while
            # a group was one instant — two foods logged in the same minute are two
            # things that happened. A group is now a whole session, and summing
            # eighteen `strength_set_weight` rows reports 1,850 kg as a set weight.
            # A wrong number is worse than a missing one, because nothing
            # distinguishes it from a right one (rule 19).
            event["_values"][row.metric_type].append(float(row.value))
            event["measure_counts"][row.metric_type] = (
                event["measure_counts"].get(row.metric_type, 0) + 1
            )
        # The end of the span, which is the difference between a moment and a
        # duration on the timeline. `session_end` leads: it is the provider's
        # statement about the session, where the others are per-point echoes of it.
        for field in END_FIELDS:
            if isinstance(metadata.get(field), str) and "until" not in event:
                event["until"] = metadata[field]
                break

    for event in grouped.values():
        for metric_type, values in event.pop("_values").items():
            event["measures"][metric_type] = _collapse(metric_type, values)

    events = sorted(grouped.values(), key=lambda item: item["at"])
    truncated = len(rows) > MAX_EVENT_ROWS or len(events) > MAX_EVENTS
    return events[:MAX_EVENTS], truncated


async def _lane_completeness(
    session: AsyncSession, tenant_id: str
) -> dict[str, datetime | None]:
    """When each connector last finished importing, keyed by connector id.

    A lane is only as current as the connector feeding it. Reporting a lane as
    empty when its importer has simply not run since breakfast turns a schedule
    into a finding, which is the mistake this whole page exists to stop making.
    """
    rows = (
        await session.execute(
            select(SyncRun.source_id, func.max(SyncRun.finished_at))
            .where(
                SyncRun.tenant_id == tenant_id,
                SyncRun.status == "success",
                SyncRun.source_id.is_not(None),
            )
            .group_by(SyncRun.source_id)
        )
    ).all()
    return {str(source_id): finished for source_id, finished in rows}


async def build_day_story(
    session: AsyncSession,
    tenant_id: str,
    *,
    day: date,
    offset_minutes: int,
) -> dict[str, Any]:
    """Everything one day holds, grouped into lanes and a timeline."""
    window = day_window(day, offset_minutes)

    totals = await metric_totals(
        session,
        tenant_id,
        window.start,
        window.end,
        exclude=(
            # Events belong on the timeline, not in a lane total: summing a day's
            # `workout_duration` across three sessions and printing it as a lane
            # figure says something the reader did not ask.
            ~_event_metric_predicate(),
            # Stated separately rather than folded into `_event_metric_predicate`.
            # Folding it in would invert to `not (event or stream)` there and to
            # `not event or not stream` here — true for every stream metric, so the
            # exclusion would silently do nothing and a workout's per-second pulse
            # would land in the heart lane as a daily average.
            ~_stream_metric_predicate(),
        ),
    )
    events, events_truncated = await _events(session, tenant_id, window)
    last_import_by_source = await _lane_completeness(session, tenant_id)

    # Only when something is actually ambiguous. Both scan the workspace's whole
    # rollup history, and `only_source` is the common case — a single-connector
    # workspace was paying for two full-history aggregations per day rendered,
    # four per page load, to answer a question it never asked.
    ambiguous = {metric for metric, sources in totals.items() if len(sources) > 1}
    preferences = (
        await primary_source_preferences(session, tenant_id) if ambiguous else {}
    )
    coverage = await metric_source_coverage(session, tenant_id) if ambiguous else {}
    source_types = {
        str(source_id): source_type
        for source_id, source_type in (
            await session.execute(
                select(DataSource.id, DataSource.source_type).where(
                    DataSource.tenant_id == tenant_id
                )
            )
        ).all()
    }

    lanes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric_type, by_source in totals.items():
        try:
            definition = describe(metric_type)
        except ValueError:
            continue

        source_ids = sorted(by_source)
        if len(source_ids) > 1:
            # The same rule the analysis uses, so the story and the analysis
            # cannot name different connectors for the same number.
            chosen, reason = resolve_primary_source_for(
                metric_type, source_ids, preferences, coverage
            )
        else:
            chosen, reason = source_ids[0], REASON_ONLY_SOURCE

        stats = by_source[chosen]
        if definition.aggregation is Aggregation.SUM:
            value = stats["sum"]
        elif definition.aggregation is Aggregation.MAX:
            value = stats["max"]
        elif definition.aggregation is Aggregation.LAST:
            value = stats["last"]
        else:
            value = stats["avg"]

        lanes[definition.category.value].append(
            {
                "metric_type": metric_type,
                "value": round(value, definition.precision) if value is not None else None,
                "unit": definition.unit.value,
                "aggregation": definition.aggregation.value,
                "cadence": definition.cadence.value,
                "sample_count": stats["samples"],
                "source_id": chosen,
                "source_type": source_types.get(chosen),
                # only_source, preference or coverage — identifiers, not prose.
                "source_reason": reason,
                "other_sources": [s for s in source_ids if s != chosen],
                "last_at": stats["last_at"].isoformat() if stats["last_at"] else None,
            }
        )

    ordered_lanes = []
    for category in LANE_ORDER:
        entries = lanes.get(category.value)
        if not entries:
            continue
        involved = {entry["source_id"] for entry in entries}
        # A lane is current when every connector feeding it finished an import
        # after the window closed. For today that window closes at tonight's
        # midnight, so a lane of today's is never `complete` — which is correct
        # and is why `last_import_at` is published beside it: that is the field
        # that says something useful about a day still in progress.
        # A connector that has never completed a run makes the lane unknown, not
        # current. Taking `min` over a `None`-last key returned the earliest
        # *known* import instead and silently ignored the silent connector — so a
        # lane fed by one working and one dead connector reported itself complete,
        # which is the "an import schedule read as a finding" failure this module
        # exists to prevent.
        stamps = [last_import_by_source.get(source_id) for source_id in involved]
        covered_through = None if any(stamp is None for stamp in stamps) else min(stamps)
        ordered_lanes.append(
            {
                "category": category.value,
                "metrics": sorted(entries, key=lambda entry: entry["metric_type"]),
                "last_import_at": covered_through.isoformat() if covered_through else None,
                "complete": bool(covered_through and covered_through >= window.end),
            }
        )

    return {
        "tenant_id": tenant_id,
        "day": day.isoformat(),
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "offset_minutes": offset_minutes,
        "is_today": window.is_today,
        # A day still in progress is never "complete", whatever the importers say.
        "complete": not window.is_today
        and all(lane["complete"] for lane in ordered_lanes)
        and bool(ordered_lanes),
        "lanes": ordered_lanes,
        "events": events,
        "event_limit_reached": events_truncated,
    }


def resolve_primary_source_for(
    metric_type: str,
    source_ids: list[str],
    preferences: dict[str, str],
    coverage: dict[tuple[str, str], int],
) -> tuple[str, str]:
    """Adapt the shared resolver to this module's coverage shape."""
    return resolve_primary_source(
        source_ids,
        preference=preferences.get(metric_type),
        coverage={
            source_id: coverage.get((metric_type, source_id), 0)
            for source_id in source_ids
        },
    )
