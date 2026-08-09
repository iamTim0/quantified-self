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
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.connectors import is_scheduled
from core.db.models import DataSource, SyncRun
from core.db.session import async_session_maker

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
IN_FLIGHT_STATUSES = ("queued", "running")

DEFAULT_POLL_INTERVAL_HOURS = 6.0


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
    rows = (await session.execute(select(DataSource))).scalars().all()

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

    async with async_session_maker() as session:
        if not await acquire_tick_lock(session):
            logger.debug("Another replica holds the scheduler lock; skipping this tick")
            return 0

        due = await find_due_connectors(session, now=now)

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

        # Releases the advisory lock.
        await session.commit()

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
