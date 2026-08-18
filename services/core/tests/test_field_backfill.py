"""Recovering the history a field missed while it was unsupported.

Recording that a field became supported (026) says the gap exists. It does not
close it: every reading that arrived while nothing knew how to store the field is
still missing, and the platform previously left the user to force an import over
the span by hand.

What these pin is mostly the *refusals*, because a backfill that runs when it
should not is worse than one that does not run. A connector nobody can re-fetch
must not be stamped as recovered; a field that never had a gap must not trigger a
re-import of the whole catalogue; and a run refused because the connector was busy
must leave the fields pending rather than record history that nothing fetched.

Maps to Fizzbee Invariants:
- NoDuplicateData
- TenantIdAlwaysPresent
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataSource, IngestFieldReport, SyncRun
from core.db.session import async_session_maker
from core.field_backfill import (
    MAX_BACKFILL_WINDOW,
    find_pending_backfills,
    mark_backfilled,
    run_once,
)
from core.main import _enqueue_field_backfill, app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

NOW = datetime.now(timezone.utc)


class _MockNATSClient:
    async def publish(self, _subject: str, _payload: bytes) -> None:
        return None


async def _connector(
    tenant_id: str, source_type: str = "whoop", config: dict | None = None
) -> str:
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                display_name=source_type,
                config={"poll_interval_hours": 6, "lookback_days": 7, **(config or {})},
            )
        )
        await session.commit()
    return source_id


async def _field(
    tenant_id: str,
    source_id: str,
    source_type: str,
    path: str,
    *,
    first_seen: datetime,
    supported: datetime | None,
    metric_type: str | None = "steps",
) -> str:
    report_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            IngestFieldReport(
                id=report_id,
                tenant_id=tenant_id,
                source_id=source_id,
                source_type=source_type,
                field_path=path,
                value_kind="number",
                metric_type=metric_type,
                occurrences=7,
                first_seen_at=first_seen,
                last_seen_at=NOW,
                supported_since=supported,
            )
        )
        await session.commit()
    return report_id


@pytest.mark.asyncio
async def test_a_newly_supported_field_becomes_a_pending_backfill_over_its_gap():
    """The window is exactly the span the field arrived in and was not stored."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        first_seen = NOW - timedelta(days=20)
        supported = NOW - timedelta(days=2)
        await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=first_seen, supported=supported,
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)

        mine = [p for p in pending if p.tenant_id == tenant_id]
        assert len(mine) == 1
        assert mine[0].window_start == first_seen
        assert mine[0].window_end == supported
        assert mine[0].field_paths == ("cycle.strain",)
        assert mine[0].truncated is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_field_supported_the_first_time_it_was_seen_has_no_gap():
    """Nothing to recover: it was stored as it arrived.

    This is also every row migration 026 backfilled, which set the two timestamps
    equal. Without the `first_seen_at < supported_since` test the first sweep after
    a deploy would force a re-import of the entire existing catalogue.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        seen = NOW - timedelta(days=5)
        await _field(
            tenant_id, source_id, "whoop", "cycle.kilojoule",
            first_seen=seen, supported=seen,
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)

        assert [p for p in pending if p.tenant_id == tenant_id] == []
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_connector_that_cannot_be_re_imported_is_never_backfilled():
    """A push connector's history is on the device, so there is nothing to fetch.

    It stays unstamped rather than being marked recovered — if the same data ever
    becomes reachable, the gap is still recorded.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id, "apple_health")
        report_id = await _field(
            tenant_id, source_id, "apple_health", "workouts.totalSleep",
            first_seen=NOW - timedelta(days=30), supported=NOW - timedelta(days=1),
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)
            row = await session.get(IngestFieldReport, report_id)

        assert [p for p in pending if p.tenant_id == tenant_id] == []
        assert row.history_backfilled_at is None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_many_fields_on_one_connector_are_one_import_not_many():
    """An importer release maps a dozen paths at once; that is one provider fetch."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        oldest = NOW - timedelta(days=30)
        newest = NOW - timedelta(days=1)
        await _field(tenant_id, source_id, "whoop", "a",
                     first_seen=oldest, supported=NOW - timedelta(days=3))
        await _field(tenant_id, source_id, "whoop", "b",
                     first_seen=NOW - timedelta(days=10), supported=newest)

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)

        mine = [p for p in pending if p.tenant_id == tenant_id]
        assert len(mine) == 1
        # The union of both gaps, not either one of them.
        assert mine[0].window_start == oldest
        assert mine[0].window_end == newest
        assert mine[0].field_paths == ("a", "b")
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_long_gap_is_capped_and_says_so():
    """The cap bounds what is spent of a provider's quota unasked."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        supported = NOW - timedelta(days=1)
        await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=300), supported=supported,
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)

        mine = next(p for p in pending if p.tenant_id == tenant_id)
        assert mine.window_end == supported
        assert mine.window_start == supported - MAX_BACKFILL_WINDOW
        assert mine.truncated is True
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_gap_far_in_the_past_recovers_its_most_recent_window_not_nothing():
    """The cap shortens a long gap; it never turns one into a skip.

    A field supported long ago and never recovered is still worth 90 days of its
    history, and the window is anchored on `supported_since` -- so the span fetched
    is the end of the gap, which is the part that was missing right up to the moment
    storage began.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        supported = NOW - timedelta(days=200)
        await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=400),
            supported=supported,
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)

        mine = next(p for p in pending if p.tenant_id == tenant_id)
        assert mine.window_end == supported
        assert mine.window_start == supported - MAX_BACKFILL_WINDOW
        assert mine.truncated is True
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_refused_enqueue_leaves_the_field_pending():
    """"It did not run" and "it ran and found nothing" must not look the same."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        report_id = await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=20), supported=NOW - timedelta(days=2),
        )

        async def refuse(_pending) -> bool:
            return False

        await run_once(refuse, now=NOW)

        async with async_session_maker() as session:
            row = await session.get(IngestFieldReport, report_id)
            assert row.history_backfilled_at is None

            # And the next sweep still sees it.
            pending = await find_pending_backfills(session, now=NOW)
        assert [p.source_id for p in pending if p.tenant_id == tenant_id] == [source_id]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_stamped_field_is_not_backfilled_twice():
    """The column is what stops a quarter-hourly sweep re-fetching forever."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        report_id = await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=20), supported=NOW - timedelta(days=2),
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)
            mine = next(p for p in pending if p.tenant_id == tenant_id)
            assert await mark_backfilled(session, mine, now=NOW) == 1
            await session.commit()

        async with async_session_maker() as session:
            again = await find_pending_backfills(session, now=NOW)
            row = await session.get(IngestFieldReport, report_id)

        assert [p for p in again if p.tenant_id == tenant_id] == []
        assert row.history_backfilled_at is not None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_real_enqueue_records_a_forced_run_over_the_gap(monkeypatch):
    """The callback, not a stand-in: a fake `enqueue` would pass while it was broken.

    Verifies Fizzbee Invariant: TenantIdAlwaysPresent
    """
    tenant_id = await create_test_tenant()
    try:
        monkeypatch.setattr(app.state, "nats_client", _MockNATSClient(), raising=False)
        source_id = await _connector(tenant_id)
        await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=20), supported=NOW - timedelta(days=2),
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)
        mine = next(p for p in pending if p.tenant_id == tenant_id)

        assert await _enqueue_field_backfill(mine) is True

        async with async_session_maker() as session:
            runs = (
                await session.execute(select(SyncRun).where(SyncRun.tenant_id == tenant_id))
            ).scalars().all()

        assert len(runs) == 1
        run = runs[0]
        assert run.trigger == "field_backfill"
        # Force, because the coverage planner considers the period complete -- it is,
        # for every metric except the ones that were not being stored yet.
        assert run.mode == "force"
        assert run.window_start == mine.window_start
        assert run.window_end == mine.window_end
        # The reason says what it was for. Asserting on the substance, not the
        # sentence: "Period chosen by the user" was what every explicit window used
        # to claim, including the ones no user chose.
        assert "newly supported" in run.window_reason
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_busy_connector_is_not_backfilled_over_its_running_import(monkeypatch):
    """The single-flight guard applies here exactly as it does to a scheduled sync.

    Verifies Fizzbee Invariant: NoDuplicateData
    """
    tenant_id = await create_test_tenant()
    try:
        monkeypatch.setattr(app.state, "nats_client", _MockNATSClient(), raising=False)
        source_id = await _connector(tenant_id)
        await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=20), supported=NOW - timedelta(days=2),
        )

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)
        mine = next(p for p in pending if p.tenant_id == tenant_id)

        assert await _enqueue_field_backfill(mine) is True
        assert await _enqueue_field_backfill(mine) is False
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_quality_view_reports_whether_the_history_was_recovered():
    """A recoverable field with no timestamp is waiting, not stuck."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id)
        report_id = await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=20), supported=NOW - timedelta(days=2),
        )

        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            before = await ac.get(
                "/api/v1/data/quality/newly-supported-fields", headers=auth_headers(tenant_id)
            )
            entry = {f["field_path"]: f for f in before.json()["fields"]}["cycle.strain"]
            # A pull connector, so this one really can be recovered.
            assert entry["history_recoverable"] is True
            assert entry["history_backfilled_at"] is None

            async with async_session_maker() as session:
                row = await session.get(IngestFieldReport, report_id)
                row.history_backfilled_at = NOW
                await session.commit()

            after = await ac.get(
                "/api/v1/data/quality/newly-supported-fields", headers=auth_headers(tenant_id)
            )

        entry = {f["field_path"]: f for f in after.json()["fields"]}["cycle.strain"]
        assert entry["history_backfilled_at"] is not None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_file_import_connector_is_not_offered_a_recovery_it_cannot_do():
    """Its history is in an archive on the user's disk, not at a provider.

    The check used to be "is it a push type", which is a narrower question than
    "can this be re-fetched" -- so a connector fed by an export archive was told
    its history was recoverable and given a button that enqueues nothing.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    try:
        source_id = await _connector(tenant_id, "whoop", config={"import_mode": "file"})
        await _field(
            tenant_id, source_id, "whoop", "cycle.strain",
            first_seen=NOW - timedelta(days=20), supported=NOW - timedelta(days=2),
        )

        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            listed = await ac.get(
                "/api/v1/data/quality/newly-supported-fields", headers=auth_headers(tenant_id)
            )
        entry = {f["field_path"]: f for f in listed.json()["fields"]}["cycle.strain"]
        assert entry["history_recoverable"] is False

        async with async_session_maker() as session:
            pending = await find_pending_backfills(session, now=NOW)
        assert [p for p in pending if p.tenant_id == tenant_id] == []
    finally:
        await cleanup_test_tenant(tenant_id)
