"""Am I getting stronger — arithmetic over sets, with no I/O.

The grouping key here is an exercise name, which lives in JSONB. Core reads it and
hands over rows through `QueryStrengthSets`; everything under test is pure.
"""

from datetime import datetime, timedelta, timezone

import pytest
from analysis.core_client import StrengthSet
from analysis.insights import (
    MIN_SESSIONS_FOR_PROGRESSION,
    estimated_one_rep_max,
    exercise_progression,
    muscle_group_volume,
    strength_progression,
)

BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _set(week, exercise, group, weight, reps, number=1):
    return StrengthSet(
        at=BASE + timedelta(weeks=week),
        session_id=f"streak:{exercise}-{week}",
        source_id="src",
        exercise_title=exercise,
        muscle_group=group,
        weight_kg=weight or 0.0,
        reps=float(reps),
        volume_kg=(weight or 0.0) * reps,
        set_number=number,
        has_weight=weight is not None,
    )


# ── Epley ────────────────────────────────────────────────────────────────────


def test_one_rep_max_is_epley():
    assert estimated_one_rep_max(100.0, 5) == pytest.approx(116.667, abs=0.01)


def test_a_single_repetition_is_its_own_answer():
    assert estimated_one_rep_max(140.0, 1) == 140.0


def test_the_estimate_is_refused_where_the_formula_drifts():
    """Above ten reps Epley reads high, so it is not computed at all.

    A number that is wrong in a known direction is worse than no number, because
    nothing downstream can tell it apart from a good one.
    """
    assert estimated_one_rep_max(100.0, 11) is None
    assert estimated_one_rep_max(60.0, 20) is None


def test_a_bodyweight_set_has_no_estimate():
    assert estimated_one_rep_max(0.0, 10) is None


# ── Progression ──────────────────────────────────────────────────────────────


def test_a_loaded_lift_trends_on_its_estimated_one_rep_max():
    sets = [
        _set(week, "Back Squat", "quads", 100 + week * 2.5, 5)
        for week in range(6)
    ]
    exercise = exercise_progression(sets)[0]

    assert exercise["exercise_title"] == "Back Squat"
    assert exercise["muscle_group"] == "quads"
    assert exercise["sessions"] == 6
    assert exercise["best_set_weight_kg"] == 112.5
    assert exercise["trend"]["basis"] == "estimated_1rm"
    assert exercise["trend"]["direction"] == "rising"


def test_a_bodyweight_exercise_trends_on_repetitions():
    """Eight pull-ups to fifteen is progression, and its volume is zero throughout.

    Reporting `flat` here — which tracking volume would do — is a wrong answer,
    not a missing one.
    """
    sets = [_set(week, "Pull-up", "back", None, 8 + week) for week in range(6)]
    exercise = exercise_progression(sets)[0]

    assert exercise["trend"]["basis"] == "reps"
    assert exercise["trend"]["direction"] == "rising"
    assert exercise["best_set_weight_kg"] is None
    assert exercise["latest_estimated_1rm_kg"] is None


def test_a_high_rep_lift_falls_back_to_volume():
    """Epley is not computed above ten reps, so the load still has to count."""
    sets = [_set(week, "Leg Press", "quads", 80 + week * 5, 15) for week in range(6)]
    exercise = exercise_progression(sets)[0]

    assert exercise["trend"]["basis"] == "volume"
    assert exercise["trend"]["direction"] == "rising"


def test_too_few_sessions_report_no_direction():
    """Two points make a line through any two numbers, which is not a trend."""
    sets = [_set(week, "Back Squat", "quads", 100, 5) for week in range(2)]
    exercise = exercise_progression(sets)[0]

    assert exercise["sessions"] == 2
    assert exercise["trend"] is None
    # The figures that need no trend are still there.
    assert exercise["best_set_weight_kg"] == 100.0


def test_two_sessions_in_one_day_are_two_data_points():
    """Grouped by session, not by date — a double day is two sessions."""
    morning = _set(0, "Bench Press", "chest", 80, 5)
    evening = StrengthSet(
        at=BASE + timedelta(hours=9),
        session_id="streak:evening",
        source_id="src",
        exercise_title="Bench Press",
        muscle_group="chest",
        weight_kg=85.0,
        reps=5.0,
        volume_kg=425.0,
        set_number=1,
        has_weight=True,
    )
    exercise = exercise_progression([morning, evening])[0]
    assert exercise["sessions"] == 2


def test_a_set_without_a_session_id_falls_back_to_its_day():
    """A set stored before sessions existed still groups sensibly."""
    rows = [
        StrengthSet(
            at=BASE + timedelta(days=day),
            session_id="",
            source_id="src",
            exercise_title="Row",
            muscle_group="back",
            weight_kg=60.0,
            reps=8.0,
            volume_kg=480.0,
            set_number=index,
            has_weight=True,
        )
        for day in range(3)
        for index in (1, 2)
    ]
    exercise = exercise_progression(rows)[0]
    assert exercise["sessions"] == 3, "three days, six sets"
    assert exercise["total_sets"] == 6


def test_the_history_is_oldest_first():
    """The slope's sign means nothing unless the series runs forwards."""
    sets = [_set(week, "Deadlift", "hamstrings", 120 + week * 5, 3) for week in (3, 0, 2, 1)]
    exercise = exercise_progression(sets)[0]
    days = [session["day"] for session in exercise["history"]]
    assert days == sorted(days)


# ── Muscle balance ───────────────────────────────────────────────────────────


def test_muscle_group_volume_is_a_share_of_the_whole():
    sets = [
        _set(0, "Back Squat", "quads", 100, 5),
        _set(0, "Back Squat", "quads", 100, 5, number=2),
        _set(0, "Bench Press", "chest", 80, 5),
    ]
    split = {row["muscle_group"]: row for row in muscle_group_volume(sets)}

    assert split["quads"]["sets"] == 2
    assert split["chest"]["sets"] == 1
    assert split["quads"]["set_share_pct"] == pytest.approx(66.7, abs=0.1)
    assert sum(row["volume_kg"] for row in split.values()) == pytest.approx(1400.0)


def test_bodyweight_sets_are_counted_even_though_they_carry_no_volume():
    """Leaving them out would make a calisthenics programme look like no training."""
    sets = [
        _set(0, "Pull-up", "back", None, 10),
        _set(0, "Push-up", "chest", None, 20),
    ]
    split = muscle_group_volume(sets)

    assert {row["muscle_group"] for row in split} == {"back", "chest"}
    assert all(row["sets"] == 1 for row in split)
    # No volume anywhere, so a volume share would be a division by zero.
    assert all(row["volume_share_pct"] is None for row in split)


def test_a_set_with_no_muscle_group_lands_in_other():
    split = muscle_group_volume([_set(0, "Something", "", 50, 5)])
    assert split[0]["muscle_group"] == "other"


# ── The bundle section ───────────────────────────────────────────────────────


def test_an_empty_workspace_gets_an_empty_section_not_a_missing_one():
    """A reader who has never lifted sees nothing, and a consumer never branches."""
    section = strength_progression([])

    assert section["exercises"] == []
    assert section["muscle_groups"] == []
    assert section["sets_analysed"] == 0
    assert section["truncated"] is False
    assert section["min_sessions_for_trend"] == MIN_SESSIONS_FOR_PROGRESSION
    assert section["disclaimer"]


def test_the_section_reports_a_shortened_read():
    section = strength_progression([_set(0, "Row", "back", 60, 8)], truncated=True)
    assert section["truncated"] is True
    assert section["sets_analysed"] == 1


def test_exercises_are_ordered_by_the_work_that_went_into_them():
    """Total volume, not the heaviest bar and not alphabetical.

    One squat set at 100 kg x 5 is 500 kg; three curl sets at 20 kg x 10 is 600.
    The curls come first, which is what "how much work went into it" means and
    what makes the `MAX_EXERCISES` cap keep the training rather than the alphabet.
    """
    sets = [_set(0, "Back Squat", "quads", 100, 5)] + [
        _set(0, "Curl", "biceps", 20, 10, number=index) for index in range(1, 4)
    ]
    rows = strength_progression(sets)["exercises"]
    assert [row["exercise_title"] for row in rows] == ["Curl", "Back Squat"]
    assert rows[0]["total_volume_kg"] == 600.0
    assert rows[1]["total_volume_kg"] == 500.0


def test_a_direction_is_a_stable_identifier():
    """Rule 17: a client branches on this, so it is never prose.

    The vocabulary matches `trend_for_metric`, which the rest of the bundle already
    uses — `rising` / `falling` / `flat`, not a second set of words meaning the
    same thing.
    """
    sets = [_set(week, "Back Squat", "quads", 100 + week * 2.5, 5) for week in range(6)]
    direction = exercise_progression(sets)[0]["trend"]["direction"]
    assert direction in {"rising", "falling", "flat"}
    assert direction == direction.lower()
