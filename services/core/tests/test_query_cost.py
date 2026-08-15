"""What a request costs: the work it asks the database for, and the wait it creates.

These tests exist because the expensive mistakes in this service have all been
invisible to a correctness test. Every endpoint below returned the right answer
while doing it the wrong way — a scan of the whole history to compensate for
data that was not there, one aggregate per connector over the largest table on a
page that refreshes on a timer. The response was correct, so nothing failed.

**They assert on statements, not on milliseconds.** How long something takes
depends on the machine, the cache and whatever else is running, so a millisecond
budget either flakes or is set so high it never fires. What the endpoint *asks
the database to do* is exactly reproducible, and it is also the thing that
actually changed in every one of those regressions. Two properties are worth
pinning:

- **Cost must not grow with what the reader did not ask for.** A list endpoint
  issuing one query per row is the classic form; it looks fine with two rows in
  a test and melts with fifty in production.
- **Work proven unnecessary must stop happening.** The compatibility scan in the
  metric summary is the case in point (`core.rollup_coverage`).

Wall-clock time is measured too, reported, and held to a ceiling loose enough
that only a catastrophe trips it — that is a smoke alarm, not a benchmark.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from core.db.session import async_session_maker, engine
from core.main import app
from core.rollup_coverage import forget_day_rollup_coverage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

# A response nobody would sit through. High enough that a loaded CI runner never
# trips it, low enough that a restored full-history scan does.
SLOW_REQUEST_MS = 3_000

# Enough rows that a full scan is measurably different from an indexed read, few
# enough that seeding stays under a second.
SEEDED_POINTS = 20_000
SEEDED_DAYS = 400


@dataclass
class Cost:
    """Everything one request asked the database to do."""

    statements: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def against(self, table: str) -> list[str]:
        """Statements that read or write a given table."""
        return [
            statement
            for statement in self.statements
            if f" {table}" in statement.lower() or f"{table} " in statement.lower()
        ]


@contextmanager
def measure() -> Iterator[Cost]:
    """Record the SQL issued while the block runs, and how long it took."""
    cost = Cost()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        # `pool_pre_ping` checks a connection with a trivial statement on checkout.
        # It is not work the endpoint asked for.
        if statement.strip().lower() in {"select 1", "select 1;"}:
            return
        cost.statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    started = time.perf_counter()
    try:
        yield cost
    finally:
        cost.elapsed_ms = (time.perf_counter() - started) * 1000
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)


async def seed_connector(tenant_id: str, display_name: str) -> str:
    """One configured connector, complete enough for the list endpoint to return it."""
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        await session.execute(
            text(
                "INSERT INTO data_sources (id, tenant_id, source_type, display_name, config)"
                " VALUES (:id, :tenant, 'whoop', :name, :config)"
            ),
            {
                "id": source_id,
                "tenant": tenant_id,
                "name": display_name,
                "config": '{"encrypted_token": "x", "masked_token": "****"}',
            },
        )
        await session.commit()
    return source_id


async def seed_covered_history(tenant_id: str, source_id: str) -> None:
    """A workspace of ordinary points, every one of them inside a day rollup.

    Written in bulk rather than through the ingest path on purpose: the point of
    these tests is the shape of the *read*, and a rollup built by `GROUP BY` here
    is indistinguishable from one maintained incrementally.
    """
    async with async_session_maker() as session:
        await session.execute(
            text(
                """
                INSERT INTO data_points
                    (id, tenant_id, source_id, metric_type, timestamp, value,
                     metadata, idempotency_key, created_at)
                SELECT
                    gen_random_uuid(), :tenant, :source, 'steps',
                    now() - (g % :days) * interval '1 day' - (g % 1440) * interval '1 minute',
                    (g % 500)::float, '{}'::json, 'cost-' || g::text, now()
                FROM generate_series(1, :n) AS g
                """
            ),
            {"tenant": tenant_id, "source": source_id, "days": SEEDED_DAYS, "n": SEEDED_POINTS},
        )
        await session.execute(
            text(
                """
                INSERT INTO metric_rollups
                    (id, tenant_id, source_id, metric_type, resolution, bucket_start,
                     value, sample_count, sum_value, min_value, max_value,
                     first_value, last_value, first_timestamp, last_timestamp,
                     is_provider_total, updated_at)
                SELECT
                    gen_random_uuid(), tenant_id, source_id, metric_type, 'day',
                    date_trunc('day', timestamp),
                    sum(value), count(*), sum(value), min(value), max(value),
                    min(value), max(value), min(timestamp), max(timestamp), false, now()
                FROM data_points
                WHERE tenant_id = :tenant
                GROUP BY tenant_id, source_id, metric_type, date_trunc('day', timestamp)
                """
            ),
            {"tenant": tenant_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_connector_list_cost_is_flat_in_the_number_of_connectors():
    """The dashboard refreshes this every ten seconds; its cost must not scale.

    It used to run one `max(created_at)` over `data_points` per connector, so a
    workspace with eight of them paid eight aggregates against the largest table
    in the database, every ten seconds, for every open tab.
    """
    one_connector = await create_test_tenant()
    many_connectors = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        await seed_connector(one_connector, "Only")
        for index in range(6):
            await seed_connector(many_connectors, f"Connector {index}")

        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            with measure() as small:
                first = await ac.get(
                    "/api/v1/data/sources", headers=auth_headers(one_connector)
                )
            with measure() as large:
                second = await ac.get(
                    "/api/v1/data/sources", headers=auth_headers(many_connectors)
                )
    finally:
        await cleanup_test_tenant(one_connector)
        await cleanup_test_tenant(many_connectors)

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first.json()["connectors"]) == 1
    assert len(second.json()["connectors"]) == 6

    # Six times the rows, the same number of queries.
    assert len(large.statements) == len(small.statements), (
        f"{len(small.statements)} statements for one connector, "
        f"{len(large.statements)} for six: cost grows per row"
    )
    assert len(large.against("data_points")) <= 1
    assert large.elapsed_ms < SLOW_REQUEST_MS


@pytest.mark.asyncio
async def test_metric_summary_stops_reading_data_points_once_covered():
    """The summary's compatibility scan runs until it comes back empty, then never.

    Its cost is the size of the workspace rather than the size of the answer, and
    it has no time window to bound it, which made it the most expensive query in
    the platform — and it was on the path of every page load.
    """
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        source_id = await seed_connector(tenant_id, "WHOOP")
        await seed_covered_history(tenant_id, source_id)
        headers = auth_headers(tenant_id)

        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            forget_day_rollup_coverage(tenant_id)
            with measure() as cold:
                first = await ac.get("/api/v1/data/metrics/summary", headers=headers)
            with measure() as warm:
                second = await ac.get("/api/v1/data/metrics/summary", headers=headers)
    finally:
        forget_day_rollup_coverage(tenant_id)
        await cleanup_test_tenant(tenant_id)

    assert first.json()["metrics"] == second.json()["metrics"]

    # Once, to prove there is nothing to compensate for.
    assert len(cold.against("data_points")) == 1
    # Never again.
    assert warm.against("data_points") == []
    assert warm.elapsed_ms < SLOW_REQUEST_MS


@pytest.mark.asyncio
async def test_windowed_chart_query_does_not_read_the_whole_history():
    """A week on screen must not cost a year in the database.

    The day-resolution path answers from rollups and consults raw points only
    where they can still change the answer, so a covered workspace is not read at
    all — and an uncovered one is read within the window the reader asked for.
    """
    tenant_id = await create_test_tenant()
    transport = ASGITransport(app=app)
    try:
        source_id = await seed_connector(tenant_id, "WHOOP")
        await seed_covered_history(tenant_id, source_id)
        headers = auth_headers(tenant_id)

        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            # Establish coverage the way a real session does, through the summary.
            forget_day_rollup_coverage(tenant_id)
            await ac.get("/api/v1/data/metrics/summary", headers=headers)
            with measure() as cost:
                response = await ac.get(
                    "/api/v1/data/metrics",
                    params={"metric_type": "steps", "resolution": "day", "limit": 7},
                    headers=headers,
                )
    finally:
        forget_day_rollup_coverage(tenant_id)
        await cleanup_test_tenant(tenant_id)

    assert response.status_code == 200
    assert len(response.json()["data_points"]) == 7
    assert cost.against("data_points") == []
    assert cost.elapsed_ms < SLOW_REQUEST_MS
