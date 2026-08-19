"""Give already-stored workout points the activity type a re-import cannot.

Same shape and the same reason as :mod:`core.session_backfill`: rule 4 fixes the
idempotency key at ``SHA256(tenant, source, metric, timestamp)`` and Core inserts
``ON CONFLICT DO NOTHING``, so re-importing a workout does not touch the row that
is already there. Metadata added by a later importer release reaches new points
only. A separate, explicit, tenant-scoped command is therefore the only way the
history gets it — never at startup, never automatic (rule 9).

## What it writes, and what it refuses to invent

Every workout point already carries the provider's own word for the activity,
under one of two keys nobody agreed on: WHOOP wrote ``activity_name``, Apple
Health ``workout_name``. :func:`shared_schemas.activities.canonical_activity_type`
resolves either into a canonical ``activity_type``, and the wording it resolved
travels with it as ``activity_label`` — so the mapping stays auditable on the row
rather than only in the alias table.

**A connector whose activity is not in the wording is read from the connector.**
Streak's ``workout_title`` is whatever the user typed — ``Push``, ``Leg day`` — so
resolving it would file every lifting session under ``other`` while the importer
files new ones under ``strength_training``. :data:`CONNECTOR_ACTIVITY`
keeps the two paths agreeing; the title still travels, as the label it is.

**Nothing else is guessed.** A point with neither key gets no ``activity_type`` at all:
inventing ``other`` for a row we know nothing about would make "unmapped activity"
and "no activity recorded" look identical, and the second is the one worth seeing
in the report. A label that resolves to ``other`` *is* written, because that is a
real answer about a real value — the alias table did not recognise it — and the
label beside it says exactly what went unrecognised.

Re-running is a no-op: the guard skips any row that already has an
``activity_type``, which also makes this safe to resume after a partial failure.
The counts by resolved type are printed so an unexpected pile of ``other`` is
visible immediately, and each unrecognised label is named — that list is the
worklist for the alias table.

Maps to Fizzbee Invariants:
- TenantIsolation
- NoDuplicateData
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field

from shared_schemas.activities import OTHER, canonical_activity_type
from sqlalchemy import select, text

from core.daily_story import session_metric_predicate
from core.db.models import DataPoint
from core.db.session import async_session_maker

#: Where each importer put the provider's own wording, in the order it is trusted.
#: Both keys stay readable afterwards; this is about recovering a type from them.
LABEL_FIELDS: tuple[str, ...] = ("activity_name", "workout_name", "workout_title")

#: Sources whose activity is a property of the connector rather than of the wording
#: on the row, and which therefore must not be resolved from that wording.
#:
#: Streak is the whole list. Its `workout_title` is whatever the user typed — `Push`,
#: `Leg day`, a split nobody else would recognise — and none of that is an activity
#: name; resolving it would file every stored lifting session under `other` while the
#: importer files every new one under `strength_training`. Two paths, two answers,
#: which is the failure this whole exercise exists to end.
CONNECTOR_ACTIVITY: dict[str, str] = {"streak": "strength_training"}


@dataclass
class ActivityBackfillReport:
    """What one run resolved, and what it deliberately left alone."""

    updated: int = 0
    #: Canonical type → points written, so a surprise is visible without a query.
    by_type: Counter[str] = field(default_factory=Counter)
    #: Labels that resolved to `other`, with their point counts. The worklist for
    #: the alias table: every entry here is a real activity nobody has mapped yet.
    unrecognised: Counter[str] = field(default_factory=Counter)
    #: Points carrying no provider wording at all. Left untouched, never guessed.
    unlabelled: int = 0


def _labelled_activity(metadata: dict | None) -> str | None:
    """The provider's wording for a point, from whichever key holds it."""
    for name in LABEL_FIELDS:
        value = str((metadata or {}).get(name) or "").strip()
        if value:
            return value
    return None


async def backfill_activity_types(
    tenant_id: str, *, dry_run: bool = False
) -> ActivityBackfillReport:
    """Resolve one workspace's stored workout labels. Tenant-scoped (rule 2)."""
    tenant_id = str(uuid.UUID(tenant_id))
    report = ActivityBackfillReport()

    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(DataPoint.id, DataPoint.metadata_).where(
                    DataPoint.tenant_id == tenant_id,
                    session_metric_predicate(),
                    # A row that already has one is left exactly as it is, which is
                    # what makes a second run cost nothing and a resumed run correct.
                    text("NOT (data_points.metadata ? 'activity_type')"),
                )
            )
        ).all()

        for point_id, metadata in rows:
            label = _labelled_activity(metadata)
            source_type = str((metadata or {}).get("source_type") or "")
            connector_activity = CONNECTOR_ACTIVITY.get(source_type)
            if label is None and connector_activity is None:
                report.unlabelled += 1
                continue

            activity_type = (
                connector_activity
                if connector_activity is not None
                else canonical_activity_type(label)
            )
            report.updated += 1
            report.by_type[activity_type] += 1
            if activity_type == OTHER:
                report.unrecognised[label] += 1

            if dry_run:
                continue

            # `metadata || block` rather than a replacement: everything already on
            # the row is provenance (rule 19) and none of it is ours to drop.
            await session.execute(
                text(
                    """
                    UPDATE data_points
                       SET metadata = metadata || CAST(:block AS jsonb)
                     WHERE tenant_id = CAST(:tenant_id AS uuid)
                       AND id = CAST(:point_id AS uuid)
                       AND NOT (metadata ? 'activity_type')
                    """
                ),
                {
                    "block": json.dumps(
                        {"activity_type": activity_type, "activity_label": label}
                        if label
                        else {"activity_type": activity_type}
                    ),
                    "tenant_id": tenant_id,
                    "point_id": str(point_id),
                },
            )

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve stored workout labels into canonical activity types."
    )
    parser.add_argument("--tenant-id", required=True, help="Workspace UUID to process")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be written without writing anything",
    )
    args = parser.parse_args()

    report = asyncio.run(
        backfill_activity_types(args.tenant_id, dry_run=args.dry_run)
    )
    verb = "would resolve" if args.dry_run else "resolved"
    print(f"{verb} {report.updated} point(s) for tenant {args.tenant_id}.")
    for activity_type, count in sorted(report.by_type.items()):
        print(f"  {activity_type}: {count}")
    if report.unrecognised:
        print(
            "\nNo alias matched these, so they resolved to 'other'. Each one is a "
            "line in shared_schemas.activities:"
        )
        for label, count in report.unrecognised.most_common():
            print(f"  {label!r}: {count} point(s)")
    if report.unlabelled:
        print(
            f"\nLeft alone: {report.unlabelled} point(s) carry no activity wording "
            "at all. A type is not invented for a row that never had one."
        )


if __name__ == "__main__":
    main()
