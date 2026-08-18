"""Recover the history a field missed while nothing knew how to store it.

A provider field that arrives before this platform can map it is recorded in
`ingest_field_reports` with `metric_type = NULL` and kept nowhere else. When a
later importer release learns the mapping, the upsert stamps `supported_since`
on that row — and from that moment the field is stored going forward, while
every reading that arrived in the meantime is still missing. **Support arriving
today does nothing whatsoever for yesterday**, and the Data Quality Center said
as much: it reported the gap, named its two ends, and left the user to go and
force an import over it by hand.

Recovering it is a force import across that span. The provider still holds the
readings, the transformer now knows what they are, and idempotency (rule 4)
makes re-importing a range that is already partly present harmless — which is
exactly why this can be automatic rather than a button. The cost that remains
is the provider's API budget, and that is what the bounds below are for.

Three things bound it:

* **Only connectors that can be re-imported.** `is_scheduled` rather than a
  push-type check: a push connector's history lives in the device that sent it,
  and a file-import connector's lives in an archive nobody but the user has. For
  both, a planned run is a row that can only expire.
* **One import per connector, not one per field.** A single importer release
  routinely maps a dozen paths at once. Those become one force run over the
  union of their spans, because they are one provider fetch.
* **A capped span.** `MAX_BACKFILL_WINDOW` — an unsupported field can predate
  its support by a year, and re-fetching a year is the most expensive thing this
  platform can ask of a provider. A longer gap gets its most recent 90 days
  rather than nothing, and the run says it was shortened. The rest stays
  available through the manual force import the Data Quality Center already
  offers; walking backwards over successive sweeps would cover it, at the price
  of repeatedly re-fetching a connector's whole history for a case that arises
  when a mapping lands years late.

A row is stamped `history_backfilled_at` only when the run was actually queued.
A connector that was busy this tick is simply picked up on the next one, which
is what makes "it did not run" different from "it ran and found nothing".

Maps to Fizzbee Invariants:
- NoDuplicateData
- SchedulerSingleFlight
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.connectors import is_scheduled
from core.db.models import DataSource, IngestFieldReport, Tenant
from core.db.session import async_session_maker

logger = logging.getLogger(__name__)

#: Advisory-lock key for this sweep. Distinct from the sync scheduler's, so a
#: backfill tick and a scheduling tick do not exclude one another — they touch
#: different rows and block on the same per-connector lock where they overlap.
BACKFILL_LOCK_KEY = 0x5153_4241_434B_4600  # "QSBACKF\0"

#: A support transition is not urgent: the data has been missing for as long as
#: the field was unsupported, and a quarter of an hour more changes nothing. The
#: interval mainly keeps the sweep off the 5-minute path the sync scheduler owns.
TICK_SECONDS = 900

#: The furthest back one automatic backfill will reach.
#:
#: Not a statement about what is worth recovering — it is a bound on what this
#: platform will spend of somebody's API quota without being asked. Ninety days
#: covers the case this exists for (a field supported by an importer release
#: within the last few months) and stops short of re-fetching a year.
MAX_BACKFILL_WINDOW = timedelta(days=90)

#: How many field rows one tick will consider. A ceiling, not a target: the query
#: normally returns nothing at all, because a transition happens when an importer
#: is released and not otherwise.
MAX_ROWS_PER_TICK = 500


@dataclass(frozen=True)
class PendingBackfill:
    """One connector's worth of newly supported fields, and the span they missed."""

    tenant_id: str
    source_id: str
    source_type: str
    window_start: datetime
    window_end: datetime
    field_paths: tuple[str, ...]
    report_ids: tuple[str, ...]
    #: True when `MAX_BACKFILL_WINDOW` shortened the span, so the caller can say so
    #: rather than implying the whole gap was covered.
    truncated: bool


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def find_pending_backfills(
    session: AsyncSession, *, now: datetime | None = None
) -> list[PendingBackfill]:
    """Every connector across every tenant with unrecovered field history.

    Deliberately not filtered by tenant, for the same reason `find_due_connectors`
    is not: this is a worker that acts for all of them. The source relation is
    still scoped to real tenant rows so the boundary stays explicit, and every
    enqueue that follows is tenant-scoped again (rule 2).
    """
    now = now or datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(IngestFieldReport, DataSource)
            .join(DataSource, DataSource.id == IngestFieldReport.source_id)
            .where(
                IngestFieldReport.tenant_id.in_(select(Tenant.id)),
                IngestFieldReport.supported_since.is_not(None),
                IngestFieldReport.history_backfilled_at.is_(None),
                # No gap, nothing to recover: the field was mapped the first time it
                # was ever seen, so its history was stored as it arrived.
                IngestFieldReport.first_seen_at < IngestFieldReport.supported_since,
                DataSource.deleted_at.is_(None),
            )
            .order_by(
                IngestFieldReport.tenant_id,
                IngestFieldReport.source_id,
                IngestFieldReport.field_path,
            )
            .limit(MAX_ROWS_PER_TICK)
        )
    ).all()

    grouped: dict[tuple[str, str], list[tuple[IngestFieldReport, DataSource]]] = {}
    for report, source in rows:
        config = source.config or {}
        # A push or file connector cannot be re-imported at all. Its rows are left
        # unstamped on purpose: if the same connector ever becomes re-importable,
        # the history is still there to recover.
        if not is_scheduled(source.source_type, config):
            continue
        if config.get("status") == "inactive":
            continue
        grouped.setdefault((report.tenant_id, report.source_id), []).append((report, source))

    pending: list[PendingBackfill] = []
    for (tenant_id, source_id), entries in grouped.items():
        reports = [report for report, _ in entries]
        source = entries[0][1]
        window_end = max(_as_utc(r.supported_since) for r in reports)
        earliest = min(_as_utc(r.first_seen_at) for r in reports)
        floor = window_end - MAX_BACKFILL_WINDOW
        # Always a real span: `floor` is strictly before `window_end`, and the query
        # already required `first_seen_at < supported_since`. A gap longer than the
        # cap therefore recovers its most recent `MAX_BACKFILL_WINDOW` and reports
        # `truncated`, rather than being skipped — most of something beats none of
        # it, and the part that was not fetched is named on the run.
        window_start = max(earliest, floor)
        pending.append(
            PendingBackfill(
                tenant_id=tenant_id,
                source_id=source_id,
                source_type=source.source_type,
                window_start=window_start,
                window_end=window_end,
                field_paths=tuple(sorted(r.field_path for r in reports)),
                report_ids=tuple(r.id for r in reports),
                truncated=earliest < floor,
            )
        )
    return pending


async def mark_backfilled(
    session: AsyncSession, pending: PendingBackfill, *, now: datetime | None = None
) -> int:
    """Record that this connector's newly supported fields have been re-imported.

    By row id and tenant, not by predicate: a field that became supported between
    the select and here has a gap this run's window does not cover, and stamping it
    would mean its history is never recovered by anything.
    """
    now = now or datetime.now(timezone.utc)
    result = await session.execute(
        update(IngestFieldReport)
        .where(
            IngestFieldReport.tenant_id == pending.tenant_id,
            IngestFieldReport.id.in_(pending.report_ids),
            IngestFieldReport.history_backfilled_at.is_(None),
        )
        .values(history_backfilled_at=now)
    )
    return result.rowcount or 0


def window_reason(pending: PendingBackfill) -> str:
    """What this run is for, in the field that the import history already shows."""
    count = len(pending.field_paths)
    noun = "field" if count == 1 else "fields"
    scope = "part of the period" if pending.truncated else "the period"
    return (
        f"Automatic recovery of {count} newly supported {noun} over {scope} "
        f"they arrived unstored."
    )


async def acquire_tick_lock(session: AsyncSession) -> bool:
    """Try to become the replica that runs this tick.

    Transaction-scoped, so a replica that dies releases it rather than wedging the
    sweep until somebody restarts the database.
    """
    result = await session.execute(select(func.pg_try_advisory_xact_lock(BACKFILL_LOCK_KEY)))
    return bool(result.scalar())


async def run_once(
    enqueue: Callable[[PendingBackfill], Awaitable[bool]],
    *,
    now: datetime | None = None,
) -> int:
    """One sweep. Returns how many backfill imports were enqueued."""
    now = now or datetime.now(timezone.utc)

    async with async_session_maker() as session:
        if not await acquire_tick_lock(session):
            logger.debug("Another replica holds the backfill lock; skipping this tick")
            return 0
        pending = await find_pending_backfills(session, now=now)
        # Releases the advisory lock before the enqueues, which open their own
        # sessions. Holding it across a provider-bound plan would serialise every
        # replica behind the slowest one.
        await session.commit()

    enqueued = 0
    for item in pending:
        try:
            if not await enqueue(item):
                # Busy, or refused for a reason the run itself records. Unstamped,
                # so the next tick tries again.
                continue
        except Exception:
            logger.exception(
                "Field-history backfill failed to enqueue for %s/%s",
                item.tenant_id,
                item.source_type,
            )
            continue
        async with async_session_maker() as session:
            await mark_backfilled(session, item, now=now)
            await session.commit()
        enqueued += 1
        logger.info(
            "Backfilling %s newly supported field(s) for %s from %s to %s%s",
            len(item.field_paths),
            item.source_type,
            item.window_start.isoformat(),
            item.window_end.isoformat(),
            " (window capped)" if item.truncated else "",
        )
    return enqueued


async def run_field_backfill_scheduler(
    enqueue: Callable[[PendingBackfill], Awaitable[bool]],
    *,
    tick_seconds: int = TICK_SECONDS,
) -> None:
    """Sweep forever. Cancelled by the caller on shutdown."""
    logger.info("Field-history backfill sweep started (tick=%ss)", tick_seconds)
    while True:
        try:
            await asyncio.sleep(tick_seconds)
            await run_once(enqueue)
        except asyncio.CancelledError:
            logger.info("Field-history backfill sweep stopped")
            raise
        except Exception:
            # A sweep that dies on one bad tick is worse than no sweep: it looks
            # like it is running.
            logger.exception("Field-history backfill tick failed; continuing")
