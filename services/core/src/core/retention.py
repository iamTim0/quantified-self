"""Explicit retention maintenance for fine-grained data points.

This module is a deliberately separate operator command. It is not run during Core
startup: deleting health data is an operational decision, while rollups remain the
long-lived query surface. Every statement is scoped to the tenant supplied by the
operator.

Two things a rollup cannot replace, and this command therefore must not delete:

* **A metric whose fine-grained form *is* the measurement.** A day rollup of
  `strength_set_weight` is "the heaviest thing lifted that day", which is not the
  workout; a `location_point` rollup is a count, which is not the route. Those
  metrics declare `raw_retention_days = None` in the registry — see
  `NEVER_PURGED_CATEGORIES` — and this command reports them rather than skipping
  them quietly, because a metric kept forever is a decision somebody should be able
  to see.
* **Anything that is not actually fine-grained.** The filter matches `raw` and
  `second`, and legacy rows that predate the marker. It deliberately does not match
  `minute`, `hour` or `day`.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from shared_schemas.metrics import METRIC_CATALOG
from sqlalchemy import delete, func, or_, select

from core.db.models import DataPoint, MetricIngestPolicy
from core.db.session import async_session_maker

#: Resolutions this command is entitled to delete. `second` is here because
#: `heart_rate` moved to it: without this line its points match neither `raw` nor
#: `NULL`, so `raw_retention_days` would silently stop applying to the
#: highest-volume metric in the platform and nothing would report it.
PURGEABLE_RESOLUTIONS: tuple[str, ...] = ("raw", "second")

#: Used when a metric is neither catalogued nor covered by a tenant policy.
FALLBACK_RETENTION_DAYS = 90


@dataclass(frozen=True)
class PurgeReport:
    """What one run did, and what it deliberately left alone."""

    purged: int = 0
    #: Metrics whose retention is `None`. Named rather than silently skipped: the
    #: difference between "nothing was old enough" and "these are kept forever" is
    #: the whole reason an operator reads the dry run.
    exempt_metrics: tuple[str, ...] = field(default_factory=tuple)


def _raw_point_filter():
    """Match fine-grained points, including legacy rows without a resolution marker."""
    resolution = DataPoint.metadata_.op("->>")("ingest_resolution")
    return or_(resolution.is_(None), resolution.in_(PURGEABLE_RESOLUTIONS))


def _retention_days(metric_type: str, policies: dict[str, MetricIngestPolicy]) -> int | None:
    """Days to keep, or `None` for never.

    A tenant policy wins where one exists — including one that sets `None`, which is
    a workspace saying "keep this indefinitely" and is exactly as deliberate as a
    number.
    """
    if metric_type in policies:
        return policies[metric_type].raw_retention_days
    definition = METRIC_CATALOG.get(metric_type)
    if definition is None:
        return FALLBACK_RETENTION_DAYS
    return definition.raw_retention_days


async def purge_raw_points(tenant_id: str, *, dry_run: bool = False) -> PurgeReport:
    """Delete expired fine-grained points for one tenant and retain all rollups."""
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
        exempt: list[str] = []
        for metric_type in sorted(metric_types):
            retention_days = _retention_days(metric_type, policies)
            if retention_days is None:
                exempt.append(metric_type)
                continue
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
    return PurgeReport(purged=total, exempt_metrics=tuple(exempt))


def main() -> None:
    """Run the explicit tenant-scoped retention command."""
    parser = argparse.ArgumentParser(description="Purge expired raw Core data points")
    parser.add_argument("--tenant-id", required=True, help="Workspace UUID to process")
    parser.add_argument(
        "--dry-run", action="store_true", help="Count eligible points without deleting them"
    )
    args = parser.parse_args()
    report = asyncio.run(purge_raw_points(args.tenant_id, dry_run=args.dry_run))
    action = "would purge" if args.dry_run else "purged"
    print(f"{action} {report.purged} expired raw point(s) for tenant {args.tenant_id}.")
    if report.exempt_metrics:
        print(
            f"{len(report.exempt_metrics)} metric(s) are never purged "
            f"(a rollup is not a substitute for them): {', '.join(report.exempt_metrics)}."
        )


if __name__ == "__main__":
    main()
