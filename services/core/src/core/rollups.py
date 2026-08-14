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
from sqlalchemy import case, func
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
        else ("minute", "hour", "day")
        if ingest_resolution == "minute"
        else ("hour", "day")
        if ingest_resolution == "hour"
        else ("day",)
    )
    for resolution in resolutions:
        bucket = _bucket(timestamp, resolution)
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
            sample_count=1,
            sum_value=float(value),
            min_value=float(value),
            max_value=float(value),
            first_value=float(value),
            last_value=float(value),
            first_timestamp=timestamp,
            last_timestamp=timestamp,
            metadata=point_metadata,
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
                        "derived_by", aggregation.value,
                        "sample_count", current_count,
                        "rollup_resolution", resolution,
                    ),
                    "is_provider_total": False,
                    "updated_at": now,
                },
            )
        await session.execute(statement)
