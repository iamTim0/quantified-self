"""Derived reports, computed when the data changes rather than when a page opens.

Three things the dashboard shows are derivations over a tenant's whole history:
the daily gap scan, the cross-source conflict scan, and the analysis insights
bundle. All three were recomputed on every request, and the quality page
additionally re-ran the first two every fifteen seconds — a full-history scan of
`data_points` to redraw content that was identical each time.

None of them can answer differently until an import has changed the data
underneath. So they are computed once per change and read from `report_runs`,
which makes a page load one indexed row and no scan.

**What is and is not a report.** Only the expensive derivations live here. The
quarantine list, the mapping rules and the unsupported-field report are *state*,
not derivation: they are small indexed selects, and they have to be correct the
instant a user saves a rule rather than at the next run. Putting them behind a
job would make the page wrong for hours to save nothing.

**Staleness is a comparison, not a computation.** A run records
`covers_data_through` — the newest finished import it could see. A tenant whose
newest finished import is later than that has a stale report, and finding that
out costs two timestamps. Nothing re-scans to discover whether it should re-scan.

**Who computes what.** `gaps` and `conflicts` are computed here, because Core
owns the database (rule 1) and both are pure SQL plus a pass in Python.
`insights` is computed by the Analysis Service, which reads through gRPC and
writes its result back through `PutAnalysisReport` — Core stores it, Analysis
derives it, and neither reaches into the other's territory (rules 1 and 3).

Maps to Fizzbee Invariants:
- ReportSingleFlight
- ReportNeverServesFutureData
- TenantIsolation
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from shared_schemas.metrics import METRIC_CATALOG, Cadence
from sqlalchemy import Integer, case, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.analytics import (
    TimeRange,
    detect_cadence_gaps,
    detect_daily_gaps,
    find_cross_source_conflicts,
)
from core.db.models import (
    DataPoint,
    MetricMappingRule,
    MetricRollup,
    MetricSourcePreference,
    ReportRun,
    SyncRun,
    Tenant,
)
from core.db.session import async_session_maker
from core.metric_mapping import custom_definitions_from_rules

logger = logging.getLogger(__name__)

#: The kinds a tenant can hold. `insights` is written by the Analysis Service;
#: the other two are computed in this module.
REPORT_KINDS: tuple[str, ...] = ("gaps", "conflicts", "insights", "day")

#: Kinds Core computes itself. `insights` is deliberately absent — Core does not
#: do data science, and the one time this endpoint did, it queried SQL straight
#: from a request handler and had to be moved out again.
CORE_COMPUTED_KINDS: tuple[str, ...] = ("gaps", "conflicts", "day")

#: Statuses that mean a run for this kind is already under way.
IN_FLIGHT_STATUSES = ("queued", "running")

#: Why one connector answers for a metric — the whole vocabulary, in one place.
#:
#: Named constants rather than literals because that is what went wrong: the
#: three strings were written out at five call sites across three modules, and
#: nothing tied them together, so `daily_story` could have invented a fourth and
#: no test would have said anything. A client compares against these (rule 17),
#: which makes them interface, and interface belongs somewhere a reader can find.
REASON_ONLY_SOURCE = "only_source"
REASON_PREFERENCE = "preference"
REASON_COVERAGE = "coverage"

#: Every value `source_reason` and `primary_reason` may take.
SOURCE_REASONS: frozenset[str] = frozenset(
    {REASON_ONLY_SOURCE, REASON_PREFERENCE, REASON_COVERAGE}
)

#: A run still "running" after this long is assumed dead — the replica computing
#: it crashed, or the Analysis Service never answered. Without this one lost run
#: would block a kind forever, which is the failure the sync scheduler already
#: learned (`core.scheduler.STALE_RUN_AFTER`).
#:
#: This is the allowance for a run over :data:`REFERENCE_WINDOW_DAYS`. A larger
#: window gets proportionally longer — see :func:`stale_after_interval`.
STALE_RUN_AFTER = timedelta(minutes=30)

#: The window `STALE_RUN_AFTER` is the allowance for. The dashboard's default, so
#: today's behaviour is unchanged for the window most runs actually use.
REFERENCE_WINDOW_DAYS = 90

#: The ceiling however large a window is asked for. A run that has been going for
#: two hours is not slow, it is gone, and the point of failing it is to stop one
#: lost run blocking its kind forever.
MAX_STALE_RUN_AFTER = timedelta(hours=2)

#: How stale a report may get with no new data at all. New data is the normal
#: trigger; this is the backstop that catches a report whose *inputs* changed
#: without an import — a mapping rule adopted, a connector deleted.
MAX_REPORT_AGE = timedelta(hours=12)

#: Default window for the gap scan, in days. The reader can ask for another, but
#: a scheduled run has to pick one, and this is what the dashboard opens with.
DEFAULT_GAP_WINDOW_DAYS = 30

#: Arbitrary but fixed, like `core.scheduler.SCHEDULER_LOCK_KEY`: every replica
#: has to pick the same 64-bit integer for the lock to mean anything.
REPORT_TICK_LOCK_KEY = 0x5153_5250_5254_0000  # "QSRPRT\0\0"

#: How often to look for stale reports. Not how often a report is recomputed —
#: that follows the data. This only bounds how late a recomputation can be.
REPORT_TICK_SECONDS = 300

#: Cross-source conflicts are looked for in the most recent points only. The
#: whole history would be a different, much more expensive question, and a
#: disagreement between two connectors is worth knowing about while it is still
#: happening.
CONFLICT_SCAN_POINTS = 5000
DEFAULT_CONFLICT_TOLERANCE = 0.05


@dataclass(frozen=True)
class DueReport:
    """A tenant/kind pair whose report needs recomputing."""

    tenant_id: str
    kind: str
    reason: str
    #: The parameters the last successful run used, so a scheduled re-run
    #: answers the same question the reader last asked.
    params: dict[str, Any] = field(default_factory=dict)


async def primary_source_preferences(
    session: AsyncSession, tenant_id: str
) -> dict[str, str]:
    """The tenant's stated primary connector per metric, where one was stated."""
    rows = await session.execute(
        select(
            MetricSourcePreference.metric_type,
            MetricSourcePreference.primary_source_id,
        ).where(MetricSourcePreference.tenant_id == tenant_id)
    )
    return {metric_type: str(source_id) for metric_type, source_id in rows}


async def metric_source_coverage(
    session: AsyncSession, tenant_id: str
) -> dict[tuple[str, str], int]:
    """How many day buckets each connector contributed, per metric.

    Read over the workspace's whole history rather than the window a caller
    happens to be looking at, and that is deliberate: a primary source is a
    property of the workspace, not of the current chart. Resolving it per window
    made the analysed series change identity between two views of the same data,
    and made the picker card name a connector the bundle had not used — the card
    counted everything, the bundle counted the last ninety days.

    Day rollups rather than raw points: same grouping, one indexed aggregate, and
    every stored point has a day bucket (`core.rollups`).
    """
    rows = (
        await session.execute(
            select(
                MetricRollup.metric_type,
                MetricRollup.source_id,
                func.sum(MetricRollup.sample_count),
            )
            .where(
                MetricRollup.tenant_id == tenant_id,
                MetricRollup.resolution == "day",
            )
            .group_by(MetricRollup.metric_type, MetricRollup.source_id)
        )
    ).all()
    return {
        (metric_type, str(source_id)): int(samples or 0)
        for metric_type, source_id, samples in rows
    }


def resolve_primary_source(
    source_ids: Sequence[str],
    *,
    preference: str | None,
    coverage: Mapping[str, int],
) -> tuple[str, str]:
    """Which connector answers for a metric several of them report, and why.

    The reader used to be told nothing and shown nothing: a metric reported by two
    connectors was dropped from every analysis, because merging is genuinely
    unsafe — adding two step counters double counts (rule 19) and averaging two
    overlapping sensors reweights the samples invisibly. But not merging does not
    have to mean not answering. One source answers, and the caller is told which.

    A stated preference wins, and wins even when that connector covered less of
    the window: it is a statement about which device the reader trusts, not a
    guess, and quietly overruling it on volume would make the setting a placebo.
    Otherwise the source with the most samples wins, with the identifier breaking
    a tie so the choice is stable between calls rather than flickering with row
    order.

    The reason is `preference` or `coverage` — lowercase, English, stable, the
    shape rule 17 fixes for every field a client compares against. It was
    `PREFERENCE` / `COVERAGE` until now, which was the same idea in a second
    spelling: `direction` next to it is lowercase, `severity` is lowercase, and a
    reader working out which convention to follow had to guess. There is one now.
    """
    if preference and preference in source_ids:
        return preference, REASON_PREFERENCE
    best = max(sorted(source_ids), key=lambda source_id: coverage.get(source_id, 0))
    return best, REASON_COVERAGE


def report_lock_key(tenant_id: str, kind: str) -> int:
    """A stable advisory-lock key for one tenant's report of one kind.

    Keyed on both, so a tenant's gap scan and conflict scan can run at the same
    time and two replicas cannot both start the same one. A digest rather than
    `hash()`, which is process-randomised.
    """
    digest = hashlib.blake2b(f"report:{tenant_id}:{kind}".encode(), digest_size=8).digest()
    key = int.from_bytes(digest, byteorder="big", signed=True)
    return key or 1


async def acquire_report_lock(session: AsyncSession, tenant_id: str, kind: str) -> None:
    """Serialize run creation for one tenant-scoped report kind.

    Transaction-scoped and *waiting* rather than try-and-skip, for the same reason
    `acquire_connector_lock` waits: the second caller must re-check the in-flight
    guard after the first has committed, or two simultaneous refresh clicks both
    pass it.
    """
    await session.execute(select(func.pg_advisory_xact_lock(report_lock_key(tenant_id, kind))))


async def tenant_data_high_water(session: AsyncSession, tenant_id: str) -> datetime | None:
    """When this tenant's data last finished changing.

    Read from `sync_runs`, not from `data_points`: it is a small indexed table and
    an import is the only thing that adds points. Asking the large table for
    `max(created_at)` would reintroduce the whole-history scan this module exists
    to remove.
    """
    return await session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.tenant_id == tenant_id,
            SyncRun.status == "success",
        )
    )


async def latest_successful_report(
    session: AsyncSession, tenant_id: str, kind: str
) -> ReportRun | None:
    """The newest finished run of this kind, which is the only one ever shown."""
    return (
        await session.execute(
            select(ReportRun)
            .where(
                ReportRun.tenant_id == tenant_id,
                ReportRun.kind == kind,
                ReportRun.status == "success",
            )
            .order_by(ReportRun.finished_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def latest_failed_report(
    session: AsyncSession, tenant_id: str, kind: str
) -> ReportRun | None:
    """The newest failed attempt, kept separate from the last good answer."""
    return (
        await session.execute(
            select(ReportRun)
            .where(
                ReportRun.tenant_id == tenant_id,
                ReportRun.kind == kind,
                ReportRun.status == "error",
            )
            .order_by(ReportRun.finished_at.desc())
            .limit(1)
        )
    ).scalars().first()


def stale_after_interval():
    """How long a run may take, from what it was asked to compute.

    A flat thirty minutes gave a 365-day insights bundle the same allowance as a
    90-day one, though it reads four times the history. Whatever the right absolute
    number turns out to be, a *constant* is the wrong shape: the only run the flat
    value was ever calibrated against is the default window.

    So the allowance scales with `params.days` and is clamped at both ends. A
    90-day run keeps exactly the allowance it has today — this cannot shorten
    anything — and a kind that states no window (the gap, conflict and day reports,
    all computed inside Core in seconds) falls back to the reference and is
    unaffected.

    Expressed in SQL because the caller is one bulk `UPDATE` across every tenant,
    and pulling the runs into Python to divide a number would turn a single
    statement into a scan.
    """
    stated = case(
        (
            func.jsonb_typeof(ReportRun.params.op("->")("days")) == "number",
            cast(ReportRun.params.op("->>")("days"), Integer),
        ),
        else_=None,
    )
    window = func.greatest(func.coalesce(stated, REFERENCE_WINDOW_DAYS), 1)
    seconds = STALE_RUN_AFTER.total_seconds() * window / REFERENCE_WINDOW_DAYS
    bounded = func.least(
        func.greatest(seconds, STALE_RUN_AFTER.total_seconds()),
        MAX_STALE_RUN_AFTER.total_seconds(),
    )
    return func.make_interval(0, 0, 0, 0, 0, 0, bounded)

async def has_in_flight_report(
    session: AsyncSession, tenant_id: str, kind: str, *, now: datetime
) -> bool:
    """Is a run for this tenant and kind already queued or running (and not stale)?

    The same allowance `expire_stale_report_runs` uses, and it has to be: if this
    called a run stale at thirty minutes while the sweep still allowed it two hours,
    a click in minute thirty-one would queue a second run alongside the first — the
    "row of impatient clicks becomes a row of identical scans" that this guard exists
    to prevent, reappearing precisely for the long windows that take longest.
    """
    found = await session.scalar(
        select(ReportRun.id)
        .where(
            ReportRun.tenant_id == tenant_id,
            ReportRun.kind == kind,
            ReportRun.status.in_(IN_FLIGHT_STATUSES),
            ReportRun.started_at >= now - stale_after_interval(),
        )
        .limit(1)
    )
    return found is not None



async def expire_stale_report_runs(
    session: AsyncSession, *, now: datetime, tenant_ids: Sequence[str]
) -> int:
    """Fail runs that stopped reporting, so their kind is not blocked forever.

    Tenant-scoped, like `core.scheduler.expire_stale_runs` which this mirrors.
    The caller is a cross-tenant worker and already holds the tenant list, so
    there is nothing to gain from an unqualified UPDATE and rule 2 admits no
    exceptions — a write that names no tenant is one nobody can reason about.

    **Two different failures, two different codes.** Both used to be
    `report_timeout`, and they are not the same event:

    - A run still `queued` was never claimed. Nothing computed it, because the
      Analysis Service is down, is not reachable over gRPC, or has
      `REPORT_WORKER_ENABLED` off. Waiting longer would not have helped, and the
      operator has to restart something.
    - A run that reached `running` *was* claimed and did not finish in time. That
      one is about the work: either the window is genuinely too large or the worker
      died mid-computation.

    Telling a reader "the report did not complete before the run timeout" when in
    fact no worker ever existed sends them looking for a slow query that is not
    there. `insights` is the only kind Core does not compute itself, so it is the
    only kind that can be queued and abandoned — which is exactly why this was the
    one message anybody ever saw.
    """
    if not tenant_ids:
        return 0
    never_claimed = ReportRun.status == "queued"
    result = await session.execute(
        update(ReportRun)
        .where(
            ReportRun.tenant_id.in_(tenant_ids),
            ReportRun.status.in_(IN_FLIGHT_STATUSES),
            ReportRun.started_at < now - stale_after_interval(),
        )
        .values(
            status="error",
            message=case(
                (
                    never_claimed,
                    (
                        "No analysis worker claimed this report. The Analysis "
                        "Service may be stopped or unreachable."
                    ),
                ),
                else_="The report did not complete before the run timeout.",
            ),
            message_code=case(
                (never_claimed, "report_never_claimed"),
                else_="report_timeout",
            ),
            message_params={},
            finished_at=now,
        )
    )
    return result.rowcount or 0


def day_report_has_rolled_over(run: ReportRun) -> bool:
    """Whether a stored day report is describing the wrong two days.

    The daily story is the only kind whose answer expires on a clock rather than
    on an import: at one minute past midnight a report computed yesterday still
    holds the 14th and the 15th and calls the 15th "today". No data changed, so
    nothing else here would notice, and the twelve-hour age backstop would leave
    the landing page naming the wrong days for most of a morning.

    The reader's own midnight, not UTC's — the offset the run was computed for is
    stored with it, which is exactly what that offset is for.
    """
    params = run.params or {}
    stored_day = params.get("day")
    if not isinstance(stored_day, str):
        # A run from before the day was recorded. Treat as rolled over rather
        # than assume: recomputing once is cheap, showing the wrong day is not.
        return True
    offset = int(params.get("offset_minutes") or 0)
    reader_today = (
        datetime.now(timezone.utc) + timedelta(minutes=offset)
    ).date().isoformat()
    return stored_day != reader_today


def report_is_stale(run: ReportRun | None, high_water: datetime | None) -> bool:
    """Whether a stored report no longer describes the data that exists.

    Four ways to be stale, and only the first two are about data: no report at
    all; data finished arriving after the report saw it; the report is simply
    old, which catches an input that changed without an import (an adopted
    mapping rule, a deleted connector); or — for the daily story alone — the
    calendar day it was computed for has ended.
    """
    if run is None or run.finished_at is None:
        return True
    if run.kind == "day" and day_report_has_rolled_over(run):
        return True
    if high_water is not None and (
        run.covers_data_through is None or run.covers_data_through < high_water
    ):
        return True
    return datetime.now(timezone.utc) - run.finished_at >= MAX_REPORT_AGE


async def find_due_reports(session: AsyncSession, *, now: datetime) -> list[DueReport]:
    """Every tenant/kind pair whose report needs recomputing.

    Cross-tenant on purpose — this is the one path that acts for all of them, in
    the same way `find_due_connectors` does. Every computation that follows is
    still scoped to a single tenant (rule 2).

    Three grouped queries rather than two per tenant per kind. A tick that mostly
    finds nothing due should not cost more as workspaces are added.
    """
    tenant_ids = list((await session.execute(select(Tenant.id))).scalars())
    if not tenant_ids:
        return []
    await expire_stale_report_runs(session, now=now, tenant_ids=tenant_ids)

    high_water_by_tenant = {
        str(tenant_id): finished
        for tenant_id, finished in (
            await session.execute(
                select(SyncRun.tenant_id, func.max(SyncRun.finished_at))
                .where(
                    SyncRun.tenant_id.in_(tenant_ids),
                    SyncRun.status == "success",
                )
                .group_by(SyncRun.tenant_id)
            )
        ).all()
    }

    in_flight = {
        (str(tenant_id), kind)
        for tenant_id, kind in (
            await session.execute(
                select(ReportRun.tenant_id, ReportRun.kind).where(
                    ReportRun.tenant_id.in_(tenant_ids),
                    ReportRun.status.in_(IN_FLIGHT_STATUSES),
                    # Same allowance as the sweep above, for the same reason.
                    ReportRun.started_at >= now - stale_after_interval(),
                )
            )
        ).all()
    }

    # The newest successful run per (tenant, kind), in one pass. `DISTINCT ON`
    # needs the ordering to lead with the distinct columns.
    latest_rows = (
        await session.execute(
            select(ReportRun)
            .where(
                ReportRun.tenant_id.in_(tenant_ids),
                ReportRun.status == "success",
            )
            .distinct(ReportRun.tenant_id, ReportRun.kind)
            .order_by(
                ReportRun.tenant_id,
                ReportRun.kind,
                ReportRun.finished_at.desc(),
            )
        )
    ).scalars().all()
    latest_by_key = {(str(run.tenant_id), run.kind): run for run in latest_rows}

    due: list[DueReport] = []
    for tenant_id in (str(t) for t in tenant_ids):
        high_water = high_water_by_tenant.get(tenant_id)
        if high_water is None:
            # A workspace that has never completed an import has nothing to
            # report on. Computing an empty gap scan for it every twelve hours
            # would be work that can only ever produce the same nothing.
            continue
        for kind in REPORT_KINDS:
            if (tenant_id, kind) in in_flight:
                continue
            latest = latest_by_key.get((tenant_id, kind))
            if not report_is_stale(latest, high_water):
                continue
            reason = "no_report" if latest is None else (
                "new_data"
                if latest.covers_data_through is None
                or latest.covers_data_through < high_water
                else "max_age"
            )
            due.append(
                DueReport(
                    tenant_id=tenant_id,
                    kind=kind,
                    reason=reason,
                    # What the reader last asked for, carried into the scheduled
                    # re-run. Without this a tick replaced a 365-day gap report
                    # with a 30-day one and the selector snapped back under the
                    # reader — and, worse, dropped the `offset_minutes` that
                    # decides which calendar day a point belongs to, so a
                    # scheduled run silently reverted to UTC day boundaries.
                    params=dict(latest.params or {}) if latest else {},
                )
            )
    return due


def resolved_report_params(
    kind: str, params: dict[str, Any] | None
) -> dict[str, Any]:
    """The parameters a run is opened with, completed for the kinds that need it.

    A day report records the day it answers for, stamped when the run opens so
    the stored value is right even if the computation straddles midnight. It is
    what `day_report_has_rolled_over` reads; without it every day report looks
    permanently stale.

    Shared, because there are two entry points — the scheduler and a manual
    refresh — and stamping in only one of them is how the manual path ended up
    storing a run with no day at all.
    """
    resolved = dict(params or {})
    if kind == "day":
        offset = int(resolved.get("offset_minutes") or 0)
        resolved["day"] = (
            (datetime.now(timezone.utc) + timedelta(minutes=offset)).date().isoformat()
        )
    return resolved


async def open_report_run(
    session: AsyncSession,
    *,
    tenant_id: str,
    kind: str,
    trigger: str,
    request_id: str,
    params: dict[str, Any] | None = None,
) -> ReportRun:
    """Record that a computation has begun, and what it was asked for."""
    run = ReportRun(
        tenant_id=tenant_id,
        kind=kind,
        status="running",
        trigger=trigger,
        request_id=request_id[:128],
        params=params or {},
        covers_data_through=await tenant_data_high_water(session, tenant_id),
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()
    return run


def finish_report_run(run: ReportRun, payload: dict[str, Any]) -> None:
    """Store a finished result. The run is what a reader is served from now on."""
    run.payload = payload
    run.status = "success"
    run.message_code = "report_computed"
    run.message_params = {}
    run.message = "Report computed."
    run.finished_at = datetime.now(timezone.utc)


def fail_report_run(run: ReportRun, code: str, detail: str) -> None:
    """Record a failure without destroying the previous successful run.

    A failed run is never served — `latest_successful_report` filters on success —
    so the reader keeps seeing the last good answer, correctly labelled with the
    time it was computed, rather than an empty page.
    """
    run.status = "error"
    run.message_code = code
    run.message_params = {}
    run.message = detail[:512]
    run.finished_at = datetime.now(timezone.utc)


# ─── The computations themselves ────────────────────────────────


async def _cadence_overrides(session: AsyncSession, tenant_id: str) -> dict[str, Cadence]:
    """Cadences declared by a tenant's own adopted mapping rules."""
    rules = list(
        (
            await session.execute(
                select(MetricMappingRule).where(
                    MetricMappingRule.tenant_id == tenant_id,
                    MetricMappingRule.action == "adopt",
                )
            )
        ).scalars()
    )
    return {
        key: definition.cadence
        for key, definition in custom_definitions_from_rules(rules).items()
    }


async def compute_gaps_report(
    session: AsyncSession,
    tenant_id: str,
    *,
    start_date: date,
    end_date: date,
    local_timezone: timezone,
) -> dict[str, Any]:
    """Missing tracking days and interrupted spans, for the metrics that have them."""
    cadence_overrides = await _cadence_overrides(session, tenant_id)

    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    window_end = datetime.combine(
        end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )

    # Filtered in SQL, not in Python. Half the registry is event-driven and would
    # be discarded after Postgres had selected, transferred and decoded it — and
    # the discarded half is the high-volume one, GPS traces and per-minute samples.
    judged = [
        key
        for key, definition in METRIC_CATALOG.items()
        if definition.cadence in (Cadence.DAILY, Cadence.CONTINUOUS)
    ]
    judged.extend(
        key
        for key, cadence in cadence_overrides.items()
        if cadence in (Cadence.DAILY, Cadence.CONTINUOUS)
    )
    rows = (
        await session.execute(
            select(DataPoint.metric_type, DataPoint.timestamp).where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.metric_type.in_(judged),
                DataPoint.timestamp >= window_start,
                DataPoint.timestamp < window_end,
            )
        )
    ).all()

    gaps = detect_daily_gaps(
        rows,
        start_date,
        end_date,
        local_timezone=local_timezone,
        cadence_overrides=cadence_overrides,
    )
    cadence_gaps = detect_cadence_gaps(
        rows,
        TimeRange(window_start, window_end),
        cadence_overrides=cadence_overrides,
    )
    return {
        "tenant_id": tenant_id,
        "gaps": gaps,
        "missing_count": sum(len(gap["missing_dates"]) for gap in gaps),
        # Continuous metrics report interrupted spans rather than missing days:
        # a calendar day is the wrong unit for something sampled every minute.
        "cadence_gaps": cadence_gaps,
    }


async def compute_conflicts_report(
    session: AsyncSession,
    tenant_id: str,
    *,
    tolerance: float = DEFAULT_CONFLICT_TOLERANCE,
) -> dict[str, Any]:
    """Same-day values from different connectors that disagree beyond a tolerance."""
    rows = await session.execute(
        select(
            DataPoint.id,
            DataPoint.source_id,
            DataPoint.metric_type,
            DataPoint.timestamp,
            DataPoint.value,
        )
        .where(DataPoint.tenant_id == tenant_id)
        .order_by(DataPoint.timestamp.desc())
        .limit(CONFLICT_SCAN_POINTS)
    )
    points = [
        {
            "id": row.id,
            "source_id": row.source_id,
            "metric_type": row.metric_type,
            "timestamp": row.timestamp,
            "value": row.value,
        }
        for row in rows
    ]
    conflicts = find_cross_source_conflicts(points, tolerance)
    for conflict in conflicts:
        for candidate in conflict["candidates"]:
            candidate["timestamp"] = candidate["timestamp"].isoformat()
    return {"tenant_id": tenant_id, "conflicts": conflicts}


async def compute_core_report(
    session: AsyncSession, tenant_id: str, kind: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch to the computation for a kind Core owns."""
    if kind == "gaps":
        window_days = int(params.get("window_days") or DEFAULT_GAP_WINDOW_DAYS)
        offset_minutes = int(params.get("offset_minutes") or 0)
        end_date = datetime.now(timezone.utc).date()
        return await compute_gaps_report(
            session,
            tenant_id,
            start_date=end_date - timedelta(days=window_days - 1),
            end_date=end_date,
            local_timezone=timezone(timedelta(minutes=offset_minutes)),
        )
    if kind == "conflicts":
        tolerance = float(params.get("tolerance") or DEFAULT_CONFLICT_TOLERANCE)
        return await compute_conflicts_report(session, tenant_id, tolerance=tolerance)
    if kind == "day":
        return await compute_day_report(session, tenant_id, params)
    raise ValueError(f"{kind} is not computed by Core")


async def compute_day_report(
    session: AsyncSession, tenant_id: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Yesterday and today in one stored answer.

    Both days in one report rather than one report per day, because that is what
    the page renders and because a report is one row per (tenant, kind). Storing
    a row per calendar day would make the table grow without bound to hold
    answers nobody will ask for again.

    The offset is recorded in the run's params, which is what lets the staleness
    check know when the reader's midnight has passed.
    """
    # Imported here rather than at module scope: `core.daily_story` imports this
    # module for the primary-source resolver, so binding the name at load time
    # would be a cycle.
    from core.daily_story import build_day_story

    offset_minutes = int(params.get("offset_minutes") or 0)
    today = (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).date()
    yesterday = today - timedelta(days=1)

    return {
        "tenant_id": tenant_id,
        "offset_minutes": offset_minutes,
        "days": [
            await build_day_story(
                session, tenant_id, day=day, offset_minutes=offset_minutes
            )
            for day in (yesterday, today)
        ],
    }


async def run_core_report(
    session: AsyncSession,
    *,
    tenant_id: str,
    kind: str,
    trigger: str,
    request_id: str,
    params: dict[str, Any] | None = None,
) -> ReportRun:
    """Open a run, compute it, and record the outcome either way.

    The caller commits. A failure is stored as a failed run rather than raised,
    because a scheduled tick must go on to the next tenant and a reader must go
    on seeing the last good answer.
    """
    resolved = resolved_report_params(kind, params)
    run = await open_report_run(
        session,
        tenant_id=tenant_id,
        kind=kind,
        trigger=trigger,
        request_id=request_id,
        params=resolved,
    )
    try:
        payload = await compute_core_report(session, tenant_id, kind, resolved)
    except Exception as exc:
        # One bad report must not stop the tick, and must not lose the last good one.
        logger.exception("Report %s failed for tenant=%s", kind, tenant_id)
        fail_report_run(run, "report_failed", type(exc).__name__)
        return run
    finish_report_run(run, payload)
    return run


async def enqueue_report_run(
    session: AsyncSession,
    *,
    tenant_id: str,
    kind: str,
    trigger: str,
    request_id: str,
    params: dict[str, Any] | None = None,
) -> ReportRun:
    """Record a run the Analysis Service will pick up and complete.

    `insights` is not computed here — Core does not do data science (rule 3). The
    queued row is both the work item and the in-flight marker: it is what
    `ListDueAnalysisReports` hands out and what stops a second tick, or a second
    refresh click, from queueing the same work twice.
    """
    run = ReportRun(
        tenant_id=tenant_id,
        kind=kind,
        status="queued",
        trigger=trigger,
        request_id=request_id[:128],
        params=params or {},
        covers_data_through=await tenant_data_high_water(session, tenant_id),
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    await session.flush()
    return run


async def claim_due_analysis_runs(
    session: AsyncSession, *, limit: int = 20
) -> list[ReportRun]:
    """Queued insight runs, oldest first, marked as running as they are handed out.

    `SKIP LOCKED` rather than a plain select: two Analysis replicas polling at the
    same moment must not both receive the same run. The row moves to `running` in
    the same transaction that selects it, so the second caller sees it gone rather
    than duplicating a minute of computation.
    """
    rows = list(
        (
            await session.execute(
                select(ReportRun)
                .where(ReportRun.kind == "insights", ReportRun.status == "queued")
                .order_by(ReportRun.started_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
    )
    for run in rows:
        run.status = "running"
    return rows


async def run_report_tick(*, now: datetime | None = None) -> int:
    """One scheduling tick. Returns how many reports were computed or queued.

    Mirrors `core.scheduler.run_once`, including the single-flight advisory lock:
    several Core replicas each tick on their own timer, and without it each would
    recompute every due report.
    """
    now = now or datetime.now(timezone.utc)
    handled = 0

    async with async_session_maker() as session:
        if not await acquire_tick_lock(session):
            logger.debug("Another replica holds the report lock; skipping this tick")
            return 0
        due = await find_due_reports(session, now=now)
        await session.commit()

    for item in due:
        # One session per report, so a failure rolls back only its own work and
        # a long computation does not hold the tick's lock while it runs.
        try:
            async with async_session_maker() as session:
                await acquire_report_lock(session, item.tenant_id, item.kind)
                # Re-checked under the lock: another replica may have started this
                # between the tick's scan and now.
                if await has_in_flight_report(session, item.tenant_id, item.kind, now=now):
                    await session.commit()
                    continue
                if item.kind in CORE_COMPUTED_KINDS:
                    await run_core_report(
                        session,
                        tenant_id=item.tenant_id,
                        kind=item.kind,
                        trigger="scheduled",
                        request_id=f"report-{item.kind}-{item.tenant_id}",
                        params=item.params,
                    )
                else:
                    await enqueue_report_run(
                        session,
                        tenant_id=item.tenant_id,
                        kind=item.kind,
                        trigger="scheduled",
                        request_id=f"report-{item.kind}-{item.tenant_id}",
                        params=item.params,
                    )
                await session.commit()
                handled += 1
        except Exception:
            # One bad tenant must not stop the rest of the tick, for the same
            # reason `run_once` catches per connector.
            logger.exception(
                "Report %s failed for tenant=%s", item.kind, item.tenant_id
            )

    if handled:
        logger.info("Report scheduler handled %s report(s)", handled)
    return handled


async def acquire_tick_lock(session: AsyncSession) -> bool:
    """Try to become the replica that runs this report tick."""
    result = await session.execute(
        select(func.pg_try_advisory_xact_lock(REPORT_TICK_LOCK_KEY))
    )
    return bool(result.scalar())


async def run_report_scheduler(*, tick_seconds: int = REPORT_TICK_SECONDS) -> None:
    """Tick forever. Cancelled by the caller on shutdown."""
    logger.info("Report scheduler started (tick=%ss)", tick_seconds)
    while True:
        try:
            await asyncio.sleep(tick_seconds)
            await run_report_tick()
        except asyncio.CancelledError:
            logger.info("Report scheduler stopped")
            raise
        except Exception:
            # A scheduler that dies on one bad tick is worse than no scheduler:
            # it looks like it is running.
            logger.exception("Report tick failed; continuing")


def report_payload(
    run: ReportRun | None,
    *,
    stale: bool,
    error: ReportRun | None = None,
) -> dict[str, Any]:
    """The wire shape of a stored report.

    `computed_at` and `stale` travel with the result on purpose: a reader shown a
    precomputed number is entitled to know when it was true, and a number with no
    date on it is the reason on-the-fly computation felt safer than it was.
    """
    if run is None:
        payload: dict[str, Any] = {
            "status": "never_computed",
            "stale": True,
            "computed_at": None,
            "covers_data_through": None,
            "params": {},
            "result": None,
        }
    else:
        payload = {
            "status": "ready",
            "stale": stale,
            "computed_at": run.finished_at.isoformat() if run.finished_at else None,
            "covers_data_through": (
                run.covers_data_through.isoformat() if run.covers_data_through else None
            ),
            "params": run.params or {},
            "result": run.payload,
        }
    payload["error"] = (
        {
            "code": error.message_code or "report_failed",
            "params": error.message_params or {},
            "message": error.message,
        }
        if error is not None
        else None
    )
    return payload
