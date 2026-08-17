"""Turning one contribution window into canonical ingestion events.

**Every day in the window gets a point, including the empty ones.** GitHub's
contribution calendar reports a count for every date, zero included, and that zero
is a fact about the day: nothing was committed. Emitting nothing instead would
leave the gap scan reporting a hole for every quiet Sunday, forever, with no
import able to fill it. The `DAILY` cadence on these metrics is what makes that a
promise rather than a preference.

**The calendar is the authority for how many commits a day held; the commit
history is only ever consulted for how many lines they changed.** GitHub attributes
a contribution to a day in the account's own timezone and hands back the calendar
already bucketed that way, while commit timestamps are instants this importer
buckets in UTC. Letting the second decide the first would move commits across
midnight for anyone not on UTC.

**Standing figures are stamped at the end of the window, once.** Followers, stars
and the current streak are `LAST` metrics — the number today, not a total of the
numbers so far — so writing one per day would fabricate a history the API never
reported.

Per-repository series go under the `github_` namespace (rule 15): which
repositories exist is a property of one account, not of the platform.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from shared_schemas import idempotency_key, provenance
from shared_schemas.field_report import FieldReportCollector
from shared_schemas.metrics import canonical_metric_type

from github_importer.client import (
    MAX_REPOSITORIES,
    ContributionWindow,
    RepositoryActivity,
)

SOURCE_TYPE = "github"

METRIC_COMMITS = canonical_metric_type("code_commits")
METRIC_LINES_ADDED = canonical_metric_type("code_lines_added")
METRIC_LINES_REMOVED = canonical_metric_type("code_lines_removed")
METRIC_REPOSITORIES = canonical_metric_type("code_repositories_touched")
METRIC_PRS_OPENED = canonical_metric_type("code_pull_requests_opened")
METRIC_PRS_MERGED = canonical_metric_type("code_pull_requests_merged")
METRIC_REVIEWS = canonical_metric_type("code_reviews_submitted")
METRIC_ISSUES_OPENED = canonical_metric_type("code_issues_opened")
METRIC_STREAK = canonical_metric_type("code_contribution_streak")
METRIC_FOLLOWERS = canonical_metric_type("code_followers")
METRIC_STARS = canonical_metric_type("code_stars_received")

#: A repository name reduced to something usable as a metric suffix.
#:
#: Lowercase, and everything outside `[a-z0-9_]` collapsed to `_`, because the
#: suffix becomes part of a metric name and a name is not a place for a slash. The
#: original `owner/name` stays in `metadata.repository`, which is what anything
#: displaying it should read.
_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")


def repository_slug(name_with_owner: str) -> str:
    slug = _SLUG_UNSAFE.sub("_", name_with_owner.lower()).strip("_")
    return slug or "unknown"


def _midday(day: str) -> str:
    """The instant a daily figure is stamped at.

    Midday UTC rather than midnight, and this is the one lesson the Yazio importer
    paid for: a date-only figure stamped at `T00:00:00Z` renders as 02:00 for a
    reader in CEST and falls outside the local day entirely for a reader west of
    UTC, so the day's work disappears from that day. Midday is inside the local day
    for every offset the platform accepts (±16 hours) and reads as "that day"
    rather than as a precise moment.
    """
    return f"{day}T12:00:00Z"


def _point(
    *,
    tenant_id: str,
    source_id: str,
    metric_type: str,
    timestamp: str,
    value: float,
    metadata: dict[str, Any],
    idempotency_source_id: str | None = None,
) -> dict[str, Any]:
    key_source = idempotency_source_id or source_id
    point: dict[str, Any] = {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "metric_type": metric_type,
        "timestamp": timestamp,
        "value": value,
        "metadata": {"source_type": SOURCE_TYPE, **metadata},
        "idempotency_key": idempotency_key(tenant_id, key_source, metric_type, timestamp),
        "source_type": SOURCE_TYPE,
    }
    if idempotency_source_id:
        point["idempotency_source_id"] = idempotency_source_id
    return point


def days_in_window(start: datetime, end: datetime) -> list[str]:
    """Every calendar day the window touches, as ISO dates."""
    first = start.astimezone(timezone.utc).date()
    last = end.astimezone(timezone.utc).date()
    return [
        (first + timedelta(days=offset)).isoformat()
        for offset in range((last - first).days + 1)
    ]


def current_streak(contributions_by_day: dict[str, int], *, today: date) -> int:
    """Consecutive days up to today with at least one contribution.

    Counted backwards from today, and **today not contributing does not break it** —
    the day is still in progress, so a streak read at 09:00 would otherwise report
    zero every morning and jump back overnight. It resumes the count at yesterday,
    which is what every tool that shows a streak means by the word.

    Bounded by the window that was fetched: a streak longer than the import window
    reports the window, which is a floor rather than a wrong number, and the
    metadata says so.
    """
    streak = 0
    cursor = today
    if contributions_by_day.get(cursor.isoformat(), 0) <= 0:
        cursor -= timedelta(days=1)
    while contributions_by_day.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _repository_days(repositories: list[RepositoryActivity]) -> dict[str, int]:
    """How many distinct repositories each day saw a commit in."""
    counts: dict[str, set[str]] = {}
    for repository in repositories:
        for day, commits in repository.commits_by_day.items():
            if commits > 0:
                counts.setdefault(day, set()).add(repository.name_with_owner)
    return {day: len(names) for day, names in counts.items()}


def transform_window(
    window: ContributionWindow,
    tenant_id: str,
    source_id: str,
    *,
    start: datetime,
    end: datetime,
    report: FieldReportCollector | None = None,
    per_repository: bool = True,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Every data point one import produces."""
    points: list[dict[str, Any]] = []
    days = days_in_window(start, end)
    if not days:
        return points

    additions: dict[str, int] = {}
    deletions: dict[str, int] = {}
    truncated_repositories = []
    for repository in window.repositories:
        for day, count in repository.additions_by_day.items():
            additions[day] = additions.get(day, 0) + count
        for day, count in repository.deletions_by_day.items():
            deletions[day] = deletions.get(day, 0) + count
        if repository.commits_truncated:
            truncated_repositories.append(repository.name_with_owner)

    repositories_touched = _repository_days(window.repositories)
    # Only for days the commit scan actually covered. A repository beyond
    # `MAX_REPOSITORIES` contributes commits (the calendar counted them) but no
    # lines, and reporting 0 lines for a day that had thousands is a wrong number
    # where an absent one would have been a visible gap.
    line_counts_complete = (
        len(window.repositories) <= MAX_REPOSITORIES and not truncated_repositories
    )

    daily_series: list[tuple[str, dict[str, int], bool]] = [
        (METRIC_COMMITS, window.commits_by_day, True),
        (METRIC_PRS_OPENED, window.pull_requests_opened_by_day, True),
        (METRIC_PRS_MERGED, window.pull_requests_merged_by_day, True),
        (METRIC_REVIEWS, window.reviews_by_day, True),
        (METRIC_ISSUES_OPENED, window.issues_opened_by_day, True),
        (METRIC_REPOSITORIES, repositories_touched, True),
        (METRIC_LINES_ADDED, additions, line_counts_complete),
        (METRIC_LINES_REMOVED, deletions, line_counts_complete),
    ]

    for metric_type, series, emit_zeros in daily_series:
        for day in days:
            value = series.get(day)
            if value is None:
                if not emit_zeros:
                    continue
                value = 0
            metadata: dict[str, Any] = {
                "day": day,
                **provenance(metric_type, value),
                "github_login": window.login,
            }
            if metric_type in (METRIC_LINES_ADDED, METRIC_LINES_REMOVED):
                metadata["derived_from"] = ["repository.commit.additions"]
                metadata["derived_by"] = "sum"
                metadata["sample_count"] = len(window.repositories)
                if truncated_repositories:
                    metadata["partial"] = True
                    metadata["partial_reason"] = "commit_scan_truncated"
            if metric_type == METRIC_REPOSITORIES:
                metadata["derived_from"] = ["commitContributionsByRepository"]
                metadata["derived_by"] = "count"
                metadata["sample_count"] = len(window.repositories)
            points.append(
                _point(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type=metric_type,
                    timestamp=_midday(day),
                    value=float(value),
                    metadata=metadata,
                )
            )
        if report is not None:
            report.mapped(f"contributionsCollection.{metric_type}", 0, metric_type)

    # ── Standing figures, once, at the last day of the window ────────────────
    last_day = days[-1]
    reference = today or datetime.now(timezone.utc).date()
    streak = current_streak(window.contributions_by_day, today=reference)
    points.append(
        _point(
            tenant_id=tenant_id,
            source_id=source_id,
            metric_type=METRIC_STREAK,
            timestamp=_midday(last_day),
            value=float(streak),
            metadata={
                "day": last_day,
                **provenance(METRIC_STREAK, streak),
                "derived_from": ["contributionCalendar.contributionDays"],
                "derived_by": "count",
                "sample_count": len(window.contributions_by_day),
                # A streak that runs to the first day fetched is a floor, not a
                # total: the run may well be longer than the window asked about.
                "bounded_by_window": streak >= len(window.contributions_by_day) > 0,
                "github_login": window.login,
            },
        )
    )

    for metric_type, value in (
        (METRIC_FOLLOWERS, window.followers),
        (METRIC_STARS, window.stars_received),
    ):
        if value is None:
            continue
        points.append(
            _point(
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type=metric_type,
                timestamp=_midday(last_day),
                value=float(value),
                metadata={
                    "day": last_day,
                    **provenance(metric_type, value),
                    "github_login": window.login,
                },
            )
        )

    if per_repository:
        points.extend(
            _repository_points(window, tenant_id, source_id, days=days, report=report)
        )

    if report is not None:
        for path in window.unmapped_paths:
            report.unmapped(path, None)

    return points


def _repository_points(
    window: ContributionWindow,
    tenant_id: str,
    source_id: str,
    *,
    days: list[str],
    report: FieldReportCollector | None,
) -> list[dict[str, Any]]:
    """Per-repository commit counts, under the registered dynamic namespace.

    Zeros are **not** emitted here. A daily series per repository would write one
    point per repository per day whether or not anything happened in it, which for
    forty repositories over a year is half a million rows saying nothing. The
    account-wide `code_*` series is the one that carries the promise of a value
    every day; this is the breakdown beneath it.

    `idempotency_source_id` carries the repository, so two repositories' points for
    one day do not collide on a key that names only the metric and the day.
    """
    points: list[dict[str, Any]] = []
    for repository in window.repositories:
        slug = repository_slug(repository.name_with_owner)
        metric_type = canonical_metric_type(f"github_{slug}_commits")
        for day in days:
            commits = repository.commits_by_day.get(day, 0)
            if commits <= 0:
                continue
            points.append(
                _point(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type=metric_type,
                    timestamp=_midday(day),
                    value=float(commits),
                    metadata={
                        "day": day,
                        **provenance(metric_type, commits),
                        "repository": repository.name_with_owner,
                        "github_login": window.login,
                        "lines_added": repository.additions_by_day.get(day),
                        "lines_removed": repository.deletions_by_day.get(day),
                    },
                    idempotency_source_id=f"{source_id}_{slug}",
                )
            )
        if report is not None:
            report.mapped("commitContributionsByRepository", 0, metric_type)
    return points
