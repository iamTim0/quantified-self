"""Periodic sync scheduling.

`poll_interval_hours` was stored on every connector, echoed back to the UI, used
to size the adaptive import window -- and read by nothing that ever started a
sync. There was no scheduler anywhere in the repository, so every import happened
because somebody pressed a button.

Scheduling lives in Core because Core owns the two things the decision needs: the
connector configuration and the sync history. An importer cannot make it -- it
has no database access (rule 1) and no idea when it last succeeded.

Two failure modes shape the design:

* **More than one Core replica.** Each would tick on its own timer and enqueue the
  same connector. A Postgres advisory lock makes a tick single-flight across every
  replica sharing the database. Transaction-scoped (`pg_try_advisory_xact_lock`),
  so a crashed replica releases it when its connection dies rather than wedging
  scheduling until someone notices.
* **A sync that is already running.** Re-enqueuing it wastes an external API
  budget and can trip a provider's rate limit. Idempotency keeps the data correct
  either way, but correct-and-wasteful is still wrong. Core refuses to enqueue a
  connector that already has an in-flight run -- which is also what makes the
  importers' process-local `active_syncs` guard no longer load-bearing: the
  duplicate never reaches them.

Maps to Fizzbee Invariants:
- NoDuplicateData
- SchedulerSingleFlight
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.connectors import is_scheduled
from core.db.models import DataSource, SyncRun, Tenant
from core.db.session import async_session_maker
from core.deployment_warnings import Warning_

logger = logging.getLogger(__name__)

# Arbitrary but fixed: an advisory lock key is just a 64-bit integer, and every
# replica has to pick the same one.
SCHEDULER_LOCK_KEY = 0x5153_5343_4845_4400  # "QSSCHED\0"

# How often to look for due connectors. Not the poll interval -- that is
# per-connector and measured in hours. This only bounds how late a due sync can
# be.
TICK_SECONDS = 300

# A run that has been "running" for longer than this is assumed dead: the
# importer crashed, or the message was never delivered. Without this a single
# lost task would block a connector forever.
STALE_RUN_AFTER = timedelta(hours=6)

# Statuses that mean "this connector is busy".
# Core loading is still part of the same import. A second scheduled run must
# wait until the consumer has drained the first run's events, otherwise the
# connector can report two overlapping imports while its first batch is only
# just being written.
IN_FLIGHT_STATUSES = ("queued", "running", "loading")

DEFAULT_POLL_INTERVAL_HOURS = 6.0

# After how many consecutive lock denials the scheduler says so out loud. Twelve
# ticks is an hour: long enough that ordinary contention between replicas never
# reaches it, short enough that a wedged lock is reported the same morning.
LOCK_DENIED_TICKS_BEFORE_WARNING = 12

#: Consecutive ticks that could not take the lock. Module-level because the tick is
#: a function, not an object, and the count is what distinguishes "another replica
#: is working" from "nothing will ever schedule again".
_lock_denied_ticks = 0


@dataclass(frozen=True)
class DueConnector:
    tenant_id: str
    source_id: str
    source_type: str
    poll_interval_hours: float
    last_sync_at: datetime | None


def _parse_timestamp(raw: Any) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def poll_interval_hours(config: dict[str, Any] | None) -> float:
    """The configured interval, clamped to something sane.

    A zero or negative value would make every connector permanently due and turn
    the scheduler into a hot loop against someone's API.
    """
    raw = (config or {}).get("poll_interval_hours", DEFAULT_POLL_INTERVAL_HOURS)
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_POLL_INTERVAL_HOURS
    if hours <= 0:
        return DEFAULT_POLL_INTERVAL_HOURS
    return min(hours, 24.0 * 7)


def is_due(config: dict[str, Any] | None, *, now: datetime) -> bool:
    """Whether a connector's poll interval has elapsed.

    A connector that has never synced is due immediately -- that is the case of a
    user who just configured one and is waiting to see data.
    """
    last = _parse_timestamp((config or {}).get("last_sync_at"))
    if last is None:
        return True
    return now - last >= timedelta(hours=poll_interval_hours(config))


async def has_in_flight_run(
    session: AsyncSession, tenant_id: str, source_id: str, *, now: datetime
) -> bool:
    """Is a sync for this connector already queued or running (and not stale)?

    Keyed on the connector instance. Keyed on the *type*, one of a tenant's two
    calendars importing would have blocked the other for up to `STALE_RUN_AFTER`,
    and the second would have looked simply broken.
    """
    cutoff = now - STALE_RUN_AFTER
    result = await session.execute(
        select(SyncRun.id)
        .where(
            SyncRun.tenant_id == tenant_id,
            SyncRun.source_id == source_id,
            SyncRun.status.in_(IN_FLIGHT_STATUSES),
            SyncRun.started_at >= cutoff,
        )
        .limit(1)
    )
    return result.scalars().first() is not None


def connector_lock_key(tenant_id: str, source_id: str) -> int:
    """Return a stable PostgreSQL advisory-lock key for one connector instance.

    The lock is deliberately keyed by both tenant and source. A tenant's two
    connectors can plan independently, while every Core replica still uses the
    same key for the same connector. A digest avoids relying on Python's process-
    randomised ``hash()`` implementation.
    """
    digest = hashlib.blake2b(
        f"{tenant_id}:{source_id}".encode(), digest_size=8
    ).digest()
    key = int.from_bytes(digest, byteorder="big", signed=True)
    return key or 1


async def acquire_connector_lock(
    session: AsyncSession, tenant_id: str, source_id: str
) -> None:
    """Serialize planning and run creation for one tenant-scoped connector.

    This is transaction-scoped, so a crashed request releases the lock with its
    database transaction. Waiting rather than returning ``False`` is important:
    the second request must re-check ``has_in_flight_run`` after the first request
    commits, otherwise two simultaneous clicks can both pass the check.
    """
    await session.execute(
        select(func.pg_advisory_xact_lock(connector_lock_key(tenant_id, source_id)))
    )


async def expire_stale_runs(
    session: AsyncSession,
    source: DataSource,
    *,
    now: datetime,
) -> int:
    """Mark importer runs that stopped reporting as failed.

    A crashed importer cannot call the status endpoint. Expiring the run here keeps
    the connector history truthful and lets the next scheduled attempt proceed.
    The update is scoped to the source's tenant and connector instance.
    """
    cutoff = now - STALE_RUN_AFTER
    result = await session.execute(
        update(SyncRun)
        .where(
            SyncRun.tenant_id == source.tenant_id,
            SyncRun.source_id == source.id,
            SyncRun.status.in_(IN_FLIGHT_STATUSES),
            SyncRun.started_at < cutoff,
        )
        .values(
            status="error",
            message="The importer did not report completion before the run timeout.",
            finished_at=now,
        )
    )
    expired = result.rowcount or 0
    if expired:
        config = dict(source.config or {})
        config["sync_status"] = "error"
        config["last_sync_message"] = (
            "The importer did not report completion before the run timeout."
        )
        source.config = config
    return expired


async def find_due_connectors(
    session: AsyncSession, *, now: datetime
) -> list[DueConnector]:
    """Every connector across every tenant whose interval has elapsed.

    Deliberately not filtered by tenant: this is the one code path that acts on
    behalf of all of them. Each enqueue that follows is still tenant-scoped, and
    the events it publishes still carry their own tenant_id (rule 2).
    """
    # The scheduler is intentionally cross-tenant, but it still scopes the source
    # relation to real tenant rows. This keeps the global worker explicit about the
    # tenant boundary instead of issuing an unqualified source-table scan.
    rows = (
        await session.execute(
            select(DataSource).where(
                DataSource.tenant_id.in_(select(Tenant.id)),
                DataSource.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    due: list[DueConnector] = []
    for source in rows:
        config = source.config or {}
        await expire_stale_runs(session, source, now=now)
        # Push connectors have no task subject anybody listens on. Planning a sync
        # for one produced a `SyncRun` that could only ever expire as stale, and
        # left the connector looking permanently queued in the meantime.
        if not is_scheduled(source.source_type, config):
            continue
        if config.get("status") == "inactive":
            continue
        if not is_due(config, now=now):
            continue
        if await has_in_flight_run(session, source.tenant_id, source.id, now=now):
            logger.debug(
                "Connector %s/%s (%s) is due but already has a run in flight",
                source.tenant_id,
                source.source_type,
                source.id,
            )
            continue
        due.append(
            DueConnector(
                tenant_id=source.tenant_id,
                source_id=source.id,
                source_type=source.source_type,
                poll_interval_hours=poll_interval_hours(config),
                last_sync_at=_parse_timestamp(config.get("last_sync_at")),
            )
        )
    return due


async def acquire_tick_lock(session: AsyncSession) -> bool:
    """Try to become the replica that runs this tick.

    Transaction-scoped, so it is released by commit, rollback, or the connection
    dying. A session-scoped lock would survive a crashed replica and stop
    scheduling entirely until somebody restarted the database.
    """
    result = await session.execute(
        select(func.pg_try_advisory_xact_lock(SCHEDULER_LOCK_KEY))
    )
    return bool(result.scalar())


async def run_once(
    enqueue: Callable[[DueConnector], Awaitable[None]], *, now: datetime | None = None
) -> int:
    """One scheduling tick. Returns how many syncs were enqueued."""
    now = now or datetime.now(timezone.utc)

    global _lock_denied_ticks

    # ── Phase 1: decide, under the lock, and commit before doing anything ──────
    #
    # The commit is the fix for a production deadlock that stopped every scheduled
    # import for a day, and it is worth stating exactly, because the shape recurs
    # whenever a transaction is held across a call that opens its own.
    #
    # `expire_stale_runs` writes `data_sources.config` when it retires a dead run,
    # so this transaction held a row lock on that connector. `enqueue` then opened a
    # *separate* session — deliberately, so one connector's failure cannot roll back
    # another's `SyncRun` — and its `UPDATE data_sources SET config = …` blocked on
    # that row lock. The outer transaction was meanwhile waiting, in Python, for
    # `enqueue` to return.
    #
    # Postgres cannot break that: the outer connection is not waiting on a database
    # lock, so there is no cycle for the deadlock detector to see. It simply hung,
    # holding `SCHEDULER_LOCK_KEY`, and every later tick failed
    # `pg_try_advisory_xact_lock` and returned silently. Worse, it was
    # self-perpetuating — the expiry never committed, so the stale run that
    # triggered it was still there for the next tick to trip over, which is why a
    # restart did not clear it.
    async with async_session_maker() as session:
        if not await acquire_tick_lock(session):
            _lock_denied_ticks += 1
            # `warning`, not `debug`, once this stops looking like contention. A
            # permanently held lock and an idle scheduler produce identical silence,
            # and the whole failure above was invisible for a day for that reason.
            if _lock_denied_ticks >= LOCK_DENIED_TICKS_BEFORE_WARNING:
                logger.warning(
                    "Scheduler lock unavailable for %s consecutive ticks (~%s min). "
                    "A held advisory lock stops every scheduled import; look for a "
                    "connection idle in transaction.",
                    _lock_denied_ticks,
                    int(_lock_denied_ticks * TICK_SECONDS / 60),
                )
            return 0
        _lock_denied_ticks = 0

        due = await find_due_connectors(session, now=now)
        # Before any enqueue, so no row lock is held while another session writes.
        await session.commit()

    # ── Phase 2: act, with no transaction and no lock held ────────────────────
    enqueued = 0
    for connector in due:
        try:
            await enqueue(connector)
            enqueued += 1
        except Exception:
            # One bad connector must not stop the rest of the tick.
            logger.exception(
                "Scheduled sync failed to enqueue for %s/%s",
                connector.tenant_id,
                connector.source_type,
            )

    if enqueued:
        logger.info("Scheduler enqueued %s sync(s)", enqueued)
    return enqueued


async def run_scheduler(
    enqueue: Callable[[DueConnector], Awaitable[None]],
    *,
    tick_seconds: int = TICK_SECONDS,
) -> None:
    """Tick forever. Cancelled by the caller on shutdown."""
    logger.info("Sync scheduler started (tick=%ss)", tick_seconds)
    while True:
        try:
            await asyncio.sleep(tick_seconds)
            await run_once(enqueue)
        except asyncio.CancelledError:
            logger.info("Sync scheduler stopped")
            raise
        except Exception:
            # A scheduler that dies on one bad tick is worse than no scheduler:
            # it looks like it is running.
            logger.exception("Scheduler tick failed; continuing")


# ── The stale-run sweep, deliberately not part of the sync tick ───────────────
#
# `expire_stale_runs` is called from `find_due_connectors` and that is still the
# right place: a dead run should not delay the connector it belongs to by a whole
# sweep interval. But it was the *only* place, and that turned out to be a trap.
#
# The tick that would have retired a dead run is the same tick that wedged on the
# advisory lock, so the repair died with the thing it repairs — a weather run sat in
# `loading` for twenty-seven hours while the mechanism designed to retire it was in
# the queue behind it. A heal job that lives inside its own subject heals nothing.
#
# So this runs on its own timer, under its own lock, reachable even when the sync
# scheduler cannot take a step.

#: Its own key, so a held sync lock cannot stop the sweep as well.
STALE_SWEEP_LOCK_KEY = 0x5153_5354_414C_4500  # "QSSTALE\0"

#: Slower than the sync tick. Retiring a run that has already been dead for six
#: hours is not urgent; being able to do it at all is the point.
STALE_SWEEP_TICK_SECONDS = 600


async def sweep_stale_runs(*, now: datetime | None = None) -> int:
    """Retire dead runs for every connector, independently of the sync tick.

    Cross-tenant like the scheduler itself, and scoped to real tenant rows for the
    same reason (rule 2). Returns how many runs were retired.
    """
    now = now or datetime.now(timezone.utc)
    async with async_session_maker() as session:
        held = await session.execute(
            select(func.pg_try_advisory_xact_lock(STALE_SWEEP_LOCK_KEY))
        )
        if not bool(held.scalar()):
            return 0

        sources = (
            await session.execute(
                select(DataSource).where(
                    DataSource.tenant_id.in_(select(Tenant.id)),
                    DataSource.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        expired = 0
        for source in sources:
            expired += await expire_stale_runs(session, source, now=now)
        await session.commit()

    if expired:
        logger.info("Stale-run sweep retired %s run(s)", expired)
    return expired


async def run_stale_run_sweep(*, tick_seconds: int = STALE_SWEEP_TICK_SECONDS) -> None:
    """Tick forever. Cancelled by the caller on shutdown."""
    logger.info("Stale-run sweep started (tick=%ss)", tick_seconds)
    while True:
        try:
            await asyncio.sleep(tick_seconds)
            await sweep_stale_runs()
        except asyncio.CancelledError:
            logger.info("Stale-run sweep stopped")
            raise
        except Exception:
            logger.exception("Stale-run sweep failed; continuing")


# ── Saying it out loud ────────────────────────────────────────────────────────


#: How far past its interval a connector has to be before the dashboard says so.
#: Three intervals, so an import that merely ran late never raises it, and a
#: connector that has genuinely stopped does within the day.
OVERDUE_INTERVAL_FACTOR = 3.0


async def overdue_connector_warning(
    session: AsyncSession, tenant_id: str, *, now: datetime | None = None
) -> Warning_ | None:
    """A connector that should have imported long ago, as something a reader sees.

    This is the finding of an outage rather than a nicety. Scheduled imports stopped
    for a day and nothing said so: the tick was wedged on an advisory lock, the only
    log line for that was `debug`, and every connector kept its last successful run
    on its card as though it were current. The data simply stopped arriving, and the
    interface looked exactly as it does when everything is fine.

    A repair mechanism was not what was missing — the sweep existed. What was missing
    was anybody knowing. So the condition is reported where the operator already
    looks, through the same `code`/`params` channel as the rest (rule 17).

    Tenant-scoped: this is one workspace's view of its own connectors (rule 2).
    """
    now = now or datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(DataSource).where(
                DataSource.tenant_id == tenant_id,
                DataSource.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    worst_name: str | None = None
    worst_hours = 0.0
    overdue = 0
    for source in rows:
        config = source.config or {}
        if not is_scheduled(source.source_type, config):
            continue
        if config.get("status") == "inactive":
            continue
        last = _parse_timestamp(config.get("last_sync_at"))
        if last is None:
            # Never synced is the case of a connector just configured. `is_due`
            # treats it as due immediately and the first tick will take it; calling
            # that "overdue" would greet every new connector with a warning.
            continue
        interval = poll_interval_hours(config)
        late_hours = (now - last).total_seconds() / 3600.0
        if late_hours < interval * OVERDUE_INTERVAL_FACTOR:
            continue
        overdue += 1
        if late_hours > worst_hours:
            worst_hours = late_hours
            worst_name = source.display_name or source.source_type

    if not overdue or worst_name is None:
        return None

    return Warning_(
        code="connectors_overdue",
        severity="warning",
        title="Scheduled imports are not running",
        detail=(
            f"{overdue} connector(s) are past their poll interval. The longest, "
            f"{worst_name}, last imported {int(worst_hours)} hours ago."
        ),
        action=(
            "Check Core's scheduler log. A connection left idle in transaction holds "
            "the scheduler's advisory lock and stops every scheduled import."
        ),
        params={
            "count": str(overdue),
            "connector": worst_name,
            "hours": str(int(worst_hours)),
        },
    )
