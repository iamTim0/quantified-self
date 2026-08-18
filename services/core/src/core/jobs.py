"""Every long-running thing a workspace has going on, as one list.

The platform already records its work in two tables — `sync_runs` for imports and
`report_runs` for derivations — and until now a reader could only see either by
knowing which page to open. An import was visible on the connectors page, a report
was a line above the chart it fed, and a nightly analysis that failed at 03:00 was
visible nowhere until somebody happened to look at the analysis tab and read a
sentence about a run timeout.

This module is the union of the two, ordered by when they happened. It is a **read
model and nothing else**: no new table, no second lifecycle, no job that exists here
but not in the table it came from. That matters more than the code it saves — a
notification that can disagree with the thing it notifies about is worse than no
notification, because the reader has two sources and no way to tell which is lying.

**Progress is reported where it is known and omitted where it is not.** An import
knows how many points it expected and how many it has processed, so it has a real
fraction. A report is a single derivation with no interior — it is queued, running,
or done — and inventing a percentage for it would be a number that moves for
reasons unrelated to the work. `progress` is `None` there, and the interface shows
a spinner rather than a bar that lies.

Everything is scoped to the tenant the Gateway injected (rule 2), and every piece
of prose a client might want to translate travels as a `code` (rule 17).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import DataSource, ReportRun, SyncRun

#: Jobs one page may return. A workspace with six connectors polling every six
#: hours produces a few dozen runs a day, so this is roughly a week of history —
#: enough to answer "did last night's run work" without paging.
MAX_JOBS = 100

#: The longest history the list will reach back over. A job nobody looked at for a
#: fortnight is not a notification any more, and an unbounded scan of `sync_runs`
#: is the one query here that would grow with a workspace's whole lifetime.
MAX_JOB_AGE = timedelta(days=14)

#: Statuses that mean the job has not settled yet. Shared with the client through
#: the payload rather than duplicated there: it is what decides whether the bell
#: keeps polling, and two definitions of "still running" would drift.
ACTIVE_STATUSES: frozenset[str] = frozenset({"queued", "running"})

#: Statuses that deserve the reader's attention once finished.
FAILED_STATUSES: frozenset[str] = frozenset({"error", "failed"})

JobKind = Literal["import", "report"]


@dataclass(frozen=True)
class Job:
    """One run, in the shape both tables can honestly be flattened into."""

    key: str
    kind: JobKind
    #: `whoop`, `insights`, `gaps` … — an identifier the dashboard renders through
    #: `jobs.subject.<subject>` and falls back to verbatim for one it does not know.
    subject: str
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    #: 0.0–1.0 where the job knows, `None` where the question does not apply.
    progress: float | None
    message_code: str | None
    message_params: dict[str, Any]
    #: The server's own English sentence, for a client that does not know the code.
    message: str | None
    detail: dict[str, Any]

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def failed(self) -> bool:
        return self.status in FAILED_STATUSES


def _import_progress(run: SyncRun) -> float | None:
    """How far an import has got, or `None` when nothing can be claimed.

    `points_expected` is what the importer said it would send, and it is optional:
    a push connector does not know in advance. Without it there is no denominator
    and therefore no fraction — reporting one anyway (say, processed over received)
    produces a bar that sits at 100% from the first event to the last, which reads
    as finished for the entire duration of the run.
    """
    if run.status not in ACTIVE_STATUSES:
        return 1.0 if run.status == "success" else None
    expected = run.points_expected
    if not expected or expected <= 0:
        return None
    return min(1.0, max(0.0, run.points_processed / expected))


def _job_from_sync_run(run: SyncRun, source_names: dict[str, str]) -> Job:
    return Job(
        # Prefixed, because the two tables have independent UUID spaces and a bare
        # id would collide in the client's list keys the day they ever met.
        key=f"import:{run.id}",
        kind="import",
        subject=run.source_type,
        status=run.status,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        progress=_import_progress(run),
        message_code=run.message_code,
        message_params=run.message_params or {},
        message=run.message,
        detail={
            "source_id": run.source_id,
            "source_name": source_names.get(str(run.source_id)) if run.source_id else None,
            "mode": run.mode,
            "points_expected": run.points_expected,
            "points_processed": run.points_processed,
            "points_accepted": run.points_accepted,
            "points_duplicate": run.points_duplicate,
            "points_rejected": run.points_rejected,
            "unsupported_fields": run.unsupported_fields,
            "window_start": run.window_start.isoformat() if run.window_start else None,
            "window_end": run.window_end.isoformat() if run.window_end else None,
        },
    )


def _job_from_report_run(run: ReportRun) -> Job:
    params = run.params or {}
    return Job(
        key=f"report:{run.id}",
        kind="report",
        subject=run.kind,
        status=run.status,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        # Deliberately absent. A derivation has no interior to report on, and a
        # percentage that moves for reasons unrelated to the work is worse than a
        # spinner, which at least claims nothing.
        progress=1.0 if run.status == "success" else None,
        message_code=run.message_code,
        message_params=run.message_params or {},
        message=run.message,
        detail={
            # The window the run was asked for, which is what makes a nightly
            # 365-day analysis distinguishable from the 90-day one behind the tab.
            "days": params.get("days"),
            "metric_type": params.get("metric_type"),
            "source_id": params.get("source_id"),
            "covers_data_through": (
                run.covers_data_through.isoformat() if run.covers_data_through else None
            ),
        },
    )


def _serialise(job: Job) -> dict[str, Any]:
    return {
        "key": job.key,
        "kind": job.kind,
        "subject": job.subject,
        "status": job.status,
        "trigger": job.trigger,
        "started_at": job.started_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "progress": job.progress,
        "active": job.active,
        "failed": job.failed,
        "message_code": job.message_code,
        "message_params": job.message_params,
        "message": job.message,
        "detail": job.detail,
    }


async def list_jobs(
    session: AsyncSession,
    tenant_id: str,
    *,
    limit: int = 50,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Every import and report run this workspace has going on, newest first.

    `since` is what the notification bell passes: the moment the reader last looked.
    Anything that finished after it is unseen, and that count is the badge. It is a
    parameter rather than stored state on purpose — "have I seen this" is a property
    of one person's browser, not of the workspace, and putting it in the database
    would mean two people sharing a workspace clear each other's notifications.
    """
    cutoff = datetime.now(timezone.utc) - MAX_JOB_AGE
    capped = max(1, min(limit, MAX_JOBS))

    sync_runs = (
        await session.execute(
            select(SyncRun)
            .where(SyncRun.tenant_id == tenant_id, SyncRun.started_at >= cutoff)
            .order_by(SyncRun.started_at.desc())
            .limit(capped)
        )
    ).scalars().all()

    report_runs = (
        await session.execute(
            select(ReportRun)
            .where(ReportRun.tenant_id == tenant_id, ReportRun.started_at >= cutoff)
            .order_by(ReportRun.started_at.desc())
            .limit(capped)
        )
    ).scalars().all()

    # Only for the connectors an actual run names, rather than the workspace's whole
    # connector list: a display name is decoration on this page and must not turn a
    # bounded read into one that grows with the number of connectors.
    wanted = {str(run.source_id) for run in sync_runs if run.source_id}
    source_names: dict[str, str] = {}
    if wanted:
        source_names = {
            str(source_id): name
            for source_id, name in (
                await session.execute(
                    select(DataSource.id, DataSource.display_name).where(
                        DataSource.tenant_id == tenant_id, DataSource.id.in_(sorted(wanted))
                    )
                )
            ).all()
        }

    jobs = [
        *(_job_from_sync_run(run, source_names) for run in sync_runs),
        *(_job_from_report_run(run) for run in report_runs),
    ]
    # Each table was read in its own order; the merged list has to be re-sorted, and
    # only then truncated. Truncating first would drop the newer half of whichever
    # table happened to be busier.
    jobs.sort(key=lambda job: job.started_at, reverse=True)
    jobs = jobs[:capped]

    active = [job for job in jobs if job.active]
    # A run that stored nothing counts here exactly like one that stored
    # thousands, and that is the intended reading rather than an oversight.
    #
    # The alternative was considered: skip runs whose `points_accepted` is zero,
    # so a scheduled poll finding an already-covered range does not light the
    # badge. It was rejected because it makes the badge answer a different
    # question than the list it opens. "Nothing arrived" is a fact about the
    # import — the one a reader checks when a connector has gone quiet — and a
    # notification channel that silently drops the uneventful cases teaches the
    # reader that its silence means nothing happened, when it could equally mean
    # nothing was reported.
    #
    # Noise is bounded instead by the poll interval and `MAX_JOB_AGE`: a
    # connector polled every six hours contributes four rows a day, which is a
    # log, not a flood.
    unseen = [
        job
        for job in jobs
        if since is not None and job.finished_at is not None and job.finished_at > since
    ]

    return {
        "jobs": [_serialise(job) for job in jobs],
        "active_count": len(active),
        # What the badge shows. `None` when the caller stated no `since`, which is
        # not the same as zero: a client that has never looked has nothing to
        # compare against, and showing "0 new" there would be a claim.
        "unseen_count": len(unseen) if since is not None else None,
        "failed_unseen_count": len([job for job in unseen if job.failed]),
        # So a client polls while something is happening and stops when it is not,
        # rather than each client inventing its own rule for that.
        "poll_recommended": bool(active),
        "window_days": MAX_JOB_AGE.days,
    }
