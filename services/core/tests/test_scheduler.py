"""Tests for periodic sync scheduling.

`poll_interval_hours` was stored, shown in the UI, used to size an import window
— and read by nothing that ever started a sync. These pin the behaviour that
makes it mean something, and the two things that go wrong when more than one Core
process exists.

Maps to Fizzbee Invariants:
- NoDuplicateData
- SchedulerSingleFlight
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataSource, SyncRun
from core.db.session import async_session_maker
from core.scheduler import (
    DueConnector,
    acquire_tick_lock,
    connector_lock_key,
    find_due_connectors,
    has_in_flight_run,
    is_due,
    poll_interval_hours,
    run_once,
    sweep_stale_runs,
)
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

NOW = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


# ── Policy: pure, no database ────────────────────────────────────────────────


def test_connector_lock_key_is_stable_and_connector_scoped():
    """Verifies Fizzbee Invariant: SchedulerSingleFlight."""
    tenant = str(uuid.uuid4())
    source = str(uuid.uuid4())

    assert connector_lock_key(tenant, source) == connector_lock_key(tenant, source)
    assert connector_lock_key(tenant, source) != connector_lock_key(tenant, str(uuid.uuid4()))
    assert connector_lock_key(tenant, source) != connector_lock_key(str(uuid.uuid4()), source)


def test_a_connector_that_never_synced_is_due():
    """Someone who just configured a connector is waiting for data now."""
    assert is_due({}, now=NOW) is True
    assert is_due({"poll_interval_hours": 6}, now=NOW) is True


def test_due_only_after_the_interval_has_elapsed():
    config = {
        "poll_interval_hours": 6,
        "last_sync_at": (NOW - timedelta(hours=5, minutes=59)).isoformat(),
    }
    assert is_due(config, now=NOW) is False

    config["last_sync_at"] = (NOW - timedelta(hours=6)).isoformat()
    assert is_due(config, now=NOW) is True


def test_a_nonsense_interval_falls_back_instead_of_hot_looping():
    """Zero or negative would make every connector permanently due.

    That is not a harmless default: the scheduler would hammer a third-party API
    every tick and get the user rate-limited.
    """
    for bad in (0, -1, "", None, "not-a-number"):
        assert poll_interval_hours({"poll_interval_hours": bad}) == 6.0

    # And an absurdly large one is clamped rather than trusted.
    assert poll_interval_hours({"poll_interval_hours": 100_000}) == 24.0 * 7


def test_naive_timestamps_are_treated_as_utc():
    """A stored timestamp without a zone must not crash the comparison."""
    config = {
        "poll_interval_hours": 1,
        "last_sync_at": (NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat(),
    }
    assert is_due(config, now=NOW) is True


# ── Against the database ─────────────────────────────────────────────────────


async def _connector(
    tenant_id: str, *, source_type: str, config: dict, display_name: str | None = None
) -> str:
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                display_name=display_name or source_type,
                config=config,
            )
        )
        await session.commit()
    return source_id


async def _run(
    tenant_id: str, source_type: str, source_id: str, *, status: str, started_at: datetime
):
    """A sync run attributed to one connector *instance*.

    `source_id` is what the scheduler now keys on: with two calendars, keying on
    the type let one connector's run block the other for six hours.
    """
    async with async_session_maker() as session:
        session.add(
            SyncRun(
                tenant_id=tenant_id,
                source_id=source_id,
                source_type=source_type,
                request_id=str(uuid.uuid4()),
                status=status,
                started_at=started_at,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_due_connector_is_found():
    tenant_id = await create_test_tenant()
    try:
        await _connector(
            tenant_id,
            source_type="oura",
            config={"poll_interval_hours": 1, "last_sync_at": (NOW - timedelta(hours=3)).isoformat()},
        )
        async with async_session_maker() as session:
            due = await find_due_connectors(session, now=NOW)
        mine = [d for d in due if d.tenant_id == tenant_id]
        assert [d.source_type for d in mine] == ["oura"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_connector_with_a_run_in_flight_is_skipped():
    """Re-enqueuing burns an API budget and can trip a rate limit.

    Verifies Fizzbee Invariant: NoDuplicateData
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(
            tenant_id, source_type="whoop", config={"poll_interval_hours": 1}
        )
        await _run(
            tenant_id, "whoop", source_id, status="running", started_at=NOW - timedelta(minutes=5)
        )

        async with async_session_maker() as session:
            due = await find_due_connectors(session, now=NOW)
        assert [d for d in due if d.tenant_id == tenant_id] == []
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_stale_run_does_not_block_forever():
    """An importer that crashed mid-run must not wedge its connector.

    Without an age cutoff a single lost task means that connector never syncs
    again, and nothing surfaces it -- the UI just shows "running".
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(
            tenant_id, source_type="yazio", config={"poll_interval_hours": 1}
        )
        await _run(
            tenant_id, "yazio", source_id, status="running", started_at=NOW - timedelta(hours=12)
        )

        async with async_session_maker() as session:
            assert (
                await has_in_flight_run(session, tenant_id, source_id, now=NOW)
            ) is False
            due = await find_due_connectors(session, now=NOW)
        assert [d.source_type for d in due if d.tenant_id == tenant_id] == ["yazio"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_finished_run_does_not_block():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(
            tenant_id, source_type="dawarich", config={"poll_interval_hours": 1}
        )
        await _run(
            tenant_id,
            "dawarich",
            source_id,
            status="success",
            started_at=NOW - timedelta(minutes=1),
        )

        async with async_session_maker() as session:
            assert (
                await has_in_flight_run(session, tenant_id, source_id, now=NOW)
            ) is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_one_instance_syncing_does_not_block_its_twin():
    """Two calendars are two connectors, not one busy one.

    Keyed on `source_type`, the second calendar was skipped for as long as the
    first was importing -- up to STALE_RUN_AFTER -- and looked simply broken.
    """
    tenant_id = await create_test_tenant()
    try:
        work = await _connector(
            tenant_id,
            source_type="calendar",
            display_name="Work",
            config={"poll_interval_hours": 1},
        )
        family = await _connector(
            tenant_id,
            source_type="calendar",
            display_name="Family",
            config={"poll_interval_hours": 1},
        )
        await _run(
            tenant_id, "calendar", work, status="running", started_at=NOW - timedelta(minutes=5)
        )

        async with async_session_maker() as session:
            assert await has_in_flight_run(session, tenant_id, work, now=NOW) is True
            assert await has_in_flight_run(session, tenant_id, family, now=NOW) is False
            due = await find_due_connectors(session, now=NOW)

        assert [d.source_id for d in due if d.tenant_id == tenant_id] == [family]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_push_connectors_are_never_scheduled():
    """Nothing subscribes to `qs.task.sync.apple_health`.

    Planning a sync for a push connector produced a SyncRun that could only ever
    expire as stale six hours later, while the connector showed as queued
    throughout.
    """
    tenant_id = await create_test_tenant()
    try:
        await _connector(
            tenant_id, source_type="apple_health", config={"poll_interval_hours": 1}
        )
        async with async_session_maker() as session:
            due = await find_due_connectors(session, now=NOW)
        assert [d for d in due if d.tenant_id == tenant_id] == []
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_tick_lock_is_held_by_one_transaction_at_a_time():
    """Two Core replicas ticking together must not both schedule.

    Modelled with two concurrent sessions, which is what two replicas are from
    the database's point of view.

    Verifies Fizzbee Invariant: SchedulerSingleFlight
    """
    async with async_session_maker() as first, async_session_maker() as second:
        assert await acquire_tick_lock(first) is True
        # Same key, different transaction: must not be granted.
        assert await acquire_tick_lock(second) is False

        # Releasing the first transaction hands it over.
        await first.rollback()
        assert await acquire_tick_lock(second) is True
        await second.rollback()


@pytest.mark.asyncio
async def test_run_once_enqueues_due_connectors_and_survives_one_failing():
    """A single broken connector must not abort the rest of the tick."""
    tenant_id = await create_test_tenant()
    try:
        await _connector(tenant_id, source_type="oura", config={"poll_interval_hours": 1})
        await _connector(tenant_id, source_type="weather", config={"poll_interval_hours": 1})

        seen: list[str] = []

        async def enqueue(connector: DueConnector) -> None:
            seen.append(connector.source_type)
            # Keyed on this test's tenant as well as the source type. `run_once`
            # scans every tenant, so keying on the source type alone made the
            # arithmetic below depend on no other tenant in the database having an
            # oura connector that happened to be due -- which broke the moment one
            # did (AGENTS.md rule 10: no test may assume the state of the database
            # around it).
            if connector.tenant_id == tenant_id and connector.source_type == "oura":
                raise RuntimeError("simulated importer configuration error")

        enqueued = await run_once(enqueue, now=NOW)

        # Both were attempted; only the healthy one counts as enqueued.
        assert {"oura", "weather"} <= set(seen)
        assert enqueued == len(seen) - 1
    finally:
        await cleanup_test_tenant(tenant_id)


# ── The tick must not hold anything while it acts ────────────────────────────
#
# These pin the shape of a production deadlock that stopped every scheduled import
# for a day and survived a restart. See `run_once` for the full account.


@pytest.mark.asyncio
async def test_the_tick_holds_no_lock_while_enqueueing():
    """Phase 2 runs with the advisory lock already released.

    The direct statement of the invariant: if the tick can still be holding
    `SCHEDULER_LOCK_KEY` when it calls out, then anything that call touches can
    block against it — and the outer transaction is waiting in Python, so Postgres
    sees no cycle and never breaks it.

    Verifies Fizzbee Invariant: SchedulerSingleFlight
    """
    tenant_id = await create_test_tenant()
    try:
        await _connector(tenant_id, source_type="weather", config={"poll_interval_hours": 1})
        lock_free_during_enqueue: list[bool] = []

        async def enqueue(connector: DueConnector) -> None:
            async with async_session_maker() as other:
                lock_free_during_enqueue.append(await acquire_tick_lock(other))
                await other.rollback()

        await run_once(enqueue, now=NOW)

        assert lock_free_during_enqueue, "the connector was never enqueued"
        assert all(lock_free_during_enqueue), (
            "the scheduler lock was still held while enqueueing; a session opened by "
            "the enqueue path can deadlock against the tick that started it"
        )
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_connector_with_a_dead_run_can_still_be_enqueued():
    """The exact production failure, reproduced.

    `expire_stale_runs` writes `data_sources.config` when it retires a dead run, so
    the tick held a row lock on that connector. The real enqueue path opens its own
    session — deliberately — and updates the same row, which blocked; the tick was
    meanwhile waiting for the enqueue to return. Nothing timed out, because neither
    side was waiting on something Postgres could see.

    `lock_timeout` is what turns a regression into a failed assertion instead of a
    suite that hangs until CI kills it.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(
            tenant_id, source_type="weather", config={"poll_interval_hours": 1}
        )
        # Dead long enough for the sweep to retire it, which is what makes the tick
        # write `data_sources.config` before it enqueues anything.
        await _run(
            tenant_id,
            "weather",
            source_id,
            status="loading",
            started_at=NOW - timedelta(hours=12),
        )

        blocked: list[str] = []

        async def enqueue(connector: DueConnector) -> None:
            if connector.source_id != source_id:
                return
            async with async_session_maker() as other:
                await other.execute(text("SET LOCAL lock_timeout = '2s'"))
                try:
                    await other.execute(
                        update(DataSource)
                        .where(DataSource.id == connector.source_id)
                        .values(config={"poll_interval_hours": 1, "touched": True})
                    )
                    await other.commit()
                except SQLAlchemyError as exc:  # pragma: no cover - regression only
                    # Narrow on purpose: a lock timeout arrives as a database error,
                    # and catching everything here would swallow a genuine bug in the
                    # test itself and report it as the regression under study.
                    blocked.append(type(exc).__name__)
                    await other.rollback()

        await asyncio.wait_for(run_once(enqueue, now=NOW), timeout=30)

        assert not blocked, (
            f"the enqueue path could not write `data_sources` ({blocked}); the tick "
            "is still holding a row lock while it calls out"
        )

        # And the dead run was actually retired rather than merely stepped over.
        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(SyncRun.status).where(SyncRun.source_id == source_id)
                )
            ).scalars().all()
        assert row == ["error"], row
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_stale_sweep_does_not_need_the_scheduler_lock():
    """The repair must not share a fate with the thing it repairs.

    Retiring a dead run used to happen only inside the sync tick. When that tick
    wedged on its advisory lock, the repair wedged with it, and a run sat in
    `loading` for twenty-seven hours while the mechanism meant to retire it waited
    behind the failure it would have fixed.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(
            tenant_id, source_type="weather", config={"poll_interval_hours": 1}
        )
        await _run(
            tenant_id,
            "weather",
            source_id,
            status="loading",
            started_at=NOW - timedelta(hours=12),
        )

        # Somebody else holds the sync lock for the whole sweep, exactly as the hung
        # transaction did in production.
        async with async_session_maker() as holder:
            assert await acquire_tick_lock(holder) is True
            retired = await sweep_stale_runs(now=NOW)
            await holder.rollback()

        assert retired >= 1, "the sweep did nothing while the sync lock was held"
        async with async_session_maker() as session:
            statuses = (
                await session.execute(
                    select(SyncRun.status).where(SyncRun.source_id == source_id)
                )
            ).scalars().all()
        assert statuses == ["error"], statuses
    finally:
        await cleanup_test_tenant(tenant_id)
