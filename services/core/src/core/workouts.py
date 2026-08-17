"""One workout, and everything that happened while it was happening.

The platform holds a workout's route, its sets, and the readings every other
connector took during it — and until now it could not put them on one page,
because a workout is not a row anywhere. It is a fan of points that share a
`session_id` (`shared_schemas.sessions`), or, for anything imported before that
existed, a timestamp and a title.

**The window is the join.** Once the session's span is known, everything else
follows from it: the Apple Watch's pulse, WHOOP's strain, Dawarich's trace, the
weather at the time. None of those know they belong to a workout, and none of them
need to — they were recorded between its start and its end, which is what "during
my workout" means. That is why the detail resolves a window first and queries it
second, and why a GPS trace whose session tag cannot be recovered (Apple Health's
webhook route fixes) still appears.

**Everything here is bounded by the session, not by the workspace.** A three-hour
ride and a twenty-minute run produce the same number of statements and the same
shape of response; the constants below are what make that true, and every one of
them reports when it bites. A quietly shortened answer is indistinguishable from a
short workout — the posture `MAX_EVENTS` / `event_limit_reached` already take in
`core.daily_story`.

Verified by `specs/workout_sessions.fizz`.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from shared_schemas.metrics import Cadence, MetricCategory, describe
from sqlalchemy import Float, and_, case, cast, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from core.daily_story import (
    _category_of,
    _collapse,
    _stream_metric_predicate,
    _unit_of,
    day_window,
    entry_metric_predicate,
    metric_totals,
    # The adapter, not the shared resolver underneath it: `metric_source_coverage`
    # is keyed by `(metric_type, source_id)` and the resolver wants a per-source
    # map, which is exactly what this converts. Calling the inner one directly
    # passed four positional arguments to a function taking one.
    resolve_primary_source_for,
    session_metric_predicate,
    weighted_average,
)
from core.db.models import DataPoint, DataSource
from core.reports import (
    REASON_ONLY_SOURCE,
    metric_source_coverage,
    primary_source_preferences,
)
from core.sessions import (
    END_FIELDS,
    STREAM_METRICS,
    TITLE_FIELDS,
    SessionRef,
    encode_session_key,
    session_group_key,
    session_title,
)

logger = logging.getLogger(__name__)

#: The longest span one session may cover. A workout mis-stamped with an end three
#: days after its start is a data problem, not a reason to scan three days: the
#: window is clamped and `window.clamped` says so, which the reader can act on where
#: a `400` would leave them nothing.
MAX_SESSION_HOURS = 12

#: Seconds added at each end. A watch's first GPS fix and its last heart-rate sample
#: routinely fall just outside the session the provider declares.
DEFAULT_PAD_SECONDS = 120
MAX_PAD_SECONDS = 900

#: Points a decimated stream may return, and the ceiling a caller may raise it to.
DEFAULT_STREAM_POINTS = 500
MAX_STREAM_POINTS = 2000

#: The same for a route. Higher, because a track's shape survives decimation worse
#: than a line chart's does.
DEFAULT_ROUTE_POINTS = 1000
MAX_ROUTE_POINTS = 5000

#: The same for a whole day's movement, which is a longer track than one session's
#: and is the reason these are separate numbers.
#:
#: The overview map used to ask `/metrics` for `limit=1000` against an endpoint that
#: sorts ascending and reports no truncation, so a day with more fixes than that
#: silently returned *the morning* — a track that stops at 11:00 and a point count
#: presented as the day's total. Nothing on the page distinguished it from a day
#: that ended at 11:00.
DEFAULT_DAY_TRACK_POINTS = 4000
MAX_DAY_TRACK_POINTS = 20000

#: Set rows one session may return. Twenty exercises of ten sets is two hundred.
MAX_SET_ROWS = 4000

#: Rows the summary scan may read. A session is a dozen figures; this is a ceiling
#: on a mis-tagged import writing one `session_id` across a whole day, which would
#: otherwise be the one query here with no bound and nothing saying it was cut.
MAX_SUMMARY_ROWS = 4000

#: Distinct series a detail response will draw. Beyond a handful the page is not
#: readable anyway, and each one costs a group in the same query.
MAX_STREAM_METRICS = 8

#: Readings a metric needs inside the window before it is drawn as a series.
#:
#: The registry's `CONTINUOUS` cadence says a metric *can* be sampled often; it says
#: nothing about whether it *was*, in this particular 45 minutes. Weather is
#: continuous and arrives hourly, so a workout window holds one reading of it — and
#: a one-point line is not a chart. Without this it was classified as a stream,
#: excluded from `surroundings` for being one, and then dropped by the client for
#: having too few points to draw: present in the payload, invisible on the page.
MIN_STREAM_POINTS = 3

#: Rows the list scan may read before it reports itself truncated.
MAX_LIST_ROWS = 20_000

#: Sessions one list page may return.
MAX_LIST_SESSIONS = 200

#: How far either side of the key's stated start a session may be looked for. The
#: key carries the start precisely so this bound exists: without it, resolving
#: `metadata->>'session_id'` has nothing to constrain the hypertable's time
#: dimension and the query walks a whole history to find a 45-minute run.
RESOLVE_MARGIN = timedelta(days=1)

#: The longest range the list will answer over, matching the gap scan.
MAX_LIST_DAYS = 366


class SessionNotFound(LookupError):
    """No session of that key in this workspace — including somebody else's."""


def _session_predicate(ref: SessionRef):
    """Rows belonging to one session, in whichever shape it was stored.

    A tagged session matches on its id alone. An untagged one has only the
    timestamp and title `core.daily_story` has always grouped on — plus
    `source_id`, which the day page's looser key omits. Two connectors stamping
    the same second with the same title may merge on a summary; on a detail page
    the reader would act on the merge.
    """
    if ref.kind == "session_id":
        return DataPoint.metadata_.op("->>")("session_id") == ref.session_id
    predicates = [
        DataPoint.timestamp == ref.start,
        # A legacy row has no session id by definition. Without this a tagged point
        # sharing the instant would be pulled into the legacy group as well, and one
        # row in two sessions is the double count the whole design rules out.
        DataPoint.metadata_.op("->>")("session_id").is_(None),
        # The title, expressed for the database exactly as `session_title` computes
        # it in Python. On the timestamp alone this matched every legacy row at that
        # instant from that connector: two workouts stamped the same second appeared
        # as two rows in the list, and opening either showed both of their measures.
        #
        # `nullif(x, '')` per field, because `session_title` skips an empty string
        # and falls through to the next field, where a bare `coalesce` would stop at
        # it.
        func.coalesce(
            *(
                func.nullif(DataPoint.metadata_.op("->>")(field), "")
                for field in TITLE_FIELDS
            ),
            "",
        )
        == (ref.title or ""),
    ]
    if ref.source_id:
        predicates.append(DataPoint.source_id == ref.source_id)
    return and_(*predicates)


def _sessionable_predicate():
    """Metrics that can describe a session, excluding the series inside one.

    `session_metric_predicate`, not the wider entry predicate the day's lanes
    exclude. While this was the wider one, `category="all"` — the list's default —
    grouped `nutrition_item_energy` and `calendar_meeting_duration` into sessions
    and returned them as workouts, titled from `food_name` and `summary` because
    `sessions.TITLE_FIELDS` reads those to name a card. A logged banana and a
    stand-up are not training, and a list of workouts that contains them cannot be
    used to answer anything about training.
    """
    return and_(session_metric_predicate(), ~_stream_metric_predicate())


def _stated_bound(key: str):
    """A numeric spread the point declared, or its own value.

    Guarded by `jsonb_typeof`, so a metadata key holding something other than a
    number degrades instead of failing the cast for every row in the window.
    """
    return func.coalesce(
        case(
            (
                func.jsonb_typeof(DataPoint.metadata_.op("->")(key)) == "number",
                cast(DataPoint.metadata_.op("->>")(key), Float),
            ),
            else_=None,
        ),
        DataPoint.value,
    )


def _clean(value: Any) -> Any:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


async def build_workout_list(
    session: AsyncSession,
    tenant_id: str,
    *,
    start_date: date,
    end_date: date,
    offset_minutes: int,
    category: str = "all",
    limit: int = 50,
) -> dict[str, Any]:
    """Every session in a range, newest first.

    The window uses the reader's own offset through the same `day_window` the daily
    story uses. A reader whose day starts at a different moment on two pages of one
    product is being told two different things about one dataset.
    """
    window_start = day_window(start_date, offset_minutes).start
    window_end = day_window(end_date, offset_minutes).end

    predicates = [
        DataPoint.tenant_id == tenant_id,
        DataPoint.timestamp >= window_start,
        DataPoint.timestamp < window_end,
        _sessionable_predicate(),
    ]
    if category == "workout":
        predicates.append(DataPoint.metric_type.startswith("workout_", autoescape=True))
    elif category == "strength":
        predicates.append(DataPoint.metric_type.startswith("strength_", autoescape=True))

    rows = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.timestamp,
                DataPoint.value,
                DataPoint.metadata_,
                DataPoint.source_id,
            )
            .where(*predicates)
            .order_by(DataPoint.timestamp.desc())
            # One over the budget, so a scan that hit its ceiling is distinguishable
            # from one that simply ran out of rows.
            .limit(MAX_LIST_ROWS + 1)
        )
    ).all()

    scan_limit_reached = len(rows) > MAX_LIST_ROWS
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows[:MAX_LIST_ROWS]:
        metadata = row.metadata_ or {}
        key = session_group_key(row.timestamp, metadata, _category_of(row.metric_type))
        entry = grouped.get(key)
        if entry is None:
            entry = grouped[key] = {
                "identity": key[0],
                "session_id": metadata.get("session_id"),
                "start": row.timestamp,
                "end": None,
                "title": session_title(metadata),
                "category": _category_of(row.metric_type),
                "source_id": str(row.source_id),
                "point_count": 0,
                "exercises": set(),
                "muscle_groups": set(),
                "_values": defaultdict(list),
            }
        entry["point_count"] += 1
        # A session's rows arrive newest-first, so the earliest one seen last is its
        # start. Sets are minutes apart, and the first set is when the workout began.
        entry["start"] = min(entry["start"], row.timestamp)
        if row.timestamp > (entry["end"] or row.timestamp - timedelta(seconds=1)):
            entry["end"] = row.timestamp
        if row.value is not None:
            entry["_values"][row.metric_type].append(float(row.value))
        if not entry["title"]:
            entry["title"] = session_title(metadata)
        for field in END_FIELDS:
            stated = metadata.get(field)
            if isinstance(stated, str) and stated:
                parsed = _parse_iso(stated)
                if parsed is not None and (entry["end"] is None or parsed > entry["end"]):
                    entry["end"] = parsed
                break
        if metadata.get("exercise_title"):
            entry["exercises"].add(str(metadata["exercise_title"]))
        if metadata.get("muscle_group"):
            entry["muscle_groups"].add(str(metadata["muscle_group"]))

    sessions = sorted(grouped.items(), key=lambda item: item[1]["start"], reverse=True)
    limited = sessions[:limit]

    payload = []
    for key, entry in limited:
        measures = {
            metric: _collapse(metric, values)
            for metric, values in entry["_values"].items()
        }
        ref = SessionRef(
            kind=entry["identity"],
            start=entry["start"],
            session_id=entry["session_id"],
            source_id=entry["source_id"],
            title=entry["title"],
            category=entry["category"],
        )
        payload.append(
            {
                "session_key": encode_session_key(ref),
                "session_id": entry["session_id"],
                # A stable identifier, not prose (rule 17). `timestamp_title` is the
                # interface's cue that this group may be two workouts merged or one
                # split, because the rows behind it carry no session of their own.
                "identity": entry["identity"],
                "start": entry["start"].isoformat(),
                "end": entry["end"].isoformat() if entry["end"] else None,
                "title": entry["title"],
                "category": entry["category"],
                "source_id": entry["source_id"],
                "measures": measures,
                "units": {metric: _unit_of(metric) for metric in measures},
                "point_count": entry["point_count"],
                "exercise_count": len(entry["exercises"]),
                "muscle_groups": sorted(entry["muscle_groups"]),
            }
        )

    return {
        "tenant_id": tenant_id,
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "offset_minutes": offset_minutes,
        "count": len(payload),
        "sessions": payload,
        "has_more": len(sessions) > len(limited),
        "scan_limit_reached": scan_limit_reached,
    }


def _parse_iso(raw: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _resolve_window(
    session: AsyncSession, tenant_id: str, ref: SessionRef
) -> tuple[datetime, datetime, bool]:
    """The span a session actually covers, bounded and clamped.

    Bounded by the key's own start ± a day before anything else, so resolving a
    session never costs a history scan. Clamped to `MAX_SESSION_HOURS`, and the
    clamp is reported rather than raised: a workout with a mis-stamped end is
    something the reader can see and act on, where a `400` would leave them
    nothing at all.
    """
    row = (
        await session.execute(
            select(
                func.min(DataPoint.timestamp),
                func.max(DataPoint.timestamp),
                func.max(DataPoint.metadata_.op("->>")("session_end")),
            ).where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= ref.start - RESOLVE_MARGIN,
                DataPoint.timestamp <= ref.start + RESOLVE_MARGIN,
                _session_predicate(ref),
            )
        )
    ).one()

    first, last, stated_end = row
    if first is None:
        raise SessionNotFound(ref.session_id or ref.title or "")

    start = first
    end = last
    if isinstance(stated_end, str):
        parsed = _parse_iso(stated_end)
        if parsed is not None and parsed > end:
            end = parsed

    clamped = False
    ceiling = start + timedelta(hours=MAX_SESSION_HOURS)
    if end > ceiling:
        end = ceiling
        clamped = True
    if end <= start:
        # A session whose points all share one instant is a moment, not a span.
        # A minute of window is what makes the streams and the route queries below
        # return the samples taken at that instant rather than an empty range.
        end = start + timedelta(minutes=1)
    return start, end, clamped


async def _summary_measures(
    session: AsyncSession, tenant_id: str, ref: SessionRef
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """This session's own figures, and the metadata that describes it."""
    rows = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.value,
                DataPoint.metadata_,
                DataPoint.source_id,
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= ref.start - RESOLVE_MARGIN,
                DataPoint.timestamp <= ref.start + RESOLVE_MARGIN,
                _session_predicate(ref),
                _sessionable_predicate(),
            )
            .order_by(DataPoint.timestamp)
            .limit(MAX_SUMMARY_ROWS + 1)
        )
    ).all()
    measures_truncated = len(rows) > MAX_SUMMARY_ROWS
    rows = rows[:MAX_SUMMARY_ROWS]

    collected: dict[str, dict[str, Any]] = {}
    context: dict[str, Any] = {}
    for row in rows:
        # The last third of a legacy group key. It cannot go in the SQL predicate —
        # a category is a property of the metric name in the registry, not of a
        # column — so it is applied here, where the mapping lives. Without it a
        # workout and a strength session sharing an instant and a name would be two
        # rows in the list and one merged page when opened.
        if (
            ref.kind == "timestamp_title"
            and ref.category
            and _category_of(row.metric_type) != ref.category
        ):
            continue
        metadata = row.metadata_ or {}
        context.setdefault("title", session_title(metadata))
        for field in ("workout_name", "activity_name", "workout_title", "session_origin",
                      "workout_category", "muscle_group", "is_indoor", "device_source",
                      "gps_enabled", "ambient_temperature", "ambient_humidity", "notes"):
            if field in metadata and field not in context and metadata[field] is not None:
                context[field] = metadata[field]
        if row.value is None:
            continue
        entry = collected.setdefault(
            row.metric_type,
            {
                "metric_type": row.metric_type,
                "unit": _unit_of(row.metric_type),
                "source_id": str(row.source_id),
                "provider_value": metadata.get("provider_value"),
                "units": metadata.get("units"),
                # Kept, so a number this platform worked out never passes for one
                # the provider stated (rule 19).
                "derived_by": metadata.get("derived_by"),
                "derived_from": metadata.get("derived_from"),
                "sample_count": 0,
                "_values": [],
            },
        )
        entry["_values"].append(float(row.value))
        entry["sample_count"] += 1

    measures = []
    for metric_type, entry in sorted(collected.items()):
        values = entry.pop("_values")
        entry["value"] = _collapse(metric_type, values)
        try:
            entry["aggregation"] = describe(metric_type).aggregation.value
            entry["category"] = describe(metric_type).category.value
        except ValueError:
            entry["aggregation"] = "average"
            entry["category"] = MetricCategory.CUSTOM.value
        measures.append(entry)
    context["_truncated"] = measures_truncated
    return measures, context


async def _strength_breakdown(
    session: AsyncSession, tenant_id: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """Sets grouped by muscle group and exercise, in the order they were done."""
    rows = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.timestamp,
                DataPoint.value,
                DataPoint.metadata_,
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
                DataPoint.metric_type.startswith("strength_set_", autoescape=True),
            )
            .order_by(DataPoint.timestamp)
            .limit(MAX_SET_ROWS + 1)
        )
    ).all()

    truncated = len(rows) > MAX_SET_ROWS
    sets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows[:MAX_SET_ROWS]:
        metadata = row.metadata_ or {}
        exercise = str(metadata.get("exercise_title") or "Exercise")
        # `set_id` where the provider states one, else the instant — which is what
        # separates one set from the next when it does not.
        identity = str(metadata.get("set_id") or row.timestamp.isoformat())
        entry = sets.setdefault(
            (exercise, identity),
            {
                "exercise_title": exercise,
                "muscle_group": metadata.get("muscle_group"),
                "exercise_category": metadata.get("exercise_category"),
                "set_number": metadata.get("set_number"),
                "at": row.timestamp.isoformat(),
                "notes": metadata.get("notes"),
            },
        )
        field = {
            "strength_set_weight": "weight",
            "strength_set_reps": "reps",
            "strength_set_volume": "volume",
            "strength_set_heart_rate_max": "heart_rate_max",
        }.get(row.metric_type)
        if field and row.value is not None:
            entry[field] = float(row.value)

    by_exercise: dict[str, dict[str, Any]] = {}
    for (exercise, _identity), entry in sets.items():
        group = by_exercise.setdefault(
            exercise,
            {
                "exercise_title": exercise,
                "muscle_group": entry.get("muscle_group"),
                "exercise_category": entry.get("exercise_category"),
                "sets": [],
                "total_volume": 0.0,
                "total_reps": 0.0,
                "top_set_weight": None,
            },
        )
        group["sets"].append(entry)
        group["total_volume"] += entry.get("volume") or 0.0
        group["total_reps"] += entry.get("reps") or 0.0
        weight = entry.get("weight")
        if weight is not None and (group["top_set_weight"] is None or weight > group["top_set_weight"]):
            group["top_set_weight"] = weight

    exercises = sorted(by_exercise.values(), key=lambda item: item["sets"][0]["at"])
    for group in exercises:
        group["sets"].sort(key=lambda item: (item["at"], item.get("set_number") or 0))

    return {
        "exercises": exercises,
        "total_volume": sum(group["total_volume"] for group in exercises),
        "total_sets": sum(len(group["sets"]) for group in exercises),
        "set_rows_truncated": truncated,
    }


def _not_another_sessions_stream(ref: SessionRef):
    """Keep this session's own series, and drop the ones that say they are not.

    The window is the join for everything on this page, and for ambient readings it
    has to be: weather and a second device's continuous metrics carry no session id
    and never will. But `workout_heart_rate` *does* carry one — every importer that
    emits a workout writes it — and the window alone attributed the pulse of an
    overlapping or back-to-back session to this one. Two sessions an hour apart with
    a 15-minute pad between them is enough, and the resulting chart is a real
    measurement of the wrong workout, which is the kind of wrong nothing on the page
    can betray.

    So only *stream* rows are narrowed, and only when they state an id that is not
    this session's. A stream row carrying no id keeps the window as its only
    evidence, which is all a pre-`session_id` row has ever had.
    """
    if ref.kind != "session_id" or not ref.session_id:
        return true()
    stated = DataPoint.metadata_.op("->>")("session_id")
    return or_(
        ~_stream_metric_predicate(),
        stated.is_(None),
        stated == ref.session_id,
    )


async def _streams(
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    *,
    stream_points: int,
    ref: SessionRef,
) -> list[dict[str, Any]]:
    """The continuous series inside the window, decimated in SQL.

    Bucketed mean **plus a min/max envelope**, not a sampled subset: a decimated
    point that hides its extremes is a number that looks measured. A sprint that
    peaked at 186 inside a bucket averaging 162 has to still show 186, or the chart
    is a different workout from the one that happened.

    Not largest-triangle-three-buckets, which draws a prettier line and needs every
    row transferred into Python first — the cost this whole function avoids.
    Epoch-floor arithmetic rather than `time_bucket()`, so nothing here depends on
    TimescaleDB: Core uses `date_trunc` everywhere else for the same reason.
    """
    candidates = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.source_id,
                func.count(DataPoint.value).label("samples"),
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
                DataPoint.value.is_not(None),
                or_(
                    _stream_metric_predicate(),
                    DataPoint.metric_type.in_(_continuous_metrics()),
                ),
                # Applied to the density test as well as to the read below. A series
                # belonging to a neighbouring session must not pass the floor here and
                # then contribute nothing, which would exclude the metric from
                # `surroundings` for being a drawn stream while drawing nothing.
                _not_another_sessions_stream(ref),
            )
            # Grouped the way the streams themselves are. Counting per metric
            # while emitting per (metric, connector) meant three readings split
            # two-and-one across two connectors passed the density test, were
            # excluded from `surroundings` for being a stream, and were then dropped
            # by the client for having too few points to draw — invisible on both.
            .group_by(DataPoint.metric_type, DataPoint.source_id)
            .having(func.count(DataPoint.value) >= MIN_STREAM_POINTS)
            # Densest first, so the cap keeps the series worth drawing rather than
            # whichever names sort earliest.
            .order_by(func.count(DataPoint.value).desc())
            .limit(MAX_STREAM_METRICS)
        )
    ).all()
    if not candidates:
        return []

    drawn = {(row.metric_type, str(row.source_id)) for row in candidates}
    metrics = sorted({metric for metric, _ in drawn})
    span = max((end - start).total_seconds(), 1.0)
    width = max(1, int(span // max(stream_points, 1)) + (1 if span % max(stream_points, 1) else 0))

    bucket = func.to_timestamp(
        func.floor(func.extract("epoch", DataPoint.timestamp) / width) * width
    )
    rows = (
        await session.execute(
            select(
                DataPoint.metric_type,
                DataPoint.source_id,
                bucket.label("bucket"),
                # Weighted by what each stored point stands on. These are already
                # bucket means — a second of `workout_heart_rate` can average sixty
                # readings or one — so a bare `avg()` let a sparse bucket pull the
                # line as hard as a dense one, and the drawn average disagreed with
                # both `metric_rollups` and the min/max band beneath it.
                weighted_average().label("avg_value"),
                # `jsonb_typeof` before the cast. Only the bucket aggregator writes
                # these keys and it always writes numbers, so this is unreachable
                # today — but an unguarded cast turns one odd value anywhere in the
                # window into a 500 for the whole page, where the guard degrades to
                # the point's own value.
                func.min(func.least(DataPoint.value, _stated_bound("bucket_min"))).label(
                    "min_value"
                ),
                func.max(func.greatest(DataPoint.value, _stated_bound("bucket_max"))).label(
                    "max_value"
                ),
                func.count(DataPoint.value).label("samples"),
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
                DataPoint.value.is_not(None),
                DataPoint.metric_type.in_(metrics),
                _not_another_sessions_stream(ref),
            )
            .group_by(DataPoint.metric_type, DataPoint.source_id, text("bucket"))
            .order_by(text("bucket"))
        )
    ).all()

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row.metric_type, str(row.source_id))
        # A connector below the density floor is not a series, even where another
        # connector's readings of the same metric are.
        if key not in drawn:
            continue
        stream = grouped.setdefault(
            key,
            {
                "metric_type": row.metric_type,
                "source_id": str(row.source_id),
                "unit": _unit_of(row.metric_type),
                "bucket_seconds": width,
                "points": [],
            },
        )
        stream["points"].append(
            {
                "t": row.bucket.isoformat(),
                "avg": _clean(row.avg_value),
                "min": _clean(row.min_value),
                "max": _clean(row.max_value),
                "n": int(row.samples or 0),
            }
        )

    streams = []
    for stream in grouped.values():
        stream["point_count"] = len(stream["points"])
        stream["truncated"] = len(stream["points"]) > stream_points
        stream["points"] = stream["points"][:stream_points]
        streams.append(stream)
    return sorted(streams, key=lambda item: item["metric_type"])


def _continuous_metrics() -> list[str]:
    """Registry metrics sampled often enough to be worth drawing as a line."""
    from shared_schemas.metrics import METRIC_CATALOG

    return sorted(
        key
        for key, definition in METRIC_CATALOG.items()
        if definition.cadence is Cadence.CONTINUOUS or key in STREAM_METRICS
    )


async def track_for_window(
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    *,
    route_points: int,
) -> dict[str, Any] | None:
    """The GPS track, simplified in the database.

    This is the one read in the platform that uses `location_geom`. The PostGIS
    column, its GiST index and the trigger that fills it have existed since
    migration 005 and nothing has ever queried them.

    `ST_Length(::geography)` gives a **measured** track length to sit beside the
    distance the provider stated — a genuinely different number, and exactly the
    kind of cross-check a detail page is for. It is one aggregation over the
    geometry column, in a CTE, rather than the two the first version ran: the second
    built a simplified `GeoJSON` linestring that nothing rendered, because the map
    draws from `samples` and the decimation that matters happens in the query below.

    Metadata coordinates remain the fallback, for rows written before migration 005
    or through a path where the trigger's cast failed. The response says which was
    used through a stable code, never prose (rule 17).
    """
    total = (
        await session.execute(
            select(func.count(DataPoint.id)).where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
                DataPoint.metric_type == "location_point",
            )
        )
    ).scalar_one()
    if not total:
        return None

    stride = max(1, (int(total) + route_points - 1) // route_points)
    geometry = (
        await session.execute(
            text(
                """
                WITH track AS (
                    SELECT
                        ST_MakeLine(location_geom ORDER BY timestamp) AS line,
                        count(*) AS geom_count
                    FROM data_points
                    WHERE tenant_id = :tenant_id
                      AND metric_type = 'location_point'
                      AND timestamp >= :start AND timestamp < :end
                      AND location_geom IS NOT NULL
                )
                SELECT ST_Length(line::geography) AS length_m, geom_count
                FROM track
                """
            ),
            {
                "tenant_id": tenant_id,
                "start": start,
                "end": end,
            },
        )
    ).one()

    # Decimated in SQL, not after loading. Reading every fix and then keeping one in
    # `stride` transfers the whole track to discard most of it: twelve hours at one
    # fix a second is 43,200 rows of JSONB to produce a thousand. `row_number()` puts
    # the stride in the database, so what crosses the wire is what is returned.
    numbered = (
        select(
            DataPoint.timestamp.label("at"),
            DataPoint.metadata_.label("meta"),
            func.row_number().over(order_by=DataPoint.timestamp).label("rn"),
        )
        .where(
            DataPoint.tenant_id == tenant_id,
            DataPoint.timestamp >= start,
            DataPoint.timestamp < end,
            DataPoint.metric_type == "location_point",
        )
        .subquery()
    )
    fixes = (
        await session.execute(
            select(numbered.c.at, numbered.c.meta)
            .where((numbered.c.rn - 1) % stride == 0)
            .order_by(numbered.c.at)
            .limit(route_points)
        )
    ).all()

    samples = []
    for row in fixes:
        metadata = row.meta or {}
        latitude = _clean(metadata.get("latitude"))
        longitude = _clean(metadata.get("longitude"))
        if latitude is None or longitude is None:
            continue
        samples.append(
            {
                "t": row.at.isoformat(),
                "lat": latitude,
                "lon": longitude,
                "altitude": _clean(metadata.get("altitude")),
                "speed": _clean(metadata.get("speed")),
            }
        )

    has_geometry = bool(geometry.geom_count)
    return {
        "source": "geometry" if has_geometry else "metadata",
        "measured_distance_m": _clean(geometry.length_m) if has_geometry else None,
        "fix_count": int(total),
        "samples": samples,
        "sample_count": len(samples),
        "truncated": stride > 1,
    }


async def _context(
    session: AsyncSession,
    tenant_id: str,
    start: datetime,
    end: datetime,
    *,
    drawn_as_streams: set[str],
) -> list[dict[str, Any]]:
    """Everything every other connector recorded during the session.

    One aggregate row per (metric, connector) — not the rows themselves, which is
    what keeps "every point from every connector" from meaning "every point on the
    wire". Reuses `daily_story.metric_totals` and `resolve_primary_source`, so this
    page and the day page cannot name different connectors for one number.
    """
    totals = await metric_totals(
        session,
        tenant_id,
        start,
        end,
        exclude=(
            # Every entry metric, not only the session's own. Narrowing
            # `_sessionable_predicate` to what a session actually is would otherwise
            # let the other entry metrics in here instead, and `nutrition_item_energy`
            # is a `SUM`: a workout window that happens to straddle lunch would report
            # the meal's calories as a figure measured "during" the session.
            ~entry_metric_predicate(),
            # Exactly the metrics that *were* drawn — not everything that could
            # have been. A series shown as a chart must not also appear as a single
            # figure, and a metric with one reading in this window is not a series,
            # so it belongs here rather than nowhere.
            ~DataPoint.metric_type.in_(sorted(drawn_as_streams) or [""]),
            # The route is the route. `location_point` is a marker whose value is
            # always 1, so summing it reports "270" as though 270 were a reading of
            # something.
            DataPoint.metric_type != "location_point",
        ),
    )
    if not totals:
        return []

    ambiguous = {metric for metric, sources in totals.items() if len(sources) > 1}
    preferences = await primary_source_preferences(session, tenant_id) if ambiguous else {}
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

    entries = []
    for metric_type, by_source in sorted(totals.items()):
        try:
            definition = describe(metric_type)
        except ValueError:
            continue
        source_ids = sorted(by_source)
        if len(source_ids) > 1:
            chosen, reason = resolve_primary_source_for(
                metric_type, source_ids, preferences, coverage
            )
        else:
            chosen, reason = source_ids[0], REASON_ONLY_SOURCE
        stats = by_source[chosen]
        value = {
            "sum": stats["sum"],
            "max": stats["max"],
            "last": stats["last"],
        }.get(definition.aggregation.value, stats["avg"])
        entries.append(
            {
                "metric_type": metric_type,
                "value": value,
                "unit": definition.unit.value,
                "aggregation": definition.aggregation.value,
                "category": definition.category.value,
                "source_id": chosen,
                "source_type": source_types.get(chosen),
                "source_reason": reason,
                "other_sources": [s for s in source_ids if s != chosen],
                "sample_count": stats["samples"],
            }
        )
    return entries


async def build_workout_detail(
    session: AsyncSession,
    tenant_id: str,
    ref: SessionRef,
    *,
    pad_seconds: int = DEFAULT_PAD_SECONDS,
    stream_points: int = DEFAULT_STREAM_POINTS,
    route_points: int = DEFAULT_ROUTE_POINTS,
) -> dict[str, Any]:
    """One session in full. Raises `SessionNotFound` for a key this tenant has none of."""
    start, end, clamped = await _resolve_window(session, tenant_id, ref)
    pad = timedelta(seconds=max(0, min(pad_seconds, MAX_PAD_SECONDS)))
    window_start, window_end = start - pad, end + pad

    measures, context = await _summary_measures(session, tenant_id, ref)
    strength = await _strength_breakdown(session, tenant_id, window_start, window_end)
    streams = await _streams(
        session, tenant_id, window_start, window_end, stream_points=stream_points, ref=ref
    )
    route = await track_for_window(
        session, tenant_id, window_start, window_end, route_points=route_points
    )
    surroundings = await _context(
        session,
        tenant_id,
        window_start,
        window_end,
        drawn_as_streams={stream["metric_type"] for stream in streams},
    )

    return {
        "tenant_id": tenant_id,
        "session_key": encode_session_key(ref),
        "session_id": ref.session_id,
        "identity": ref.kind,
        "title": context.get("title") or ref.title or "",
        "category": (measures[0]["category"] if measures else MetricCategory.WORKOUT.value),
        "context": {k: v for k, v in context.items() if k not in ("title", "_truncated")},
        "measures_truncated": bool(context.get("_truncated")),
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "queried_from": window_start.isoformat(),
            "queried_to": window_end.isoformat(),
            "pad_seconds": int(pad.total_seconds()),
            "clamped": clamped,
        },
        "measures": measures,
        "strength": strength,
        "streams": streams,
        "route": route,
        "surroundings": surroundings,
        "limits": {
            "stream_points": stream_points,
            "route_points": route_points,
            "max_session_hours": MAX_SESSION_HOURS,
            "max_set_rows": MAX_SET_ROWS,
        },
    }
