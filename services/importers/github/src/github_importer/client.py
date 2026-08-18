"""Reading a GitHub account's own activity.

**GraphQL, not REST, and that is a rate-limit decision rather than a taste one.**
Lines added and removed are the expensive figure: over REST they need
`GET /repos/{owner}/{repo}/commits/{sha}` per commit, because the list endpoint
omits `stats`. A month of ordinary work is several hundred commits, so a single
import would spend most of an hour's 5,000-request budget to learn two numbers per
day. The GraphQL commit history returns `additions` and `deletions` inline, 100
commits per request.

The contribution calendar is the other reason. It reports **every day in the
window, including the days with nothing on them**, which is what lets the importer
emit an honest zero rather than a gap. A day with no commits is a real fact about
that day; a missing point is the gap scan's problem forever.

Nothing here stores a token. The credential arrives per request from Core (rule 8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import httpx

from github_importer.config import settings

logger = logging.getLogger(__name__)

#: Repositories one import will ask for commit statistics from.
#:
#: The contribution collection already orders them by commit count, so this keeps
#: the ones the window actually holds work in. A person with two hundred
#: repositories does not have commits in two hundred of them last week.
MAX_REPOSITORIES = 40

#: Commits read per repository per window. Beyond this the figure is reported as
#: partial rather than silently truncated -- a lines-added total that quietly
#: stopped counting is indistinguishable from a quiet week.
MAX_COMMITS_PER_REPOSITORY = 500

#: One page of the commit history.
COMMIT_PAGE_SIZE = 100

#: Longest span `contributionsCollection` will accept in one query.
#:
#: GitHub answers anything wider with `The total time spanned by 'from' and 'to'
#: must not exceed 1 year` — an HTTP 200 carrying a GraphQL error, so it surfaced
#: as a failed import rather than as a truncated one. A first import asks for the
#: whole history it has never read, which made full backfill impossible. 365 days
#: rather than a calendar year, because a span crossing a leap day is 366.
#:
#: Only this query is bounded. The commit history is limited by git's own
#: `since`/`until`, which have no such ceiling.
MAX_CONTRIBUTION_SPAN = timedelta(days=365)


class GitHubApiError(RuntimeError):
    """The API answered, and the answer was not usable."""


class GitHubUnauthorizedError(GitHubApiError):
    """The token is missing, revoked, or lacks the scope for what was asked."""


class GitHubRateLimitError(GitHubApiError):
    """The account's request budget is spent. Retried on the next scheduled run."""


@dataclass
class RepositoryActivity:
    """One repository's share of the window."""

    name_with_owner: str
    #: `date -> commit count`, as GitHub itself attributes them.
    commits_by_day: dict[str, int] = field(default_factory=dict)
    additions_by_day: dict[str, int] = field(default_factory=dict)
    deletions_by_day: dict[str, int] = field(default_factory=dict)
    #: True when the commit scan hit `MAX_COMMITS_PER_REPOSITORY`, so the line
    #: counts below it are a floor rather than a total.
    commits_truncated: bool = False


@dataclass
class ContributionWindow:
    """Everything one import learned, before any of it becomes a metric."""

    login: str
    #: `date -> count` for every day in the window, zeros included.
    contributions_by_day: dict[str, int] = field(default_factory=dict)
    commits_by_day: dict[str, int] = field(default_factory=dict)
    pull_requests_opened_by_day: dict[str, int] = field(default_factory=dict)
    pull_requests_merged_by_day: dict[str, int] = field(default_factory=dict)
    reviews_by_day: dict[str, int] = field(default_factory=dict)
    issues_opened_by_day: dict[str, int] = field(default_factory=dict)
    repositories: list[RepositoryActivity] = field(default_factory=list)
    followers: int | None = None
    stars_received: int | None = None
    #: Field paths the payload carried and this importer does not store, so the
    #: Data Quality Center can name them (rule 19).
    unmapped_paths: list[str] = field(default_factory=list)


_CONTRIBUTIONS_QUERY = """
query($from: DateTime!, $to: DateTime!) {
  viewer {
    login
    followers { totalCount }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      nodes { stargazerCount }
    }
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner }
        contributions(first: 100) { nodes { occurredAt commitCount } }
      }
      pullRequestContributions(first: 100) {
        nodes { occurredAt pullRequest { merged mergedAt } }
      }
      pullRequestReviewContributions(first: 100) { nodes { occurredAt } }
      issueContributions(first: 100) { nodes { occurredAt } }
    }
  }
}
"""

_COMMIT_HISTORY_QUERY = """
query($owner: String!, $name: String!, $author: ID!, $since: GitTimestamp!,
      $until: GitTimestamp!, $pageSize: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(author: {id: $author}, since: $since, until: $until,
                  first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            nodes { committedDate additions deletions }
          }
        }
      }
    }
  }
}
"""

_VIEWER_ID_QUERY = "query { viewer { id } }"


def _day(stamp: str) -> str:
    """The calendar day an ISO timestamp falls on, in UTC.

    GitHub attributes a contribution to a day in the *account's* configured
    timezone and returns the calendar already bucketed that way; commit timestamps
    come back as instants. Bucketing those in UTC can disagree with the calendar by
    a day at the edges, which is why the calendar is the authority for
    `code_commits` and the commit history is only ever consulted for line counts.
    """
    return stamp[:10]


class GitHubClient:
    """One account's activity, read with one token.

    The token is passed in per call rather than held: this importer is stateless by
    rule 8, and a client that remembered a credential would be one restart away from
    using a revoked one.
    """

    def __init__(self, token: str, *, timeout: float = 30.0) -> None:
        self._token = token
        self._timeout = timeout

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            # Propagated so one request can be followed across the platform and
            # GitHub's own logs (rule 13).
            "X-Request-ID": request_id,
            "User-Agent": settings.SERVICE_NAME,
        }

    async def _graphql(
        self, client: httpx.AsyncClient, query: str, variables: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        response = await client.post(
            settings.GITHUB_GRAPHQL_URL,
            headers=self._headers(request_id),
            json={"query": query, "variables": variables},
        )
        if response.status_code in (401, 403):
            # GitHub answers 403 for both "no permission" and "rate limited", and the
            # two need different handling: one is the operator's problem now, the
            # other resolves itself by the next run.
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining == "0":
                raise GitHubRateLimitError("GitHub rate limit exhausted for this token")
            raise GitHubUnauthorizedError(
                "GitHub rejected the token (check that it grants repo and read:user)"
            )
        if response.status_code >= 400:
            raise GitHubApiError(f"GitHub returned HTTP {response.status_code}")

        body = response.json()
        errors = body.get("errors")
        if errors:
            # A GraphQL error arrives with HTTP 200. Treating that as success is how
            # an import silently stores nothing and reports itself finished.
            first = errors[0].get("message", "unknown error")
            if any(e.get("type") == "RATE_LIMITED" for e in errors):
                raise GitHubRateLimitError(f"GitHub rate limit: {first}")
            raise GitHubApiError(f"GitHub GraphQL error: {first}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise GitHubApiError("GitHub returned no data")
        return data

    async def fetch_window(
        self, *, start: datetime, end: datetime, request_id: str
    ) -> ContributionWindow:
        """Everything the window holds, in as few requests as it can be had."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            slices = split_span(start, end)
            if len(slices) > 1:
                logger.info(
                    "[req_id=%s] Window spans %d days; reading it in %d contribution "
                    "queries of at most a year.",
                    request_id,
                    (end - start).days,
                    len(slices),
                )

            window = ContributionWindow(login="")
            for slice_start, slice_end in slices:
                data = await self._graphql(
                    client,
                    _CONTRIBUTIONS_QUERY,
                    {"from": slice_start.isoformat(), "to": slice_end.isoformat()},
                    request_id,
                )
                _merge_contributions(window, data.get("viewer") or {})

            # Busiest first, so `MAX_REPOSITORIES` below keeps the repositories the
            # window is actually about. Sorted after the merge rather than inside it:
            # a repository quiet in one slice and busy in the next only has its real
            # rank once every slice has been counted.
            window.repositories.sort(key=lambda r: sum(r.commits_by_day.values()), reverse=True)

            if not window.repositories:
                return window

            identity = await self._graphql(client, _VIEWER_ID_QUERY, {}, request_id)
            author_id = ((identity.get("viewer") or {}).get("id")) or ""
            if not author_id:
                # Without it the history query would return *everybody's* commits in
                # those repositories and report a colleague's work as this reader's.
                logger.warning(
                    "[req_id=%s] Could not resolve the viewer's node id; "
                    "skipping line counts rather than counting other people's commits.",
                    request_id,
                )
                window.unmapped_paths.append("repository.commit.additions")
                window.unmapped_paths.append("repository.commit.deletions")
                return window

            for repository in window.repositories[:MAX_REPOSITORIES]:
                await self._fill_commit_stats(
                    client, repository, author_id, start, end, request_id
                )
            if len(window.repositories) > MAX_REPOSITORIES:
                logger.info(
                    "[req_id=%s] %d repositories had commits; line counts read from the "
                    "busiest %d.",
                    request_id,
                    len(window.repositories),
                    MAX_REPOSITORIES,
                )
        return window

    async def _fill_commit_stats(
        self,
        client: httpx.AsyncClient,
        repository: RepositoryActivity,
        author_id: str,
        start: datetime,
        end: datetime,
        request_id: str,
    ) -> None:
        owner, _, name = repository.name_with_owner.partition("/")
        if not owner or not name:
            return

        cursor: str | None = None
        seen = 0
        while seen < MAX_COMMITS_PER_REPOSITORY:
            data = await self._graphql(
                client,
                _COMMIT_HISTORY_QUERY,
                {
                    "owner": owner,
                    "name": name,
                    "author": author_id,
                    "since": start.isoformat(),
                    "until": end.isoformat(),
                    "pageSize": COMMIT_PAGE_SIZE,
                    "cursor": cursor,
                },
                request_id,
            )
            branch = ((data.get("repository") or {}).get("defaultBranchRef")) or {}
            history = ((branch.get("target") or {}).get("history")) or {}
            for node in history.get("nodes") or []:
                committed = node.get("committedDate")
                if not isinstance(committed, str):
                    continue
                day = _day(committed)
                repository.additions_by_day[day] = repository.additions_by_day.get(
                    day, 0
                ) + int(node.get("additions") or 0)
                repository.deletions_by_day[day] = repository.deletions_by_day.get(
                    day, 0
                ) + int(node.get("deletions") or 0)
                seen += 1

            page = history.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return
            cursor = page.get("endCursor")
            if not cursor:
                return
        repository.commits_truncated = True


def _bucket(nodes: Any, key: str = "occurredAt") -> dict[str, int]:
    """Count contribution nodes per calendar day."""
    counts: dict[str, int] = {}
    for node in nodes or []:
        stamp = (node or {}).get(key)
        if isinstance(stamp, str) and stamp:
            counts[_day(stamp)] = counts.get(_day(stamp), 0) + 1
    return counts


def split_span(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """`[start, end]` as consecutive spans of at most `MAX_CONTRIBUTION_SPAN`.

    The spans neither overlap nor leave a gap: each begins a microsecond after the
    previous one ended, and `occurredAt` has second resolution, so no contribution
    falls between two of them and none is counted twice. Overlapping instead would
    double every contribution on the shared day — a wrong number, which rule 19
    ranks below a missing one precisely because nothing distinguishes it from a
    right one.
    """
    if end <= start:
        return [(start, end)]

    spans: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + MAX_CONTRIBUTION_SPAN, end)
        spans.append((cursor, stop))
        cursor = stop + timedelta(microseconds=1)
    return spans


def _merge_day_counts(into: dict[str, int], other: dict[str, int]) -> None:
    """Add one span's per-day counts to the window's.

    Summed rather than overwritten: a day split across two spans is reported by
    each of them with only its own share, and the day's real total is the sum.
    """
    for day, count in other.items():
        into[day] = into.get(day, 0) + count


def _merge_contributions(window: ContributionWindow, viewer: dict[str, Any]) -> None:
    """Fold one span's `viewer` payload into the window being assembled."""
    part = _parse_contributions(viewer)

    if part.login:
        window.login = part.login
    # Point-in-time totals rather than window sums: whoever answered last is
    # current, and adding them across spans would report seven times the followers.
    if part.followers is not None:
        window.followers = part.followers
    if part.stars_received is not None:
        window.stars_received = part.stars_received

    _merge_day_counts(window.contributions_by_day, part.contributions_by_day)
    _merge_day_counts(window.commits_by_day, part.commits_by_day)
    _merge_day_counts(window.pull_requests_opened_by_day, part.pull_requests_opened_by_day)
    _merge_day_counts(window.pull_requests_merged_by_day, part.pull_requests_merged_by_day)
    _merge_day_counts(window.reviews_by_day, part.reviews_by_day)
    _merge_day_counts(window.issues_opened_by_day, part.issues_opened_by_day)

    by_name = {repository.name_with_owner: repository for repository in window.repositories}
    for repository in part.repositories:
        existing = by_name.get(repository.name_with_owner)
        if existing is None:
            window.repositories.append(repository)
            by_name[repository.name_with_owner] = repository
            continue
        _merge_day_counts(existing.commits_by_day, repository.commits_by_day)

    for path in part.unmapped_paths:
        if path not in window.unmapped_paths:
            window.unmapped_paths.append(path)


def _parse_contributions(viewer: dict[str, Any]) -> ContributionWindow:
    collection = viewer.get("contributionsCollection") or {}
    window = ContributionWindow(login=str(viewer.get("login") or ""))

    followers = (viewer.get("followers") or {}).get("totalCount")
    if isinstance(followers, int):
        window.followers = followers

    owned = ((viewer.get("repositories") or {}).get("nodes")) or []
    if owned:
        window.stars_received = sum(int(node.get("stargazerCount") or 0) for node in owned)

    calendar = (collection.get("contributionCalendar") or {}).get("weeks") or []
    for week in calendar:
        for day in (week or {}).get("contributionDays") or []:
            date_value = day.get("date")
            if isinstance(date_value, str) and date_value:
                window.contributions_by_day[date_value] = int(day.get("contributionCount") or 0)

    for entry in collection.get("commitContributionsByRepository") or []:
        name = ((entry or {}).get("repository") or {}).get("nameWithOwner")
        if not isinstance(name, str) or not name:
            continue
        activity = RepositoryActivity(name_with_owner=name)
        for node in ((entry.get("contributions") or {}).get("nodes")) or []:
            stamp = (node or {}).get("occurredAt")
            if not isinstance(stamp, str) or not stamp:
                continue
            count = int(node.get("commitCount") or 0)
            day = _day(stamp)
            activity.commits_by_day[day] = activity.commits_by_day.get(day, 0) + count
            window.commits_by_day[day] = window.commits_by_day.get(day, 0) + count
        window.repositories.append(activity)

    pull_requests = ((collection.get("pullRequestContributions") or {}).get("nodes")) or []
    window.pull_requests_opened_by_day = _bucket(pull_requests)
    merged: dict[str, int] = {}
    for node in pull_requests:
        pull_request = (node or {}).get("pullRequest") or {}
        merged_at = pull_request.get("mergedAt")
        # `mergedAt`, not `occurredAt`: a pull request opened on Monday and merged on
        # Thursday is Thursday's merge. Counting it on Monday would put the two
        # events on one day and make "merged" indistinguishable from "opened".
        if pull_request.get("merged") and isinstance(merged_at, str) and merged_at:
            merged[_day(merged_at)] = merged.get(_day(merged_at), 0) + 1
    window.pull_requests_merged_by_day = merged

    window.reviews_by_day = _bucket(
        ((collection.get("pullRequestReviewContributions") or {}).get("nodes")) or []
    )
    window.issues_opened_by_day = _bucket(
        ((collection.get("issueContributions") or {}).get("nodes")) or []
    )
    return window
