"""What the retention command deletes, and what it must never delete.

A rollup substitutes for a fine-grained point only when the metric is a quantity
over time. For a set of squats and for a GPS fix it is not: a day rollup of
`strength_set_weight` is the heaviest thing lifted that day, and a `location_point`
rollup is a count. Purging those is not keeping the aggregate, it is deleting the
measurement — and unlike a gap, nothing afterwards can tell you it happened.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import DataPoint, DataSource, MetricIngestPolicy
from core.db.session import async_session_maker
from core.retention import PURGEABLE_RESOLUTIONS, purge_raw_points
from sqlalchemy import func, select

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

LONG_AGO = datetime.now(timezone.utc) - timedelta(days=400)


async def _source(tenant_id: str) -> str:
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type="apple_health",
                display_name="apple_health",
            )
        )
        await session.commit()
    return source_id


async def _point(
    tenant_id: str,
    source_id: str,
    metric_type: str,
    *,
    resolution: str | None,
    at: datetime = LONG_AGO,
    metadata: dict | None = None,
) -> None:
    payload = dict(metadata or {})
    if resolution is not None:
        payload["ingest_resolution"] = resolution
    async with async_session_maker() as session:
        session.add(
            DataPoint(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type=metric_type,
                timestamp=at,
                value=1.0,
                metadata_=payload,
                idempotency_key=f"{metric_type}-{uuid.uuid4().hex}",
            )
        )
        await session.commit()


async def _count(tenant_id: str, metric_type: str) -> int:
    async with async_session_maker() as session:
        result = await session.execute(
            select(func.count(DataPoint.id)).where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.metric_type == metric_type,
            )
        )
        return int(result.scalar_one() or 0)


@pytest.mark.asyncio
async def test_a_second_resolution_point_is_purged_like_a_raw_one():
    """The trap the second tier sets.

    The filter used to match only `raw` and rows with no marker. The moment
    `heart_rate` moved to `second`, its points matched neither — so
    `raw_retention_days` would have silently stopped applying to the
    highest-volume metric in the platform, and nothing would have reported it.
    """
    assert "second" in PURGEABLE_RESOLUTIONS

    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "heart_rate", resolution="second")
        assert await _count(tenant_id, "heart_rate") == 1

        report = await purge_raw_points(tenant_id)

        assert report.purged == 1
        assert await _count(tenant_id, "heart_rate") == 0
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_rolled_up_point_is_not_purged():
    """Only fine-grained points expire; a minute bucket is the retained form."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "heart_rate", resolution="minute")

        report = await purge_raw_points(tenant_id)

        assert report.purged == 0
        assert await _count(tenant_id, "heart_rate") == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_gps_coordinates_survive_a_purge():
    """A `location_point` rollup is a count. Purging the fixes loses the route.

    This is the concrete reason `NEVER_PURGED_CATEGORIES` exists: the aggregate
    that survives would go on reporting how many fixes there were, while the
    coordinates they carried were gone.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(
            tenant_id, source_id, "location_point",
            resolution="raw", metadata={"latitude": 52.52, "longitude": 13.40},
        )

        report = await purge_raw_points(tenant_id)

        assert report.purged == 0
        assert await _count(tenant_id, "location_point") == 1
        assert "location_point" in report.exempt_metrics
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_strength_set_survives_a_purge():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "strength_set_weight", resolution="raw")

        report = await purge_raw_points(tenant_id)

        assert await _count(tenant_id, "strength_set_weight") == 1
        assert "strength_set_weight" in report.exempt_metrics
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_dry_run_names_the_metrics_it_exempted():
    """A metric kept forever is a decision, and a decision is stated.

    Without this the dry run's count could not distinguish "nothing was old
    enough" from "these are never deleted at all".
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "location_point", resolution="raw")
        await _point(tenant_id, source_id, "heart_rate", resolution="second")

        report = await purge_raw_points(tenant_id, dry_run=True)

        assert report.purged == 1, "the heart rate point is eligible"
        assert report.exempt_metrics == ("location_point",)
        # A dry run deletes nothing.
        assert await _count(tenant_id, "heart_rate") == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_workspace_may_keep_a_metric_forever():
    """A tenant policy of `null` is as deliberate as a number, and wins."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "heart_rate", resolution="second")
        async with async_session_maker() as session:
            session.add(
                MetricIngestPolicy(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    metric_type="heart_rate",
                    resolution="second",
                    raw_retention_days=None,
                )
            )
            await session.commit()

        report = await purge_raw_points(tenant_id)

        assert report.purged == 0
        assert "heart_rate" in report.exempt_metrics
        assert await _count(tenant_id, "heart_rate") == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_point_inside_its_retention_window_is_kept():
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        recent = datetime.now(timezone.utc) - timedelta(days=2)
        await _point(tenant_id, source_id, "heart_rate", resolution="second", at=recent)

        report = await purge_raw_points(tenant_id)

        assert report.purged == 0
        assert await _count(tenant_id, "heart_rate") == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_purge_never_reaches_another_workspace():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead."""
    keeper = await create_test_tenant()
    purger = await create_test_tenant()
    try:
        keeper_source = await _source(keeper)
        purger_source = await _source(purger)
        await _point(keeper, keeper_source, "heart_rate", resolution="second")
        await _point(purger, purger_source, "heart_rate", resolution="second")

        report = await purge_raw_points(purger)

        assert report.purged == 1
        assert await _count(keeper, "heart_rate") == 1
        assert await _count(purger, "heart_rate") == 0
    finally:
        await cleanup_test_tenant(keeper)
        await cleanup_test_tenant(purger)


# ── Rollups: the weighted mean and the real spread ───────────────────────────


@pytest.mark.asyncio
async def test_a_bucketed_point_weights_the_rollup_by_its_sample_count():
    """A minute holding sixty samples must not count as much as one holding one.

    The rollup's mean was an unweighted mean of bucket means, so a sparse minute
    dragged an hour's average as hard as a dense one.
    """
    from core.db.models import MetricRollup
    from core.rollups import update_rollups_for_point

    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
        async with async_session_maker() as session:
            # A minute of 60 samples averaging 180, then a minute of 1 sample at 60.
            await update_rollups_for_point(
                session, tenant_id=tenant_id, source_id=source_id,
                metric_type="heart_rate", timestamp=at, value=180.0,
                metadata={"ingest_resolution": "minute", "bucket_samples": 60,
                          "bucket_min": 170.0, "bucket_max": 195.0},
            )
            await update_rollups_for_point(
                session, tenant_id=tenant_id, source_id=source_id,
                metric_type="heart_rate", timestamp=at + timedelta(minutes=1), value=60.0,
                metadata={"ingest_resolution": "minute", "bucket_samples": 1,
                          "bucket_min": 60.0, "bucket_max": 60.0},
            )
            await session.commit()

            hour = (
                await session.execute(
                    select(MetricRollup).where(
                        MetricRollup.tenant_id == tenant_id,
                        MetricRollup.metric_type == "heart_rate",
                        MetricRollup.resolution == "hour",
                    )
                )
            ).scalar_one()

        # Weighted: (180*60 + 60*1) / 61 = 178.03, not the unweighted 120.
        assert hour.sample_count == 61
        assert round(hour.value, 2) == 178.03
        # The spread is the samples' spread, not the spread of two averages.
        assert hour.min_value == 60.0
        assert hour.max_value == 195.0
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_summed_metric_is_not_multiplied_by_its_sample_count():
    """`value` for a SUM metric is already the bucket's total.

    Weighting it would report a day of steps as that day times the number of
    buckets in it.
    """
    from core.db.models import MetricRollup
    from core.rollups import update_rollups_for_point

    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
        async with async_session_maker() as session:
            for minute, steps in ((0, 120.0), (1, 80.0)):
                await update_rollups_for_point(
                    session, tenant_id=tenant_id, source_id=source_id,
                    metric_type="steps", timestamp=at + timedelta(minutes=minute),
                    value=steps,
                    metadata={"ingest_resolution": "minute", "bucket_samples": 40},
                )
            await session.commit()

            hour = (
                await session.execute(
                    select(MetricRollup).where(
                        MetricRollup.tenant_id == tenant_id,
                        MetricRollup.metric_type == "steps",
                        MetricRollup.resolution == "hour",
                    )
                )
            ).scalar_one()

        assert hour.value == 200.0, "200 steps, not 200 * 40"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_point_with_no_stated_spread_still_rolls_up():
    """Legacy and raw points carry neither a count nor a spread."""
    from core.db.models import MetricRollup
    from core.rollups import update_rollups_for_point

    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
        async with async_session_maker() as session:
            await update_rollups_for_point(
                session, tenant_id=tenant_id, source_id=source_id,
                metric_type="heart_rate", timestamp=at, value=142.0, metadata={},
            )
            await session.commit()
            day = (
                await session.execute(
                    select(MetricRollup).where(
                        MetricRollup.tenant_id == tenant_id,
                        MetricRollup.resolution == "day",
                    )
                )
            ).scalar_one()

        assert day.sample_count == 1
        assert day.value == 142.0
        assert day.min_value == day.max_value == 142.0
    finally:
        await cleanup_test_tenant(tenant_id)


# ── The policy API must not put an expiry on a never-purged metric ───────────


@pytest.mark.asyncio
async def test_changing_a_resolution_does_not_add_an_expiry():
    """The Explorer's resolution control must not delete GPS routes.

    A request that states no `raw_retention_days` keeps the registry's answer. When
    the field defaulted to 90, changing the *resolution* of `location_point` wrote a
    ninety-day expiry onto it, the next purge deleted every fix, and the dry run
    reported nothing unusual — a policy row of 90 is indistinguishable from a
    workspace that asked for 90.
    """
    from core.main import app
    from httpx import ASGITransport, AsyncClient

    from tests.db_helpers import auth_headers

    app.state.testing = True
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "location_point", resolution="raw",
                     metadata={"latitude": 52.5, "longitude": 13.4})

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            response = await client.put(
                "/api/v1/data/metrics/ingest-policy/location_point",
                json={"resolution": "raw"},
                headers=auth_headers(tenant_id),
            )
        assert response.status_code == 200, response.text
        assert response.json()["raw_retention_days"] is None
        assert response.json()["policy"]["raw_retention_days"] is None

        report = await purge_raw_points(tenant_id)
        assert report.purged == 0
        assert "location_point" in report.exempt_metrics
        assert await _count(tenant_id, "location_point") == 1
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_workspace_can_still_state_a_retention_explicitly():
    """Omitting the field and sending a number are different requests."""
    from core.main import app
    from httpx import ASGITransport, AsyncClient

    from tests.db_helpers import auth_headers

    app.state.testing = True
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        await _point(tenant_id, source_id, "location_point", resolution="raw")

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            response = await client.put(
                "/api/v1/data/metrics/ingest-policy/location_point",
                json={"resolution": "raw", "raw_retention_days": 30},
                headers=auth_headers(tenant_id),
            )
        assert response.status_code == 200
        assert response.json()["raw_retention_days"] == 30

        report = await purge_raw_points(tenant_id)
        assert report.purged == 1, "a stated limit is honoured, even here"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_provenance_sample_count_is_not_used_as_a_weight():
    """Rule 19's `sample_count` is not "readings this mean averages".

    WHOOP's zone shares are `AVERAGE` metrics carrying `sample_count = 6`, the
    number of zone fields the payload held. Weighting a rollup by that produces an
    average weighted by a quantity of nothing.
    """
    from core.db.models import MetricRollup
    from core.rollups import update_rollups_for_point

    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id)
        at = datetime(2026, 8, 15, 10, 0, tzinfo=timezone.utc)
        async with async_session_maker() as session:
            for minute, share, provenance_count in ((0, 30.0, 6), (30, 10.0, 4)):
                await update_rollups_for_point(
                    session, tenant_id=tenant_id, source_id=source_id,
                    metric_type="workout_heart_rate_zone_1",
                    timestamp=at + timedelta(minutes=minute), value=share,
                    metadata={"derived_by": "share", "sample_count": provenance_count},
                )
            await session.commit()

            day = (
                await session.execute(
                    select(MetricRollup).where(
                        MetricRollup.tenant_id == tenant_id,
                        MetricRollup.metric_type == "workout_heart_rate_zone_1",
                        MetricRollup.resolution == "day",
                    )
                )
            ).scalar_one()

        # Unweighted: (30 + 10) / 2. Weighted by the provenance counts it would be
        # (30*6 + 10*4) / 10 = 22, which is an average of nothing.
        assert day.value == 20.0
        assert day.sample_count == 2, "two readings, not ten zone fields"
    finally:
        await cleanup_test_tenant(tenant_id)
