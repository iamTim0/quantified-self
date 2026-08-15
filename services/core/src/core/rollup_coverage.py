"""Which tenants still hold raw points that no *day* rollup represents.

The compatibility queries in Core all ask the same expensive question: *is this
data point already counted by a rollup?* The test has to be applied to every
point the query considers, and it is at its most expensive exactly when the
answer is always "yes" — a workspace whose data all arrived after rollups
existed scans its entire history to discover that there is nothing to
compensate for.

The metric summary has no time window to bound that with, so it paid it in full
on every call. Postgres answers it with a parallel anti-join over every chunk of
the workspace's data points, which is to say it recruits as many cores as it is
allowed to: measured on a 2,000,000-point workspace, the summary cost 276 ms of
eight-worker scanning to add nothing to an 18 ms rollup aggregate.

**The answer cannot change through ingestion.** Every path that inserts a
`DataPoint` — the NATS consumer, the internal bulk-write endpoint and the
quarantine replay — calls `update_rollups_for_point` for the same point inside
the same transaction, and that always writes a day bucket whatever the point is
(`core.rollups`). Nothing deletes a rollup except the workspace wipe, which
deletes the points as well. A point that no day rollup covers is therefore
*older than rollups*, and no import can create another one.

So the scan is a proof about the past, and a proof about the past is worth
remembering: once a tenant is known to hold no such points, that stays true for
as long as this process is running, and the scan never has to run again.

**Day resolution only, and that qualifier is load-bearing.** `update_rollups_for_point`
writes minute and hour buckets only for points imported at those resolutions,
and never for a provider's daily total — a total is a statement about a day, and
putting it in a minute bucket would show a daily number as a minute measurement.
An ordinary raw point therefore has a day rollup and no other, which means it is
legitimately *uncovered* at minute and hour resolution, and the queries that ask
at those resolutions must go on reading raw points to answer at all. What is
proven here says nothing about them. Consult it only where the resolution being
compensated for is `day`.

Only the "nothing here" direction is remembered, which is the direction that
cannot rot. The opposite — a tenant that *does* hold legacy points — is left to
re-query, because that set shrinks (`core.retention`, `core.rollup_backfill`)
and a remembered aggregate would keep reporting points that are gone. Rule 19:
a wrong number is worse than a missing one. It also means the backfill needs no
cache invalidation of its own: once it has covered the last legacy point, the
next scan comes back empty and stops happening.

State lives in this process only, so a restart re-proves it. That is the answer
to the one thing the invariant above cannot cover — a database restored or
edited outside the service.
"""

from __future__ import annotations

# One UUID string per tenant proven clean. Never holds aggregates or values.
_covered_by_day_rollups: set[str] = set()


def may_hold_points_outside_day_rollups(tenant_id: str) -> bool:
    """Whether a day-resolution compatibility scan could still find anything."""
    return tenant_id not in _covered_by_day_rollups


def remember_day_rollup_coverage(tenant_id: str) -> None:
    """Record that a full-history scan found no point outside a day rollup."""
    _covered_by_day_rollups.add(tenant_id)


def forget_day_rollup_coverage(tenant_id: str | None = None) -> None:
    """Drop what is remembered, for one tenant or all of them.

    Used by tests, and by anything that has reason to believe the stored data
    changed underneath the service.
    """
    if tenant_id is None:
        _covered_by_day_rollups.clear()
    else:
        _covered_by_day_rollups.discard(tenant_id)
