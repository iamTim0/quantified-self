"""Tagging stored workout points with the session id a re-import cannot give them.

The property that matters is not "it writes an id" — it is **that it writes the
same id a real import would**. An id that differs from what the importer produces
turns one workout into two, which is worse than the untagged state it replaced,
because the read path already groups untagged rows by timestamp and title and
says so.

So the central test derives the expected value from `session_metadata` itself,
the same helper every transformer calls, rather than from a literal.

Every test creates its own tenant and cleans up afterwards (rule 10).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataPoint, DataSource
from core.db.session import async_session_maker
from core.session_backfill import PROVIDER_ID_FIELD, backfill_sessions
from shared_schemas.sessions import session_metadata
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

START = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


async def create_test_source(tenant_id: str, source_type: str) -> str:
    """A connector of this type, matching `test_workout_sessions._source`."""
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                # Unique per instance: `(tenant_id, source_type, display_name)`
                # is constrained, and two connectors of one type is exactly what
                # the merge test below needs.
                display_name=f"{source_type}-{source_id[:8]}",
            )
        )
        await session.commit()
    return source_id


async def _point(
    session, *, tenant_id: str, source_id: str, metric: str, at: datetime, metadata: dict
) -> None:
    session.add(
        DataPoint(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source_id,
            metric_type=metric,
            value=1.0,
            timestamp=at,
            idempotency_key=uuid.uuid4().hex,
            metadata_=metadata,
        )
    )


async def _metadata_for(tenant_id: str) -> list[dict]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(DataPoint.metadata_).where(DataPoint.tenant_id == tenant_id)
            )
        ).scalars().all()
    return [row or {} for row in rows]


@pytest.mark.asyncio
async def test_it_reproduces_the_id_a_real_import_would_write():
    """The whole point: not *an* id, but *the* id.

    Derived from `session_metadata` here rather than hardcoded, because that is
    the function every transformer calls — if its digest ever changes, this test
    changes with it and the backfill stays in step.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await create_test_source(tenant_id, "streak")
        async with async_session_maker() as session:
            for index, metric in enumerate(
                ["strength_set_weight", "strength_set_reps", "workout_duration"]
            ):
                await _point(
                    session,
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric=metric,
                    at=START + timedelta(minutes=index),
                    metadata={"source_type": "streak", "workout_id": "streak-abc-123"},
                )
            await session.commit()

        report = await backfill_sessions(tenant_id)
        assert report.tagged == 3
        assert report.sessions == 1

        expected = session_metadata(
            source_type="streak",
            source_id=source_id,
            provider_session_id="streak-abc-123",
            start=START,
        )
        stored = await _metadata_for(tenant_id)
        assert {row["session_id"] for row in stored} == {expected["session_id"]}
        assert all(row["session_origin"] == "provider" for row in stored)
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_two_connectors_of_one_type_do_not_merge():
    """`source_id` is inside the digest, so two phones are two sessions.

    Even when both report the same provider id — which they will, if the same
    account is configured twice.
    """
    tenant_id = await create_test_tenant()
    try:
        first = await create_test_source(tenant_id, "whoop")
        second = await create_test_source(tenant_id, "whoop")
        async with async_session_maker() as session:
            for source_id in (first, second):
                await _point(
                    session,
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric="workout_duration",
                    at=START,
                    metadata={"source_type": "whoop", "whoop_id": "shared-id"},
                )
            await session.commit()

        report = await backfill_sessions(tenant_id)
        assert report.sessions == 2

        ids = {row["session_id"] for row in await _metadata_for(tenant_id)}
        assert len(ids) == 2, "one workout each, not one workout shared"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_it_is_idempotent_and_never_overwrites():
    """A second run is a no-op, and neither run drops existing provenance."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await create_test_source(tenant_id, "streak")
        async with async_session_maker() as session:
            await _point(
                session,
                tenant_id=tenant_id,
                source_id=source_id,
                metric="workout_duration",
                at=START,
                metadata={
                    "source_type": "streak",
                    "workout_id": "w-1",
                    "provider_value": 42.0,
                    "units": "min",
                },
            )
            await session.commit()

        first = await backfill_sessions(tenant_id)
        assert first.tagged == 1

        second = await backfill_sessions(tenant_id)
        assert second.tagged == 0, "already tagged, so nothing left to do"

        stored = (await _metadata_for(tenant_id))[0]
        # Rule 19: none of what was already on the row is ours to drop.
        assert stored["provider_value"] == 42.0
        assert stored["units"] == "min"
        assert stored["workout_id"] == "w-1"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing_and_still_counts():
    tenant_id = await create_test_tenant()
    try:
        source_id = await create_test_source(tenant_id, "streak")
        async with async_session_maker() as session:
            await _point(
                session,
                tenant_id=tenant_id,
                source_id=source_id,
                metric="workout_duration",
                at=START,
                metadata={"source_type": "streak", "workout_id": "w-2"},
            )
            await session.commit()

        report = await backfill_sessions(tenant_id, dry_run=True)
        assert report.tagged == 1
        assert all("session_id" not in row for row in await _metadata_for(tenant_id))
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_what_cannot_be_recovered_is_named_rather_than_guessed():
    """An Apple archive workout states no id, so its session would be derived.

    Deriving it here means guessing which timestamp was the start — and a wrong
    guess writes an id the next real import would not match, splitting one
    workout in two. Leaving it untagged keeps the timestamp-and-title grouping
    the read path already has, so the honest answer is to report it.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await create_test_source(tenant_id, "apple_health")
        async with async_session_maker() as session:
            await _point(
                session,
                tenant_id=tenant_id,
                source_id=source_id,
                metric="workout_duration",
                at=START,
                # No `workout_id`: what an archive import leaves behind.
                metadata={"source_type": "apple_health", "workout_name": "running"},
            )
            await session.commit()

        report = await backfill_sessions(tenant_id)
        assert report.tagged == 0
        assert report.skipped_points == 1
        source_type, reason, count = report.skipped[0]
        assert source_type == "apple_health"
        assert count == 1
        assert "derived" in reason

        assert all("session_id" not in row for row in await _metadata_for(tenant_id))
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_it_is_scoped_to_one_workspace():
    """Rule 2. A backfill that named no tenant is one nobody could reason about."""
    mine = await create_test_tenant()
    theirs = await create_test_tenant()
    try:
        my_source = await create_test_source(mine, "streak")
        their_source = await create_test_source(theirs, "streak")
        async with async_session_maker() as session:
            for tenant_id, source_id in ((mine, my_source), (theirs, their_source)):
                await _point(
                    session,
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric="workout_duration",
                    at=START,
                    metadata={"source_type": "streak", "workout_id": "w-3"},
                )
            await session.commit()

        await backfill_sessions(mine)

        assert all("session_id" in row for row in await _metadata_for(mine))
        assert all("session_id" not in row for row in await _metadata_for(theirs))
    finally:
        await cleanup_test_tenant(mine)
        await cleanup_test_tenant(theirs)


def test_every_session_importer_has_a_recovery_field_or_is_known_absent():
    """A new workout importer should not silently become unrecoverable.

    `PROVIDER_ID_FIELD` is the whole recoverable set. If a fourth source starts
    emitting sessions, this list is where somebody has to decide whether its id
    survives in metadata — the same posture as the structural test in
    `packages/shared-schemas/tests/test_importer_sessions.py`.
    """
    assert set(PROVIDER_ID_FIELD) == {"streak", "whoop", "apple_health"}
