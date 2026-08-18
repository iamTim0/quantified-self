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
from sqlalchemy import Float, case, cast, func, or_, select
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

#: Metrics that describe a session — something trained, with a start and a span.
#: A session's per-second series is excluded separately (`STREAM_METRICS`).
#:
#: This is also the workout list's definition of its own subject, and it is a
#: narrower set than "anything that happened at a time" on purpose: while the two
#: were one set, `nutrition_item_energy` and `calendar_meeting_duration` were
#: grouped into sessions and returned by `/api/v1/data/workouts`, so every logged
#: food item and every meeting arrived as a workout — named, because
#: `sessions.TITLE_FIELDS` reads `food_name` and `summary` to title a card.
SESSION_PREFIXES = ("workout_", "strength_set_", "strength_session_")

#: Metrics that describe one scheduled moment of a day. On the timeline, because a
#: meeting did happen at a time; never in the workout list, because a meeting is
#: not something anyone trained.
MOMENT_METRICS = frozenset({"calendar_meeting_duration"})

#: Metrics recorded *for* a day rather than *at* a time.
#:
#: Yazio stamps every item of a day at that day's midnight UTC and keeps the real
#: clock time only in `metadata.logged_time`, which nothing reads. Rendered in the
#: reader's own zone that stamp becomes 02:00 in CEST — a day's entire food intake
#: piled into the small hours, which is not what happened and is not something a
#: reader can mentally correct for. So these are told as the day's log, in meal
#: order, and the timeline keeps only the hours it can actually vouch for.
#:
#: Re-stamping them in the importer would be the other fix and is the wrong one:
#: the timestamp is part of the idempotency key (rule 4), so changing it does not
#: correct the existing points, it duplicates every one of them.
LOGGED_METRICS = frozenset({
    "nutrition_item_energy",
    "nutrition_meal_energy",
})

#: Everything that describes a single entry rather than a whole day.
#:
#: This is the set a lane total must exclude: a day's `nutrition_item_energy` rows
#: summed into the nutrition lane double counts the `nutrition_energy` total the
#: provider already sends for that day (rule 19).
ENTRY_METRICS = MOMENT_METRICS | LOGGED_METRICS

#: How many discrete events one day may contribute. A day with a GPS trace and
#: per-minute samples can hold tens of thousands of rows; a timeline that tried
#: to render them all would hang the browser to say nothing extra.
MAX_EVENTS = 200

#: Rows the event scan may read. Bounded separately from the event count
#: because one session contributes a dozen rows, and a flag that only knew
#: about the event cap could not report a scan cut short by the row cap.
MAX_EVENT_ROWS = MAX_EVENTS * 20

#: Meal groups in the order a day eats them, so the day's log reads as a day
#: rather than alphabetically. Yazio's own `daytime` values, which is what
#: `metadata.meal_category` carries. Anything else keeps its own name and sorts
#: after these, rather than being dropped for being unrecognised.
MEAL_ORDER: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")

#: Entries the day's log may hold, and the rows the scan behind it may read.
#: A day of individually logged food is dozens of rows, not thousands; these exist
#: so one mis-tagged import cannot make the page unbounded.
MAX_LOGGED_ENTRIES = 200
MAX_LOGGED_ROWS = MAX_LOGGED_ENTRIES * 10

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
    MetricCategory.DEVELOPER,
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


def _metric_predicate(names: frozenset[str], prefixes: tuple[str, ...] = ()):
    """`metric_type` matches any of these names or prefixes, expressed for SQL.

    One helper for all four sets below, so the four cannot drift into four
    different readings of what a name match is.

    `startswith(..., autoescape=True)`, not `like(f"{prefix}%")`: `_` is a
    single-character wildcard in SQL, so a plain LIKE on `strength_set_` also
    matches names the Python rule rejects. No registry key collides today, which is
    exactly how a filter drifts from the rule it mirrors.
    """
    clauses = [
        DataPoint.metric_type.startswith(prefix, autoescape=True) for prefix in prefixes
    ]
    if names:
        clauses.append(DataPoint.metric_type.in_(sorted(names)))
    return or_(*clauses)


def entry_metric_predicate():
    """Anything describing one entry rather than a whole day.

    What a lane total excludes, and nothing else: the three narrower predicates
    below are what the timeline, the workout list and the day's log each ask for.
    """
    return _metric_predicate(ENTRY_METRICS, SESSION_PREFIXES)


def session_metric_predicate():
    """Only what can be a session — the workout list's definition of its subject."""
    return _metric_predicate(frozenset(), SESSION_PREFIXES)


def timeline_metric_predicate():
    """What may be placed at an hour: sessions and scheduled moments.

    Deliberately not `LOGGED_METRICS`. A stamp that only ever means "some time that
    day" renders as a precise hour once it reaches a timeline, and a precise wrong
    hour is worse than no hour, because nothing in the interface distinguishes it
    from one the provider actually stated.
    """
    return _metric_predicate(MOMENT_METRICS, SESSION_PREFIXES)


def logged_metric_predicate():
    """What was logged for a day, told as the day's log rather than at an hour."""
    return _metric_predicate(LOGGED_METRICS)


def _stream_metric_predicate():
    """Intra-session series, which belong to neither half of a day story.

    `workout_heart_rate` begins with `workout_`, so the prefix rule above would
    call it an event — and a 90-minute workout at second resolution is 5,400 rows
    against `MAX_EVENT_ROWS`, so the timeline would come back truncated for anyone
    who trains, with `event_limit_reached` set and nothing else to show for it.

    Exact names, not a prefix, so the `_`-is-a-wildcard trap does not arise.
    """
    return DataPoint.metric_type.in_(sorted(STREAM_METRICS))


def bucket_weight():
    """How many readings one stored point stands on, for a weighted mean.

    A minute bucket carrying the mean of sixty samples is not one reading. The
    ingest-side aggregator records that count as `bucket_samples` and `core.rollups`
    has always weighted by it — but every read path took a bare `avg()`, so a
    workout's average heart rate on the detail page and the same figure in
    `metric_rollups` were two different numbers derived from one dataset. A minute
    holding a single stray sample counted for as much as a minute holding sixty.

    `bucket_samples`, never `sample_count`. Only the first means "readings this mean
    averages"; the second is rule 19 provenance that importers also set on figures
    which are not means at all — WHOOP's zone shares carry the number of zone fields
    the payload held — and weighting by that produces an average nobody can account
    for.

    The `jsonb_typeof` guard sits in the `WHEN` and the cast in the `THEN`, so a
    metadata key holding something other than a number degrades to an unweighted
    reading rather than failing the cast for every row in the window. `greatest(…, 1)`
    mirrors `rollups`' own `> 0 else 1`, and guarantees a non-zero divisor.
    """
    stated = func.coalesce(
        case(
            (
                func.jsonb_typeof(DataPoint.metadata_.op("->")("bucket_samples")) == "number",
                cast(DataPoint.metadata_.op("->>")("bucket_samples"), Float),
            ),
            else_=None,
        ),
        1.0,
    )
    return func.greatest(stated, 1.0)


def weighted_average():
    """The mean of a window, weighted by what each point stands on."""
    weight = bucket_weight()
    return func.sum(DataPoint.value * weight) / func.sum(weight)


def _category_of(metric_type: str) -> str:
    try:
        return describe(metric_type).category.value
    except ValueError:
        return MetricCategory.CUSTOM.value


def _unit_of(metric_type: str) -> str:
    try:
        return describe(metric_type).unit.value
    except ValueError:
        return ""


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
                # Weighted, so this page and `metric_rollups` cannot report two
                # different averages for one metric over one window.
                weighted_average().label("avg_value"),
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
                timeline_metric_predicate(),
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


def _meal_rank(group: str) -> tuple[int, str]:
    """Where a meal group sorts. Unknown groups keep their name and come last."""
    try:
        return (MEAL_ORDER.index(group), "")
    except ValueError:
        return (len(MEAL_ORDER), group)


async def _logged_entries(
    session: AsyncSession, tenant_id: str, window: DayWindow
) -> tuple[list[dict[str, Any]], bool]:
    """What the day logged, grouped by meal, with no clock time invented for it.

    Yazio stamps every item of a day at that day's midnight UTC. Rendered in the
    reader's own zone that became 02:00 in CEST, so a day's entire food intake
    appeared on the timeline in the small hours — every item at the same wrong
    hour, which reads as a fact about the day rather than as an artefact of how the
    provider stamps a diary.

    So the day's log is its own section: ordered by meal, and carrying the real
    clock time only where the provider actually stated one (`metadata.logged_time`,
    which until now nothing read). A group whose points carry no such time is shown
    without one rather than with a plausible invention.
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
                logged_metric_predicate(),
            )
            .order_by(DataPoint.timestamp)
            .limit(MAX_LOGGED_ROWS + 1)
        )
    ).all()

    groups: dict[str, dict[str, Any]] = {}
    for row in rows[:MAX_LOGGED_ROWS]:
        metadata = row.metadata_ or {}
        name = str(metadata.get("meal_category") or "").strip().lower()
        group = groups.setdefault(
            name or "other",
            {
                # A stable identifier, not prose (rule 17): the dashboard renders it
                # through `nutrition.meal.<group>` and falls back to the raw name for
                # a group it does not know.
                "group": name or "other",
                "category": _category_of(row.metric_type),
                "source_id": str(row.source_id),
                "entries": [],
                # The meal total exactly as the provider stated it, kept apart from
                # the sum of the items below it. They are two different claims about
                # one meal and adding them together is rule 19's double count.
                "stated_energy": None,
                "item_energy": 0.0,
                "logged_at": None,
            },
        )
        value = float(row.value) if row.value is not None else None

        stated_time = metadata.get("logged_time")
        # The earliest real time anything in this meal carried. String compare,
        # because these are ISO-8601 from one provider and parsing them here would
        # only add a failure mode to an ordering hint.
        if (
            isinstance(stated_time, str)
            and stated_time
            and (group["logged_at"] is None or stated_time < group["logged_at"])
        ):
            group["logged_at"] = stated_time

        if row.metric_type == "nutrition_meal_energy":
            if value is not None:
                group["stated_energy"] = value
            continue

        if value is not None:
            group["item_energy"] += value
        group["entries"].append(
            {
                "title": session_title(metadata),
                "metric_type": row.metric_type,
                "value": value,
                "unit": _unit_of(row.metric_type),
                "source_id": str(row.source_id),
                "logged_at": stated_time if isinstance(stated_time, str) else None,
                "amount": metadata.get("amount"),
                "serving_unit": metadata.get("serving_unit"),
                "protein_g": metadata.get("protein_g"),
                "carbs_g": metadata.get("carbs_g"),
                "fat_g": metadata.get("fat_g"),
            }
        )

    ordered = sorted(groups.values(), key=lambda entry: _meal_rank(entry["group"]))
    kept = 0
    for group in ordered:
        group["entries"].sort(key=lambda entry: (entry["logged_at"] or "", entry["title"]))
        group["entry_count"] = len(group["entries"])
        stated = group.pop("stated_energy")
        summed = group.pop("item_energy")
        # What the provider said, where it said anything; our sum only otherwise —
        # and `energy_derived` is what lets a reader tell the two apart (rule 19).
        group["energy"] = stated if stated is not None else round(summed, 1)
        group["energy_derived"] = stated is None
        group["unit"] = _unit_of("nutrition_item_energy")
        kept += group["entry_count"]

    truncated = len(rows) > MAX_LOGGED_ROWS or kept > MAX_LOGGED_ENTRIES
    return ordered, truncated


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
            # An entry belongs to the timeline or to the day's log, not to a lane
            # total: summing a day's `workout_duration` across three sessions and
            # printing it as a lane figure says something the reader did not ask,
            # and summing its `nutrition_item_energy` rows double counts the
            # `nutrition_energy` the provider already states for that day.
            ~entry_metric_predicate(),
            # Stated separately rather than folded into `entry_metric_predicate`.
            # Folding it in would invert to `not (event or stream)` there and to
            # `not event or not stream` here — true for every stream metric, so the
            # exclusion would silently do nothing and a workout's per-second pulse
            # would land in the heart lane as a daily average.
            ~_stream_metric_predicate(),
        ),
    )
    events, events_truncated = await _events(session, tenant_id, window)
    logged, logged_truncated = await _logged_entries(session, tenant_id, window)
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
        # Told apart from `events` on purpose: these carry a day, not an hour, and
        # the separation is the whole reason a day's food no longer lands at 02:00.
        "logged": logged,
        "logged_limit_reached": logged_truncated,
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
