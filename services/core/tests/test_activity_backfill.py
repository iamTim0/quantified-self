"""Resolving stored workout wording into the canonical activity type.

A re-import cannot do this: rule 4 keys a point on `(tenant, source, metric,
timestamp)` and Core inserts `ON CONFLICT DO NOTHING`, so a workout that arrives
again leaves the stored row untouched. Metadata a later importer release adds
reaches new points only, which is why this command exists at all.

The properties that matter are that it resolves the same way the importers do,
that it never invents a type for a row that carried no wording, and that running
it twice is not a rewrite.

Every test creates its own tenant and cleans up afterwards (rule 10).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from core.activity_backfill import backfill_activity_types
from core.db.models import DataPoint, DataSource
from core.db.session import async_session_maker
from shared_schemas.activities import canonical_activity_type
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

START = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)


async def _source(tenant_id: str, source_type: str) -> str:
    async with async_session_maker() as session:
        source_id = str(uuid.uuid4())
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type=source_type,
                display_name=f"{source_type}-{source_id[:8]}",
            )
        )
        await session.commit()
    return source_id


async def _seed_workouts(
    tenant_id: str, source_id: str, rows: list[dict]
) -> None:
    async with async_session_maker() as session:
        for index, metadata in enumerate(rows):
            session.add(
                DataPoint(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type="workout_duration",
                    timestamp=START + timedelta(hours=index),
                    value=float(30 + index),
                    idempotency_key=f"activity-backfill-{uuid.uuid4().hex}",
                    metadata_=metadata,
                )
            )
        await session.commit()


async def _stored(tenant_id: str) -> list[dict]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(DataPoint.metadata_)
                .where(DataPoint.tenant_id == tenant_id)
                .order_by(DataPoint.timestamp)
            )
        ).scalars().all()
    return [row or {} for row in rows]


@pytest.mark.asyncio
async def test_both_provider_keys_resolve_to_one_canonical_type() -> None:
    """WHOOP wrote `activity_name`, Apple Health `workout_name`. One key comes out."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "whoop")
        await _seed_workouts(
            tenant_id,
            source_id,
            [
                {"activity_name": "Laufen"},
                {"workout_name": "Outdoor Ausführen"},
                {"activity_name": "Innenräume Radfahren"},
            ],
        )

        report = await backfill_activity_types(tenant_id)
        stored = await _stored(tenant_id)

        assert report.updated == 3
        assert [row["activity_type"] for row in stored] == [
            "running",
            "running",
            "cycling",
        ]
        # The wording that produced each type stays on the row, so the mapping can
        # be audited later without re-deriving it (rule 19).
        assert [row["activity_label"] for row in stored] == [
            "Laufen",
            "Outdoor Ausführen",
            "Innenräume Radfahren",
        ]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_it_resolves_exactly_as_the_importers_do() -> None:
    """Derived from the shared helper, not from a literal.

    A backfill that resolved differently from the importer would split one activity
    across two keys — the state this whole exercise exists to end.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "whoop")
        wording = ["Gewichtheben", "Paddeltennis", "Spazieren", "Kitesurfen"]
        await _seed_workouts(
            tenant_id, source_id, [{"activity_name": name} for name in wording]
        )

        await backfill_activity_types(tenant_id)
        stored = await _stored(tenant_id)

        assert [row["activity_type"] for row in stored] == [
            canonical_activity_type(name) for name in wording
        ]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_point_with_no_wording_is_reported_not_guessed() -> None:
    """"Unmapped activity" and "no activity recorded" must not become one state."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "whoop")
        await _seed_workouts(
            tenant_id,
            source_id,
            [{"activity_name": "Laufen"}, {"seeded_by": "test"}],
        )

        report = await backfill_activity_types(tenant_id)
        stored = await _stored(tenant_id)

        assert report.updated == 1
        assert report.unlabelled == 1
        assert "activity_type" not in stored[1]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_unrecognised_label_is_named_as_the_worklist() -> None:
    """`other` is a real answer, and the label says what went unrecognised."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "whoop")
        await _seed_workouts(
            tenant_id, source_id, [{"activity_name": "Kitesurfen"}] * 2
        )

        report = await backfill_activity_types(tenant_id)
        stored = await _stored(tenant_id)

        assert report.unrecognised == {"Kitesurfen": 2}
        assert stored[0]["activity_type"] == "other"
        assert stored[0]["activity_label"] == "Kitesurfen"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_dry_run_writes_nothing_and_a_second_run_is_a_no_op() -> None:
    """Re-runnable after a partial failure, and safe to run twice by mistake."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "whoop")
        await _seed_workouts(tenant_id, source_id, [{"activity_name": "Laufen"}])

        dry = await backfill_activity_types(tenant_id, dry_run=True)
        assert dry.updated == 1
        assert "activity_type" not in (await _stored(tenant_id))[0]

        await backfill_activity_types(tenant_id)
        again = await backfill_activity_types(tenant_id)

        assert again.updated == 0, "a row that already has a type is left alone"
        assert (await _stored(tenant_id))[0]["activity_type"] == "running"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_type_already_present_is_never_overwritten() -> None:
    """The importer's own value wins over anything derived here."""
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "apple_health")
        await _seed_workouts(
            tenant_id,
            source_id,
            [{"workout_name": "Aktivität", "activity_type": "padel"}],
        )

        report = await backfill_activity_types(tenant_id)

        assert report.updated == 0
        assert (await _stored(tenant_id))[0]["activity_type"] == "padel"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_streak_title_is_not_mistaken_for_an_activity() -> None:
    """The connector decides, because the title is whatever the user typed.

    Resolving Streak's `workout_title` would file `Push` and `Leg day` under `other`
    while the importer files every new Streak session under
    `strength_training` — the two paths disagreeing about the same workouts, which
    is the exact failure this field was added to end.
    """
    tenant_id = await create_test_tenant()
    try:
        source_id = await _source(tenant_id, "streak")
        titles = ["Push", "Pull", "Leg day"]
        await _seed_workouts(
            tenant_id,
            source_id,
            [
                {"source_type": "streak", "workout_title": title}
                for title in titles
            ],
        )

        report = await backfill_activity_types(tenant_id)
        stored = await _stored(tenant_id)

        assert report.updated == 3
        assert report.unrecognised == {}, "a title is not an unmapped activity"
        assert {row["activity_type"] for row in stored} == {"strength_training"}
        # The title still travels, as the label it is.
        assert [row["activity_label"] for row in stored] == titles
    finally:
        await cleanup_test_tenant(tenant_id)
