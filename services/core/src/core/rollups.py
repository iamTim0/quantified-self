"""Incremental rollup maintenance owned by Core.

Rollups are updated in the same transaction as an accepted data point. A broker
ack therefore never gets ahead of the queryable aggregate. The helper is intentionally
small and SQL-based: one accepted point updates three bounded buckets instead of
requiring a full-history scan.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from shared_schemas.metrics import Aggregation, describe
from sqlalchemy import case, func, literal
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import MetricRollup


def _bucket(timestamp: datetime, resolution: str) -> datetime:
    """Return a UTC bucket boundary for a rollup resolution."""
    value = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if resolution == "minute":
        return value.replace(second=0, microsecond=0)
    if resolution == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


async def update_rollups_for_point(
    session: AsyncSession,
    *,
    tenant_id: str,
    source_id: str,
    metric_type: str,
    timestamp: datetime,
    value: float | None,
    metadata: dict[str, Any] | None,
) -> None:
    """Upsert minute, hour, and day rollups for one accepted numeric point."""
    if value is None:
        return

    try:
        aggregation = describe(metric_type).aggregation
    except ValueError:
        aggregation = Aggregation.AVERAGE

    now = datetime.now(timezone.utc)
    point_metadata = metadata or {}
    derived_from = point_metadata.get("derived_from")
    if not isinstance(derived_from, list) or not all(
        isinstance(field, str) and field for field in derived_from
    ):
        derived_from = [metric_type]
    ingest_resolution = str(point_metadata.get("ingest_resolution") or "raw")
    provider_total = point_metadata.get("provider_total") is True
    # Legacy/raw points only need a day bucket for the summary. Minute imports get
    # the full hierarchy because they are the canonical high-frequency representation.
    # A provider total is a day statement, even when its source timestamp happens to
    # be the first minute of that day; putting it into minute/hour rollups would make
    # a minute query show a daily number as if it were a minute measurement.
    resolutions = (
        ("day",)
        if provider_total
        # `second` joins `minute` here rather than falling through to day-only.
        # A second-resolution metric is the finest thing the platform stores, so
        # if it does not build the minute and hour buckets nothing does, and a
        # chart wider than a day would have no rollup to read.
        else ("minute", "hour", "day")
        if ingest_resolution in ("second", "minute")
        else ("hour", "day")
        if ingest_resolution == "hour"
        else ("day",)
    )

    # What this point actually stands on. A minute bucket carrying the mean of
    # twelve samples is not one reading, and the spread it declares is not the
    # spread of its own average.
    #
    # Without this the rollups were wrong in two ways at once: a day's "maximum
    # heart rate" was the highest minute *average* of that day, and its mean was an
    # unweighted mean of bucket means, so a minute holding one sample counted for
    # as much as a minute holding sixty.
    # `bucket_samples`, not `sample_count`. Only the bucket aggregator writes the
    # first, and only it means "readings this mean averages". `sample_count` is rule
    # 19 provenance that importers also set on figures which are not means — WHOOP's
    # zone shares carry the number of zone fields the payload held — and weighting a
    # rollup by that produces an average nobody can account for.
    stated_count = point_metadata.get("bucket_samples")
    samples = (
        int(stated_count)
        if isinstance(stated_count, (int, float))
        and not isinstance(stated_count, bool)
        and int(stated_count) > 0
        else 1
    )
    stated_min = point_metadata.get("bucket_min")
    stated_max = point_metadata.get("bucket_max")
    bucket_min = (
        float(stated_min)
        if isinstance(stated_min, (int, float)) and not isinstance(stated_min, bool)
        else float(value)
    )
    bucket_max = (
        float(stated_max)
        if isinstance(stated_max, (int, float)) and not isinstance(stated_max, bool)
        else float(value)
    )
    # `sum_value` feeds the weighted mean, so for an averaging metric it has to be
    # the bucket's total rather than its mean. For a summing metric the value
    # already *is* the total, and multiplying it by the sample count would report a
    # day of steps as a day of steps times the number of buckets in it.
    weighted_sum = float(value) * samples if aggregation is Aggregation.AVERAGE else float(value)
    for resolution in resolutions:
        bucket = _bucket(timestamp, resolution)
        rollup_metadata = (
            point_metadata
            if provider_total
            else {
                "derived_from": derived_from,
                "derived_by": aggregation.value,
                "sample_count": samples,
                "rollup_resolution": resolution,
            }
        )
        # Use the table-level insert: ``metadata`` is a reserved SQLAlchemy ORM
        # attribute, while the physical column is intentionally named metadata.
        # The ORM-level insert interprets it as DeclarativeBase.metadata.
        rollup_table = MetricRollup.__table__
        statement = insert(rollup_table).values(
            tenant_id=tenant_id,
            source_id=source_id,
            metric_type=metric_type,
            resolution=resolution,
            bucket_start=bucket,
            value=float(value),
            sample_count=samples,
            sum_value=weighted_sum,
            min_value=bucket_min,
            max_value=bucket_max,
            first_value=float(value),
            last_value=float(value),
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            metadata=rollup_metadata,
            is_provider_total=provider_total,
            updated_at=now,
        )
        excluded = statement.excluded
        current_sum = func.coalesce(rollup_table.c.sum_value, 0.0) + excluded.sum_value
        current_count = rollup_table.c.sample_count + excluded.sample_count
        current_average = current_sum / func.nullif(current_count, 0)
        current_max = func.greatest(rollup_table.c.max_value, excluded.max_value)
        current_min = func.least(rollup_table.c.min_value, excluded.min_value)
        latest_value = case(
            (excluded.last_timestamp >= rollup_table.c.last_timestamp, excluded.last_value),
            else_=rollup_table.c.last_value,
        )
        latest_timestamp = func.greatest(
            rollup_table.c.last_timestamp, excluded.last_timestamp
        )
        first_value = case(
            (excluded.first_timestamp < rollup_table.c.first_timestamp, excluded.first_value),
            else_=rollup_table.c.first_value,
        )
        first_timestamp = func.least(
            rollup_table.c.first_timestamp, excluded.first_timestamp
        )

        if aggregation is Aggregation.SUM:
            aggregate_value = current_sum
        elif aggregation is Aggregation.MAX:
            aggregate_value = current_max
        elif aggregation is Aggregation.LAST:
            aggregate_value = latest_value
        else:
            aggregate_value = current_average

        conflict_columns = [
            "tenant_id",
            "source_id",
            "metric_type",
            "resolution",
            "bucket_start",
        ]
        if provider_total:
            # Provider totals are authoritative. They replace a previously built
            # interval sum, and later interval points must not replace them.
            statement = statement.on_conflict_do_update(
                index_elements=conflict_columns,
                set_={
                    "value": excluded.value,
                    "sample_count": excluded.sample_count,
                    "sum_value": excluded.sum_value,
                    "min_value": excluded.min_value,
                    "max_value": excluded.max_value,
                    "first_value": excluded.first_value,
                    "last_value": excluded.last_value,
                    "first_timestamp": excluded.first_timestamp,
                    "last_timestamp": excluded.last_timestamp,
                    "metadata": excluded["metadata"],
                    "is_provider_total": True,
                    "updated_at": excluded.updated_at,
                },
            )
        else:
            statement = statement.on_conflict_do_update(
                index_elements=conflict_columns,
                # A daily provider statement already represents the whole bucket.
                # Do not add interval samples to it when they arrive afterwards.
                where=rollup_table.c.is_provider_total.is_(False),
                set_={
                    "value": aggregate_value,
                    "sample_count": current_count,
                    "sum_value": current_sum,
                    "min_value": current_min,
                    "max_value": current_max,
                    "first_value": first_value,
                    "last_value": latest_value,
                    "first_timestamp": first_timestamp,
                    "last_timestamp": latest_timestamp,
                    "metadata": func.jsonb_build_object(
                        "derived_from", literal(derived_from, type_=MetricRollup.__table__.c.metadata.type),
                        "derived_by", aggregation.value,
                        "sample_count", current_count,
                        "rollup_resolution", resolution,
                    ),
                    "is_provider_total": False,
                    "updated_at": now,
                },
            )
        await session.execute(statement)
