"""Explicit retention maintenance for raw data points.

This module is a deliberately separate operator command. It is not run during Core
startup: deleting health data is an operational decision, while rollups remain the
long-lived query surface. Every statement is scoped to the tenant supplied by the
operator.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from shared_schemas.metrics import METRIC_CATALOG
from sqlalchemy import delete, func, or_, select

from core.db.models import DataPoint, MetricIngestPolicy
from core.db.session import async_session_maker


def _raw_point_filter():
    """Match raw points, including legacy rows without resolution metadata."""
    resolution = DataPoint.metadata_.op("->>")("ingest_resolution")
    return or_(resolution.is_(None), resolution == "raw")


async def purge_raw_points(tenant_id: str, *, dry_run: bool = False) -> int:
    """Delete expired raw points for one tenant and retain all rollups."""
    tenant_id = str(uuid.UUID(tenant_id))
    async with async_session_maker() as session:
        policy_result = await session.execute(
            select(MetricIngestPolicy).where(MetricIngestPolicy.tenant_id == tenant_id)
        )
        policies = {row.metric_type: row for row in policy_result.scalars().all()}
        metric_result = await session.execute(
            select(DataPoint.metric_type)
            .where(DataPoint.tenant_id == tenant_id)
            .distinct()
        )
        metric_types = {row[0] for row in metric_result.all()}

        total = 0
        for metric_type in sorted(metric_types):
            definition = METRIC_CATALOG.get(metric_type)
            retention_days = (
                policies[metric_type].raw_retention_days
                if metric_type in policies
                else definition.raw_retention_days
                if definition is not None
                else 90
            )
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            scope = (
                DataPoint.tenant_id == tenant_id,
                DataPoint.metric_type == metric_type,
                DataPoint.timestamp < cutoff,
                _raw_point_filter(),
            )
            count_result = await session.execute(
                select(func.count(DataPoint.id)).where(*scope)
            )
            count = int(count_result.scalar_one() or 0)
            total += count
            if not dry_run and count:
                await session.execute(delete(DataPoint).where(*scope))

        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return total


def main() -> None:
    """Run the explicit tenant-scoped retention command."""
    parser = argparse.ArgumentParser(description="Purge expired raw Core data points")
    parser.add_argument("--tenant-id", required=True, help="Workspace UUID to process")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count eligible points without deleting them"
    )
    args = parser.parse_args()
    count = asyncio.run(purge_raw_points(args.tenant_id, dry_run=args.dry_run))
    action = "would purge" if args.dry_run else "purged"
    print(f"{action} {count} expired raw point(s) for tenant {args.tenant_id}.")


if __name__ == "__main__":
    main()
