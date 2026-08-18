"""What the GitHub importer writes, and what it refuses to write.

Verifies:
- Every day in the window gets a point, so the gap scan sees no hole for a quiet day
- Canonical metric names and registry units (rule 15)
- Deterministic idempotency keys derived from the canonical name (rule 4)
- Provenance on every point (rule 19)
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from github_importer.client import ContributionWindow, RepositoryActivity
from github_importer.transformer import (
    METRIC_COMMITS,
    METRIC_LINES_ADDED,
    METRIC_LINES_REMOVED,
    METRIC_PRS_MERGED,
    METRIC_REPOSITORIES,
    METRIC_STARS,
    METRIC_STREAK,
    current_streak,
    days_in_window,
    repository_slug,
    transform_window,
)
from shared_schemas.metrics import METRIC_CATALOG, canonical_metric_type, describe

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"
START = datetime(2026, 8, 10, tzinfo=timezone.utc)
END = datetime(2026, 8, 12, tzinfo=timezone.utc)


def _window(**kwargs) -> ContributionWindow:
    window = ContributionWindow(login="octocat")
    for key, value in kwargs.items():
        setattr(window, key, value)
    return window


def _points(window: ContributionWindow, **kwargs) -> list[dict]:
    return transform_window(
        window, TENANT, SOURCE, start=START, end=END, today=date(2026, 8, 12), **kwargs
    )


def test_every_day_in_the_window_gets_a_point_including_the_empty_ones():
    """A quiet Sunday is a fact about that Sunday, not a gap.

    These metrics are `DAILY`, so a missing point is a hole the gap scan reports
    forever and no re-import can fill -- GitHub's calendar reports the zero, so the
    importer stores the zero.
    """
    window = _window(commits_by_day={"2026-08-11": 4})
    commits = [p for p in _points(window) if p["metric_type"] == METRIC_COMMITS]

    assert [p["metadata"]["day"] for p in commits] == [
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
    ]
    assert [p["value"] for p in commits] == [0.0, 4.0, 0.0]


def test_a_daily_figure_is_stamped_at_midday_not_midnight():
    """Midnight UTC leaves the local day for a reader west of UTC.

    The same defect the Yazio importer had: a date-only figure at `T00:00:00Z`
    renders as 02:00 in CEST and falls outside the local day entirely at UTC-5, so
    the day's work vanishes from that day.
    """
    stamps = {p["timestamp"] for p in _points(_window())}
    assert stamps == {
        "2026-08-10T12:00:00Z",
        "2026-08-11T12:00:00Z",
        "2026-08-12T12:00:00Z",
    }


def test_every_metric_is_canonical_and_carries_provenance():
    window = _window(
        commits_by_day={"2026-08-11": 2},
        followers=12,
        stars_received=34,
        repositories=[
            RepositoryActivity(
                name_with_owner="octocat/hello",
                commits_by_day={"2026-08-11": 2},
                additions_by_day={"2026-08-11": 120},
                deletions_by_day={"2026-08-11": 30},
            )
        ],
    )
    for point in _points(window):
        metric = point["metric_type"]
        assert metric == canonical_metric_type(metric), metric
        assert "provider_value" in point["metadata"]
        assert "units" in point["metadata"]
        assert point["metadata"]["source_type"] == "github"
        assert point["tenant_id"] == TENANT


def test_the_idempotency_key_is_deterministic_and_per_repository():
    """Two repositories on one day must not collide on one key."""
    window = _window(
        repositories=[
            RepositoryActivity(name_with_owner="octocat/a", commits_by_day={"2026-08-11": 1}),
            RepositoryActivity(name_with_owner="octocat/b", commits_by_day={"2026-08-11": 1}),
        ]
    )
    first = _points(window)
    second = _points(window)
    assert [p["idempotency_key"] for p in first] == [p["idempotency_key"] for p in second]

    per_repo = [p for p in first if p["metric_type"].startswith("github_")]
    assert len(per_repo) == 2
    assert len({p["idempotency_key"] for p in per_repo}) == 2


def test_per_repository_series_use_the_registered_namespace():
    window = _window(
        repositories=[
            RepositoryActivity(
                name_with_owner="octocat/Hello-World", commits_by_day={"2026-08-11": 3}
            )
        ]
    )
    per_repo = [p for p in _points(window) if p["metric_type"].startswith("github_")]
    assert per_repo, "a repository with commits must produce a namespaced series"
    assert per_repo[0]["metric_type"] == "github_octocat_hello_world_commits"
    assert per_repo[0]["metadata"]["repository"] == "octocat/Hello-World"
    # Resolvable through the registry, which is what makes it legal to write.
    assert canonical_metric_type(per_repo[0]["metric_type"]) == per_repo[0]["metric_type"]


def test_per_repository_series_omit_the_quiet_days():
    """The account-wide series carries the daily promise; this is the breakdown.

    Forty repositories times a year of zeros is half a million rows saying nothing.
    """
    window = _window(
        repositories=[
            RepositoryActivity(name_with_owner="octocat/a", commits_by_day={"2026-08-11": 1})
        ]
    )
    per_repo = [p for p in _points(window) if p["metric_type"].startswith("github_")]
    assert len(per_repo) == 1


def test_line_counts_are_marked_as_derived():
    """And each names the field it actually summed.

    Asserting only that `derived_from` is non-empty is what let both metrics claim
    `additions` for a release: a removed-lines figure that cites the additions field
    cannot be audited against the provider, which is the whole purpose of recording
    provenance (rule 19).
    """
    window = _window(
        repositories=[
            RepositoryActivity(
                name_with_owner="octocat/a",
                commits_by_day={"2026-08-11": 1},
                additions_by_day={"2026-08-11": 200},
                deletions_by_day={"2026-08-11": 75},
            )
        ]
    )
    added = [p for p in _points(window) if p["metric_type"] == METRIC_LINES_ADDED]
    day = next(p for p in added if p["metadata"]["day"] == "2026-08-11")
    assert day["value"] == 200.0
    assert day["metadata"]["derived_by"] == "sum"
    assert day["metadata"]["derived_from"] == ["repository.commit.additions"]

    removed = [p for p in _points(window) if p["metric_type"] == METRIC_LINES_REMOVED]
    removed_day = next(p for p in removed if p["metadata"]["day"] == "2026-08-11")
    assert removed_day["value"] == 75.0
    assert removed_day["metadata"]["derived_by"] == "sum"
    assert removed_day["metadata"]["derived_from"] == ["repository.commit.deletions"]


def test_a_truncated_commit_scan_says_the_line_count_is_partial():
    """A total that quietly stopped counting is indistinguishable from a quiet week."""
    window = _window(
        repositories=[
            RepositoryActivity(
                name_with_owner="octocat/a",
                commits_by_day={"2026-08-11": 900},
                additions_by_day={"2026-08-11": 5000},
                commits_truncated=True,
            )
        ]
    )
    added = [p for p in _points(window) if p["metric_type"] == METRIC_LINES_ADDED]
    # Nothing is claimed for the days the scan did not reach.
    assert all(p["metadata"].get("partial") for p in added)


def test_repositories_touched_counts_distinct_repositories():
    window = _window(
        repositories=[
            RepositoryActivity(name_with_owner="octocat/a", commits_by_day={"2026-08-11": 5}),
            RepositoryActivity(name_with_owner="octocat/b", commits_by_day={"2026-08-11": 1}),
            RepositoryActivity(name_with_owner="octocat/c", commits_by_day={"2026-08-10": 1}),
        ]
    )
    touched = {
        p["metadata"]["day"]: p["value"]
        for p in _points(window)
        if p["metric_type"] == METRIC_REPOSITORIES
    }
    assert touched["2026-08-11"] == 2.0
    assert touched["2026-08-10"] == 1.0
    assert touched["2026-08-12"] == 0.0


def test_repositories_touched_is_not_a_sum_in_the_registry():
    """Adding two days' distinct counts answers a question nobody asked."""
    assert describe(METRIC_REPOSITORIES).aggregation.value == "max"


def test_a_merged_pull_request_counts_on_the_day_it_merged():
    """Opened Monday, merged Thursday is Thursday's merge.

    Counting it on `occurredAt` would put both events on one day and make "merged"
    indistinguishable from "opened".
    """
    window = _window(
        pull_requests_opened_by_day={"2026-08-10": 1},
        pull_requests_merged_by_day={"2026-08-12": 1},
    )
    merged = {
        p["metadata"]["day"]: p["value"]
        for p in _points(window)
        if p["metric_type"] == METRIC_PRS_MERGED
    }
    assert merged["2026-08-12"] == 1.0
    assert merged["2026-08-10"] == 0.0


def test_standing_figures_are_written_once_not_once_per_day():
    """Followers and stars are `LAST`: the number today, not a history invented."""
    window = _window(followers=7, stars_received=90)
    stars = [p for p in _points(window) if p["metric_type"] == METRIC_STARS]
    assert len(stars) == 1
    assert stars[0]["metadata"]["day"] == "2026-08-12"
    assert stars[0]["value"] == 90.0


def test_an_absent_standing_figure_is_omitted_rather_than_zeroed():
    """`followers: None` means GitHub did not say, which is not the same as none."""
    window = _window(followers=None)
    assert not [p for p in _points(window) if p["metric_type"] == "code_followers"]


@pytest.mark.parametrize(
    ("calendar", "expected"),
    [
        # Today has nothing yet, but yesterday and the day before do: the day is
        # still in progress, so it must not read as a broken streak.
        ({"2026-08-12": 0, "2026-08-11": 1, "2026-08-10": 1}, 2),
        ({"2026-08-12": 3, "2026-08-11": 1, "2026-08-10": 0}, 2),
        ({"2026-08-12": 0, "2026-08-11": 0}, 0),
        ({}, 0),
    ],
)
def test_a_streak_survives_a_day_still_in_progress(calendar, expected):
    assert current_streak(calendar, today=date(2026, 8, 12)) == expected


def test_the_streak_says_when_it_is_bounded_by_the_window():
    """A run longer than the window is a floor, and the metadata has to admit it."""
    window = _window(contributions_by_day={"2026-08-10": 1, "2026-08-11": 1, "2026-08-12": 1})
    streak = next(p for p in _points(window) if p["metric_type"] == METRIC_STREAK)
    assert streak["value"] == 3.0
    assert streak["metadata"]["bounded_by_window"] is True


def test_days_in_window_is_inclusive_of_both_ends():
    assert days_in_window(START, END) == ["2026-08-10", "2026-08-11", "2026-08-12"]


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("octocat/Hello-World", "octocat_hello_world"),
        ("Org.Name/repo.js", "org_name_repo_js"),
        ("///", "unknown"),
    ],
)
def test_a_repository_slug_is_safe_to_put_in_a_metric_name(name, slug):
    assert repository_slug(name) == slug


def test_every_catalogued_metric_this_importer_emits_declares_github_as_a_source():
    """`metrics_for_source` is what the dashboard uses to say what to expect."""
    window = _window(
        commits_by_day={"2026-08-11": 1},
        followers=1,
        stars_received=1,
        repositories=[
            RepositoryActivity(name_with_owner="octocat/a", commits_by_day={"2026-08-11": 1})
        ],
    )
    for point in _points(window):
        definition = METRIC_CATALOG.get(point["metric_type"])
        if definition is None:
            continue  # namespaced, and therefore not catalogued by construction
        assert "github" in definition.sources, point["metric_type"]
