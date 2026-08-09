"""The scheduler's real enqueue path, not a stand-in.

test_scheduler.py drives `run_once` with a fake `enqueue`, which verifies the
scheduling policy but would happily pass while the real callback was broken --
and it was: `_enqueue_scheduled_sync` referenced two names main.py never
imported, so every scheduled sync would have raised NameError, been swallowed by
the per-connector try/except, and logged as "failed to enqueue" forever. Ruff
caught it; no test would have.

This exercises the actual callback against the database.

Maps to Fizzbee Invariants:
- NoDuplicateData
- TenantIdAlwaysPresent
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataSource, SyncRun
from core.db.session import async_session_maker
from core.main import _enqueue_scheduled_sync, app
from core.scheduler import DueConnector
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant, create_test_tenant


class _MockNATSClient:
    async def publish(self, _subject: str, _payload: bytes) -> None:
        return None


async def _connector(tenant_id: str, source_type: str) -> str:
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                display_name=source_type,
                config={"poll_interval_hours": 1, "lookback_days": 7},
            )
        )
        await session.commit()
    return source_id


@pytest.mark.asyncio
async def test_scheduled_enqueue_records_a_run_attributed_to_the_scheduler():
    """A scheduled sync produces a SyncRun marked `scheduled`, for the right tenant.

    The trigger field is what lets an operator tell an automatic import from one
    a user asked for when reading the audit log.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id, "oura")

        await _enqueue_scheduled_sync(
            DueConnector(
                tenant_id=tenant_id,
                source_id=source_id,
                source_type="oura",
                poll_interval_hours=1.0,
                last_sync_at=None,
            )
        )

        async with async_session_maker() as session:
            runs = (
                await session.execute(
                    select(SyncRun).where(SyncRun.tenant_id == tenant_id)
                )
            ).scalars().all()

        assert len(runs) == 1
        assert runs[0].trigger == "scheduled"
        assert runs[0].source_type == "oura"
        assert runs[0].tenant_id == tenant_id
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_second_scheduled_enqueue_is_refused_while_the_first_is_in_flight(
    monkeypatch,
):
    """Core, not the importer, is what stops the duplicate.

    Verifies Fizzbee Invariant: NoDuplicateData
    """
    tenant_id = await create_test_tenant()
    try:
        monkeypatch.setattr(app.state, "nats_client", _MockNATSClient(), raising=False)
        source_id = await _connector(tenant_id, "whoop")
        connector = DueConnector(
            tenant_id=tenant_id,
            source_id=source_id,
            source_type="whoop",
            poll_interval_hours=1.0,
            last_sync_at=None,
        )

        await _enqueue_scheduled_sync(connector)
        await _enqueue_scheduled_sync(connector)

        async with async_session_maker() as session:
            runs = (
                await session.execute(
                    select(SyncRun).where(
                        SyncRun.tenant_id == tenant_id, SyncRun.source_type == "whoop"
                    )
                )
            ).scalars().all()

        # The duplicate does not enqueue a task, but its failed request is still
        # recorded so the connector detail page explains what happened.
        assert len(runs) == 2
        assert {run.status for run in runs} == {"queued", "error"}
        assert any(run.message == "The connector already has an import in flight." for run in runs)
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_deleted_connector_is_skipped_without_raising():
    """The connector can be removed between the tick's scan and its enqueue."""
    tenant_id = await create_test_tenant()
    try:
        await _enqueue_scheduled_sync(
            DueConnector(
                tenant_id=tenant_id,
                source_id=str(uuid.uuid4()),  # never existed
                source_type="oura",
                poll_interval_hours=1.0,
                last_sync_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        async with async_session_maker() as session:
            runs = (
                await session.execute(
                    select(SyncRun).where(SyncRun.tenant_id == tenant_id)
                )
            ).scalars().all()
        assert runs == []
    finally:
        await cleanup_test_tenant(tenant_id)
