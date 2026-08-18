"""How a window wider than GitHub allows is read, and how the pieces recombine.

Verifies:
- `contributionsCollection` is never asked for more than a year at once, which is
  what made a first (full-history) import fail outright
- The pieces neither overlap nor leave a gap, so no contribution is counted twice
  and none is lost (rule 19: a wrong number is worse than a missing one)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import pairwise

from github_importer.client import (
    MAX_CONTRIBUTION_SPAN,
    ContributionWindow,
    _merge_contributions,
    split_span,
)


def _viewer(
    *, login: str = "octocat", days: dict[str, int], followers: int, stars: int, repository: str
) -> dict:
    """One span's worth of `viewer`, in the shape the GraphQL query returns it."""
    return {
        "login": login,
        "followers": {"totalCount": followers},
        "repositories": {"nodes": [{"stargazerCount": stars}]},
        "contributionsCollection": {
            "contributionCalendar": {
                "weeks": [
                    {
                        "contributionDays": [
                            {"date": day, "contributionCount": count}
                            for day, count in days.items()
                        ]
                    }
                ]
            },
            "commitContributionsByRepository": [
                {
                    "repository": {"nameWithOwner": repository},
                    "contributions": {
                        "nodes": [
                            {"occurredAt": f"{day}T10:00:00Z", "commitCount": count}
                            for day, count in days.items()
                        ]
                    },
                }
            ],
            "pullRequestContributions": {"nodes": []},
            "pullRequestReviewContributions": {"nodes": []},
            "issueContributions": {"nodes": []},
        },
    }


def test_a_short_window_is_one_span() -> None:
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 19, tzinfo=timezone.utc)
    assert split_span(start, end) == [(start, end)]


def test_no_span_exceeds_what_github_accepts() -> None:
    """A full-history import: six and a half years, and GitHub allows one."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 18, 22, 6, tzinfo=timezone.utc)

    spans = split_span(start, end)

    assert len(spans) > 1
    for span_start, span_end in spans:
        assert span_end - span_start <= MAX_CONTRIBUTION_SPAN


def test_spans_cover_the_window_without_overlapping() -> None:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 8, 18, tzinfo=timezone.utc)

    spans = split_span(start, end)

    assert spans[0][0] == start
    assert spans[-1][1] == end
    for (_, earlier_end), (later_start, _) in pairwise(spans):
        # A microsecond apart: no overlap to double-count a contribution, and no
        # gap wide enough to lose one, since `occurredAt` has second resolution.
        assert later_start - earlier_end == timedelta(microseconds=1)


def test_an_empty_window_still_yields_one_span() -> None:
    moment = datetime(2026, 8, 18, tzinfo=timezone.utc)
    assert split_span(moment, moment) == [(moment, moment)]


def test_a_day_split_across_two_spans_keeps_its_whole_count() -> None:
    """Each span reports only its own share of the boundary day; the day is the sum."""
    window = ContributionWindow(login="")

    _merge_contributions(
        window, _viewer(days={"2025-08-19": 3}, followers=10, stars=5, repository="octocat/one")
    )
    _merge_contributions(
        window, _viewer(days={"2025-08-19": 4}, followers=12, stars=7, repository="octocat/one")
    )

    assert window.contributions_by_day["2025-08-19"] == 7
    assert window.commits_by_day["2025-08-19"] == 7
    assert window.repositories[0].commits_by_day["2025-08-19"] == 7


def test_point_in_time_totals_are_the_latest_rather_than_the_sum() -> None:
    """Followers and stars are counts as of now, not activity within the window."""
    window = ContributionWindow(login="")

    _merge_contributions(
        window, _viewer(days={"2025-01-02": 1}, followers=10, stars=5, repository="octocat/one")
    )
    _merge_contributions(
        window, _viewer(days={"2026-01-02": 1}, followers=12, stars=7, repository="octocat/one")
    )

    assert window.followers == 12
    assert window.stars_received == 7
    assert window.login == "octocat"


def test_a_repository_seen_only_in_a_later_span_is_kept() -> None:
    window = ContributionWindow(login="")

    _merge_contributions(
        window, _viewer(days={"2025-01-02": 1}, followers=1, stars=1, repository="octocat/one")
    )
    _merge_contributions(
        window, _viewer(days={"2026-01-02": 2}, followers=1, stars=1, repository="octocat/two")
    )

    assert {r.name_with_owner for r in window.repositories} == {"octocat/one", "octocat/two"}
