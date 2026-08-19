"""The activity vocabulary, tested against what providers actually sent.

Every string in `test_real_provider_wording_resolves` was read out of a live
workspace. They are the reason this module exists: one activity arrived under three
spellings and two providers disagreed about which key to put it in, so "which of
these were runs" had no answer a query could give.
"""

from __future__ import annotations

import pytest
from shared_schemas.activities import (
    ACTIVITY_TYPES,
    OTHER,
    activity_metadata,
    canonical_activity_type,
)


@pytest.mark.parametrize(
    ("wording", "expected"),
    [
        # WHOOP, German UI
        ("Radfahren", "cycling"),
        ("Laufen", "running"),
        ("Spazieren", "walking"),
        ("Gehen", "walking"),
        ("Gewichtheben", "strength_training"),
        ("Schwimmen", "swimming"),
        ("Funktionelles Training", "functional_training"),
        ("Paddeltennis", "padel"),
        ("Padel", "padel"),
        ("Tennis", "tennis"),
        # Apple Health push, German display names with a place qualifier
        ("Outdoor Radfahren", "cycling"),
        ("Innenräume Radfahren", "cycling"),
        # Apple's own translation of "Outdoor Run" — the software sense of "run".
        ("Outdoor Ausführen", "running"),
        # Apple Health archive, the machine-readable identifier
        ("HKWorkoutActivityTypeRunning", "running"),
        ("HKWorkoutActivityTypeTraditionalStrengthTraining", "strength_training"),
        ("HKWorkoutActivityTypeCycling", "cycling"),
        # Already canonical, and the snake_case the archive path produces
        ("running", "running"),
        ("traditional_strength_training", "strength_training"),
    ],
)
def test_real_provider_wording_resolves(wording: str, expected: str) -> None:
    assert canonical_activity_type(wording) == expected


def test_one_activity_does_not_split_across_place_qualifiers() -> None:
    """Indoor and outdoor cycling are cycling. Where it happened is `is_indoor`."""
    spellings = {"Radfahren", "Outdoor Radfahren", "Innenräume Radfahren", "Cycling"}
    assert {canonical_activity_type(name) for name in spellings} == {"cycling"}


@pytest.mark.parametrize("wording", ["", None, "   ", "Kitesurfen", "Aktivität", "Workout"])
def test_anything_unrecognised_is_other_and_never_raises(wording: str | None) -> None:
    """An unmapped activity is a gap in the alias table, not a reason to fail.

    Failing an import over one would lose a workout that is otherwise perfectly
    well described — it has a start, a duration and a distance.
    """
    assert canonical_activity_type(wording) == OTHER


def test_every_alias_target_is_a_declared_type() -> None:
    """A typo in the alias table would otherwise produce a key nothing can filter."""
    for wording in ("Radfahren", "Laufen", "Paddeltennis", "Kickboxen", "Bouldern"):
        assert canonical_activity_type(wording) in ACTIVITY_TYPES


def test_metadata_keeps_the_provider_wording_beside_the_type() -> None:
    """Rule 19: the value that arrived stays readable next to what we made of it.

    Without the label, `padel` from `Paddeltennis` is an unauditable claim — there
    would be no way to tell a correct mapping from a wrong one after the fact.
    """
    assert activity_metadata("Paddeltennis") == {
        "activity_type": "padel",
        "activity_label": "Paddeltennis",
    }


def test_metadata_omits_a_label_nobody_sent() -> None:
    """The type is always present so a filter never reasons about a missing key;
    the label is absent rather than invented."""
    assert activity_metadata(None) == {"activity_type": OTHER}
    assert activity_metadata("") == {"activity_type": OTHER}
