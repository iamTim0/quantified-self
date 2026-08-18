"""Give already-stored workout points the session id a re-import cannot.

A re-import fixes nothing here, and that is by design rather than by accident.
Rule 4 fixes the idempotency key at ``SHA256(tenant, source, metric, timestamp)``
— metadata is not in it — and Core inserts ``ON CONFLICT DO NOTHING``, so a point
that already exists is not touched when it arrives again. Sending the same
workout a second time therefore changes nothing about the row that is already
there.

Switching to ``DO UPDATE SET metadata = …`` would "fix" that and break something
worse: NATS redelivery has no ordering guarantee, so a replayed older event would
overwrite newer metadata, and rule 4's exact-once guarantee would quietly stop
being true. So: a separate, explicit, tenant-scoped command, shaped like
``core.retention`` and ``core.rollup_backfill``. Never at startup, never
automatic (rule 9).

## What it will and will not do

**It only writes an id it can prove a future import would write.**

For a provider-stated session the digest is ``sha256(f"{source_id}|{provider_id}")``
— look at :func:`shared_schemas.sessions.session_metadata`, the start instant is
not in it. So wherever the provider's own identifier survived in the metadata,
the id is reproducible exactly, with no guesswork about timestamps:

| Source          | Identifier in metadata | Origin     |
| --------------- | ---------------------- | ---------- |
| ``streak``      | ``workout_id``         | provider   |
| ``whoop``       | ``whoop_id``           | provider   |
| ``apple_health``| ``workout_id``         | provider   |

**Everything else is reported, not guessed.** A *derived* id hashes the start
instant and the label, and reconstructing those from stored rows means deciding
which of a group's timestamps was the session's start — a guess. Guessing wrong
does not leave the row as it was: it writes an id that the next real import would
*not* match, which turns one workout into two. Untagged is strictly better,
because the read path already groups untagged rows by timestamp and title
(``core.sessions.session_group_key``) and says that it did.

That leaves two known gaps, both reported by name at the end of a run:

* **Apple Health archive imports**, which state no workout id anywhere — Apple's
  export simply has none, so the importer derives one.
* **Apple Health push route fixes**, which carry only ``workout_name``. Nothing
  ties an individual GPS fix back to a session start. This is exactly why the
  detail endpoint resolves a *window* and never depends on the tag.

For a workspace that can simply be re-imported, that is the better route and
``docs/operations.md`` describes it: everything then arrives tagged from the
start and this command has nothing to do.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from shared_schemas.sessions import session_metadata
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.daily_story import session_metric_predicate
from core.db.models import DataPoint
from core.db.session import async_session_maker

#: Where each source keeps the provider's own session identifier. A source absent
#: from this table has no stated id to recover, and its points are reported
#: rather than tagged.
PROVIDER_ID_FIELD: dict[str, str] = {
    "streak": "workout_id",
    "whoop": "whoop_id",
    "apple_health": "workout_id",
}

@dataclass
class BackfillReport:
    """What one run tagged, and what it deliberately left alone."""

    tagged: int = 0
    sessions: int = 0
    #: `(source_type, reason, point_count)` — named, never silently skipped.
    skipped: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def skipped_points(self) -> int:
        return sum(count for _, _, count in self.skipped)




def _untagged():
    return func.coalesce(DataPoint.metadata_.op("?")("session_id"), False).is_(False)


async def _groups(
    session: AsyncSession, tenant_id: str
) -> tuple[dict[tuple[str, str, str], list[datetime]], list[tuple[str, str, int]]]:
    """Untagged points, gathered by the session they belong to.

    Returns the recoverable groups keyed by `(source_type, source_id, provider
    id)`, plus a tally of what could not be keyed and why.
    """
    rows = (
        await session.execute(
            select(
                DataPoint.source_id,
                DataPoint.metadata_.op("->>")("source_type"),
                DataPoint.metadata_,
                DataPoint.timestamp,
            ).where(
                DataPoint.tenant_id == tenant_id,
                session_metric_predicate(),
                _untagged(),
            )
        )
    ).all()

    groups: dict[tuple[str, str, str], list[datetime]] = defaultdict(list)
    unkeyed: dict[tuple[str, str], int] = defaultdict(int)

    for source_id, source_type, metadata, timestamp in rows:
        kind = source_type or ""
        field_name = PROVIDER_ID_FIELD.get(kind)
        if field_name is None:
            unkeyed[(kind or "unknown", "no provider identifier for this source")] += 1
            continue
        provider_id = str((metadata or {}).get(field_name) or "").strip()
        if not provider_id:
            unkeyed[(kind, f"{field_name} absent — the id would have to be derived")] += 1
            continue
        groups[(kind, str(source_id), provider_id)].append(timestamp)

    skipped = [(kind, reason, count) for (kind, reason), count in sorted(unkeyed.items())]
    return groups, skipped


async def backfill_sessions(tenant_id: str, *, dry_run: bool = False) -> BackfillReport:
    """Tag one workspace's recoverable workout points. Tenant-scoped (rule 2)."""
    tenant_id = str(uuid.UUID(tenant_id))
    report = BackfillReport()

    async with async_session_maker() as session:
        groups, report.skipped = await _groups(session, tenant_id)

        for (source_type, source_id, provider_id), timestamps in sorted(groups.items()):
            block = session_metadata(
                source_type=source_type,
                source_id=source_id,
                provider_session_id=provider_id,
                # The earliest point in the group. Not part of the digest for a
                # provider-stated id — see the module docstring — so this is a
                # window anchor for the read path, not an identity claim.
                start=min(timestamps),
            )
            report.sessions += 1
            report.tagged += len(timestamps)

            if dry_run:
                continue

            # `metadata || block` rather than a replacement: everything already on
            # the row is provenance (rule 19) and none of it is ours to drop. The
            # `NOT ? 'session_id'` guard makes a second run a no-op rather than a
            # rewrite, which is what lets this be re-run after a partial failure.
            await session.execute(
                text(
                    """
                    UPDATE data_points
                       SET metadata = metadata || CAST(:block AS jsonb)
                     WHERE tenant_id = CAST(:tenant_id AS uuid)
                       AND source_id = CAST(:source_id AS uuid)
                       AND metadata->>:field = :provider_id
                       AND NOT (metadata ? 'session_id')
                    """
                ),
                {
                    "block": json.dumps(block),
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "field": PROVIDER_ID_FIELD[source_type],
                    "provider_id": provider_id,
                },
            )

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add session ids to stored workout points that predate them."
    )
    parser.add_argument("--tenant-id", required=True, help="Workspace UUID to process")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be tagged without writing anything",
    )
    args = parser.parse_args()

    report = asyncio.run(backfill_sessions(args.tenant_id, dry_run=args.dry_run))
    verb = "would tag" if args.dry_run else "tagged"
    print(
        f"{verb} {report.tagged} point(s) across {report.sessions} session(s) "
        f"for tenant {args.tenant_id}."
    )
    if report.skipped:
        print(
            f"\nLeft untagged ({report.skipped_points} point(s)). These group by "
            "timestamp and title on the workout list instead, which the interface says:"
        )
        for source_type, reason, count in report.skipped:
            print(f"  {source_type}: {count} point(s) — {reason}")


if __name__ == "__main__":
    main()
