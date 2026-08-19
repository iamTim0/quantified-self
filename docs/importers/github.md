# GitHub importer

## Purpose

The GitHub importer reads the **authenticated account's own contribution activity** and
turns it into daily time series: commits, lines added and removed, repositories touched,
pull requests opened and merged, reviews submitted and issues opened — plus the standing
figures GitHub keeps about a profile.

It exists so that "what did I build" can sit next to "how did I sleep" in the same day.

## Setting it up

1. Create a **fine-grained personal access token** at
   [github.com/settings/tokens](https://github.com/settings/personal-access-tokens).
2. Grant it read access to the repositories you want counted — including private ones, if
   you want private work to appear.
3. The token needs the **`Contents: read`** and **`Metadata: read`** repository permissions,
   and the **`Followers: read`** account permission if you want `code_followers`.
4. Add the connector in the dashboard and paste the token. It is encrypted at rest with
   Fernet AES-256 and fetched by the importer per run; it is never written to a file, never
   published on the broker, and never logged (rules 8 and 12).

A token that expires or is revoked makes the connector report an error rather than fail
silently — the run is visible in [Background activity](../features/background-jobs.md).

## Why GraphQL

Lines added and removed are the expensive figure. Over REST they need one
`GET /repos/{owner}/{repo}/commits/{sha}` **per commit**, because the list endpoint omits
`stats`. A month of ordinary work is several hundred commits, so one import would spend most
of an hour's 5,000-request budget to learn two numbers per day.

The GraphQL commit history returns `additions` and `deletions` inline, 100 commits per
request, so an import is a handful of calls rather than hundreds.

## Every day gets a point, including the quiet ones

GitHub's contribution calendar reports a count for **every date in the window, zero
included**, and the importer stores those zeros.

That is deliberate. These metrics are `DAILY`, so a missing point is a gap — and the
[gap scan](../features/data-quality.md) would report a hole for every quiet Sunday, forever,
with no re-import able to fill it. A zero is a fact about the day: nothing was committed.

Daily figures are stamped at **midday UTC**, not midnight. A date-only figure at
`T00:00:00Z` renders as 02:00 for a reader in CEST and falls outside the local day entirely
for a reader west of UTC — the same defect the daily story had to work around for food (see
[The daily story](../features/daily-story.md)). Midday is inside the local day for every
offset the platform accepts.

## What is measured, and how

| Metric | Aggregation | Source |
| --- | --- | --- |
| `code_commits` | sum | The contribution calendar, per repository |
| `code_lines_added` / `code_lines_removed` | sum | Commit history across each repository's branches, deduplicated by commit, filtered to your own commits |
| `code_repositories_touched` | **max** | Distinct repositories with a commit that day |
| `code_pull_requests_opened` | sum | `pullRequestContributions` |
| `code_pull_requests_merged` | sum | The same, counted on `mergedAt` |
| `code_reviews_submitted` | sum | `pullRequestReviewContributions` |
| `code_issues_opened` | sum | `issueContributions` |
| `code_contribution_streak` | last | Derived from the calendar |
| `code_followers`, `code_stars_received` | last | The profile, once per run |

Three of those are judgements worth stating:

**`code_repositories_touched` is a `MAX`, not a `SUM`.** It counts *distinct* repositories
in a day, and adding two days' distinct counts answers a question nobody asked — a week of
working in one repository daily would report seven.

**A merged pull request counts on the day it merged**, not the day it was opened. Counting
it on `occurredAt` would put both events on one day and make "merged" indistinguishable
from "opened".

**The calendar decides how many commits a day held; the commit history is only ever
consulted for how many lines they changed.** GitHub attributes a contribution to a day in
the account's own timezone and hands the calendar back already bucketed that way, while
commit timestamps are instants. Letting the second decide the first would move commits
across midnight for anyone not on UTC.

### There is no `code_issues_closed`

The contribution collection reports issues *opened* per day and has no equivalent for
closing one. The closest is a search query, which answers a whole range rather than a day
and cannot distinguish "closed by me" from "assigned to me".

A registered `DAILY` metric that nothing ever writes is worse than an absent one: the gap
scan would report a permanent, unfixable gap for every day of the workspace's history. So
the metric is not in the registry at all.

### Achievements are not imported

GitHub's profile achievements and badges are not exposed by any API — REST or GraphQL. The
only way to obtain them is to parse the profile page's HTML, which breaks on any redesign,
silently, in a place where a silent break is hard to notice.

## Per-repository breakdown

Alongside the account-wide totals, each repository gets its own commit series under the
registered `github_` namespace — `github_octocat_hello_world_commits`, with the original
`owner/name` in `metadata.repository` and that day's line counts alongside it.

Which repositories exist is a property of one person's account, not of the platform, so
these cannot be catalogued and go under a dynamic namespace instead, exactly as Home
Assistant's entities do (rule 15).

**Quiet days are omitted here**, unlike in the account-wide series. Forty repositories times
a year of zeros is half a million rows saying nothing; the `code_*` series is the one that
carries the promise of a value every day, and this is the breakdown beneath it.

Turn it off with the **Per-repository breakdown** checkbox in the connector dialog, which
stores `per_repository: false` in the connector configuration. It is on by default,
because that is what the importer does when the key is absent.

## Windows longer than a year

`contributionsCollection` refuses any span wider than one year, and it refuses it with an
HTTP 200 carrying a GraphQL error — so it read as a *failed import* rather than as a
truncated one. A first import asks for the whole history it has never seen, which made
full backfill impossible: the run ended with `GitHub GraphQL error: The total time spanned
by 'from' and 'to' must not exceed 1 year` and stored nothing.

The importer now splits a longer window into consecutive spans of at most 365 days and
merges the answers. The spans are a microsecond apart, so no contribution falls between two
of them and none is counted twice — a day that straddles a boundary is reported by each span
with only its own share, and the day's total is the sum. Followers and stars are the
exception: they are counts as of now rather than activity inside the window, so the most
recent span's answer wins instead of being added up.

Only this query is bounded. Line counts come from the git history, whose `since`/`until`
have no such ceiling, so they are still read in one pass over the whole window.

The cost is one extra GraphQL call per year of history — a decade of backfill is eleven
calls against an hourly budget of 5,000 points.

## Bounds, and what says so

| Bound | Value | What happens at it |
| --- | --- | --- |
| Repositories read for line counts | 40, busiest first | Beyond it, line counts are **omitted** rather than reported as zero |
| Branches read per repository | 25, default branch first then most recent | Beyond it, the point is marked `partial` |
| Commits read per repository | 500 unique | The point is marked `partial` with `partial_reason: commit_scan_truncated` |
| Streak length | The import window | `bounded_by_window: true` in the metadata |
| Span of one contribution query | 365 days | A longer window is split and the pieces merged |

The first is the one that matters. A repository past the cap still contributes commits — the
calendar counted them — but no lines, and reporting `0` lines for a day that had thousands
is a wrong number where an absent one would have been a visible gap (rule 19).

### Lines are counted across branches, and each commit once

Commit *counts* come from `contributionsCollection`, which sees work on every branch.
Line counts come from reading commit histories, and they used to read only each
repository's **default branch** — so anything developed on a feature branch arrived as
commits with no lines at all. In one workspace a day with 20 commits and 9,187 changed
lines on a `dev` branch reported `0` lines, which is indistinguishable from a day of no
work.

The obvious repair is the wrong one. A commit is reachable from *every* branch that
contains it, so summing branch by branch counts merged work once per branch still
pointing at it. Measured on that same repository: twelve branches, five of them
Dependabot branches carrying the same commits, summed to 710,908 additions for a week
that actually changed 133,295 lines — wrong by more than five times, with nothing
downstream able to notice. The scan therefore deduplicates on the commit `oid`.

The default branch is read first rather than trusted to sort first: branches come back
newest-first, so a quiet `main` beside active feature branches would be the one dropped
by the cap.

**A day with commits never reports zero lines.** If the commit count found work and the
line scan found none of it, the importer is contradicting itself, and the day is left
out and named in the field report instead — a visible gap rather than a false quiet day.
A day with no commits still reports `0`, because that is a real statement about the day.

## Metric names carry no forge

Every catalogued metric is `code_*`, never `github_*`. A commit is a commit whether GitHub,
GitLab or a self-hosted forge reported it, and rule 15 is explicit that a name states what
was measured and never who measured it. The forge travels in `metadata`, and if a second one
ever reports the same day, `resolve_primary_source` settles it — the same machinery that
already settles two watches reporting `steps`. See
[Metrics from several connectors](../features/metric-source-selection.md).

## Rate limits

GitHub's GraphQL budget is 5,000 points per hour. An import of a week costs a few dozen. If
the budget is exhausted the run reports itself **idle** with the reason rather than failing:
it is not something an operator can act on, and the next scheduled run falls inside the
reset window.

## Related

- [Metrics](../metrics.md) — the full registry, including the `developer` category
- [Background activity](../features/background-jobs.md) — where a run's progress and failures appear
- [Data quality](../features/data-quality.md) — what a run found, including fields that arrive and are not stored
