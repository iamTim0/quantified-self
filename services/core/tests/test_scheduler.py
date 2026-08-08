"""Tests for periodic sync scheduling.

`poll_interval_hours` was stored, shown in the UI, used to size an import window
— and read by nothing that ever started a sync. These pin the behaviour that
makes it mean something, and the two things that go wrong when more than one Core
process exists.

Maps to Fizzbee Invariants:
- NoDuplicateData
- SchedulerSingleFlight
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataSource, SyncRun
from core.db.session import async_session_maker
from core.scheduler import (
    DueConnector,
    acquire_tick_lock,
    find_due_connectors,
    has_in_flight_run,
    is_due,
    poll_interval_hours,
    run_once,
)

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

NOW = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)


# ── Policy: pure, no database ────────────────────────────────────────────────


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


async def _connector(tenant_id: str, *, source_type: str, config: dict) -> str:
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                config=config,
            )
        )
        await session.commit()
    return source_id


async def _run(tenant_id: str, source_type: str, *, status: str, started_at: datetime):
    async with async_session_maker() as session:
        session.add(
            SyncRun(
                tenant_id=tenant_id,
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
        await _connector(tenant_id, source_type="whoop", config={"poll_interval_hours": 1})
        await _run(tenant_id, "whoop", status="running", started_at=NOW - timedelta(minutes=5))

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
        await _connector(tenant_id, source_type="yazio", config={"poll_interval_hours": 1})
        await _run(tenant_id, "yazio", status="running", started_at=NOW - timedelta(hours=12))

        async with async_session_maker() as session:
            assert (
                await has_in_flight_run(session, tenant_id, "yazio", now=NOW)
            ) is False
            due = await find_due_connectors(session, now=NOW)
        assert [d.source_type for d in due if d.tenant_id == tenant_id] == ["yazio"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_finished_run_does_not_block():
    tenant_id = await create_test_tenant()
    try:
        await _connector(tenant_id, source_type="dawarich", config={"poll_interval_hours": 1})
        await _run(tenant_id, "dawarich", status="success", started_at=NOW - timedelta(minutes=1))

        async with async_session_maker() as session:
            assert (
                await has_in_flight_run(session, tenant_id, "dawarich", now=NOW)
            ) is False
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
