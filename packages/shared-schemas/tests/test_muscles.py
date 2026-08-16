"""The muscle-group vocabulary, and the promise that an unknown one is visible."""

import pytest
from shared_schemas.muscles import (
    MUSCLE_GROUP_ALIASES,
    MuscleGroup,
    resolve_muscle_group,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Chest", MuscleGroup.CHEST),
        ("chest", MuscleGroup.CHEST),
        ("  CHEST  ", MuscleGroup.CHEST),
        ("Brust", MuscleGroup.CHEST),
        ("Rücken", MuscleGroup.BACK),
        ("Ruecken", MuscleGroup.BACK),
        ("Bizeps", MuscleGroup.BICEPS),
        ("Waden", MuscleGroup.CALVES),
        ("Bauch", MuscleGroup.CORE),
        ("Ganzkörper", MuscleGroup.FULL_BODY),
    ],
)
def test_a_provider_category_maps_to_a_canonical_group(raw, expected):
    assert resolve_muscle_group(raw) is expected


@pytest.mark.parametrize("raw", ["Upper Body", "upper-body", "upper_body", "UPPER BODY"])
def test_separators_and_case_collapse(raw):
    """One alias entry per concept, not one per typography."""
    assert resolve_muscle_group(raw) is MuscleGroup.OTHER


def test_an_unknown_category_is_none_not_other():
    """`None` is the signal the caller reports; `other` is what it then stores.

    Collapsing straight to `other` would make a provider's renamed vocabulary
    invisible, which is the failure rule 19 exists to prevent.
    """
    assert resolve_muscle_group("Kettlebell Complex") is None
    assert resolve_muscle_group("") is None
    assert resolve_muscle_group(None) is None


def test_a_coarse_arm_label_is_not_guessed_into_one_head():
    """`Arms` covers two muscles that move in opposite directions.

    Reading it as biceps would file every triceps set under the wrong muscle —
    a wrong number, which is worse than a missing one.
    """
    assert resolve_muscle_group("Arms") is MuscleGroup.OTHER
    assert resolve_muscle_group("Arme") is MuscleGroup.OTHER


def test_every_canonical_value_is_a_lowercase_identifier():
    """Rule 17: a client compares against these, so they are identifiers, not prose."""
    for group in MuscleGroup:
        assert group.value == group.value.lower()
        assert " " not in group.value
        assert group.value.replace("_", "").isalpha()


def test_every_alias_resolves_to_a_real_group():
    for raw, group in MUSCLE_GROUP_ALIASES.items():
        assert isinstance(group, MuscleGroup)
        assert raw == raw.casefold().strip()
