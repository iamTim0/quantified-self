"""Muscle groups — one vocabulary, mapped onto rather than copied from a provider.

Streak states a category per exercise, and that category *is* the muscle group. It
would be a line of code to store it as it arrives, and that line is the reason this
module exists instead.

A provider's own vocabulary is a provider's to change. Streak can rename ``Legs`` to
``Lower Body`` in a release, localise it to whatever the phone's language is, or split
it in two — and a dashboard grouping directly on that string would silently start
showing two groups where there was one, with no error anywhere. The same applies the
moment a *second* strength source arrives (Hevy, Strong, a CSV import): two vocabularies
describing the same muscles, and nothing to say that ``Chest`` and ``Brust`` are one
group.

So the provider's string is kept exactly as it arrived, in ``exercise_category``, and a
canonical :class:`MuscleGroup` is stored beside it in ``muscle_group``. The mapping is
here, in one place, and changing it is a commit rather than a surprise.

The canonical values are **stable lowercase English identifiers** (rule 17): a client
compares against them and the dashboard translates them through ``muscle.<value>`` keys.
They are never prose and never localised on this side.

An unrecognised category resolves to ``None``, which the caller turns into
:attr:`MuscleGroup.OTHER` *and* reports through the field report. That pairing is the
point — collapsing an unknown vocabulary into ``other`` silently is how a provider's
rename becomes invisible, which is exactly what rule 19 forbids.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "MUSCLE_GROUP_ALIASES",
    "MuscleGroup",
    "resolve_muscle_group",
]


class MuscleGroup(StrEnum):
    """What a strength exercise trains, in this platform's own words.

    Deliberately anatomical rather than split-based: ``push``/``pull``/``legs`` is a
    *programme*, and two people using the same app disagree about which exercise
    belongs to which. Which muscle a movement loads is a fact about the movement.
    """

    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    QUADS = "quads"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    CALVES = "calves"
    CORE = "core"
    #: A compound movement no single group owns — a clean, a burpee, a Turkish get-up.
    FULL_BODY = "full_body"
    #: Conditioning logged inside a strength session: rowing, assault bike, running.
    CARDIO = "cardio"
    #: Recognised as a category, but not one of the above. Distinct from *unmapped*:
    #: the caller reports an unmapped value, and stores it as this.
    OTHER = "other"


def _normalise(raw: str) -> str:
    """Fold a provider's spelling down to a lookup key.

    Case, surrounding space, and the separators apps disagree about
    (``Upper Body`` / ``upper-body`` / ``upper_body``) all collapse, so the alias
    table holds one entry per concept instead of one per typography.
    """
    folded = raw.strip().casefold()
    for separator in ("-", "_", "/", "\\", "."):
        folded = folded.replace(separator, " ")
    return " ".join(folded.split())


#: Provider vocabulary to canonical group. German spellings are here because Streak
#: and comparable apps localise their category list to the phone's language, so the
#: same workout logged on a German phone would otherwise be a different group. These
#: are *data being recognised*, not interface strings, so they are not a rule 16
#: exception — nothing here is shown to anyone.
MUSCLE_GROUP_ALIASES: dict[str, MuscleGroup] = {
    # ── Chest ────────────────────────────────────────────────────────────────
    "chest": MuscleGroup.CHEST,
    "pecs": MuscleGroup.CHEST,
    "pectorals": MuscleGroup.CHEST,
    "brust": MuscleGroup.CHEST,
    # ── Back ─────────────────────────────────────────────────────────────────
    "back": MuscleGroup.BACK,
    "lats": MuscleGroup.BACK,
    "latissimus": MuscleGroup.BACK,
    "upper back": MuscleGroup.BACK,
    "lower back": MuscleGroup.BACK,
    "traps": MuscleGroup.BACK,
    "trapezius": MuscleGroup.BACK,
    "ruecken": MuscleGroup.BACK,
    "rücken": MuscleGroup.BACK,
    "latzug": MuscleGroup.BACK,
    # ── Shoulders ────────────────────────────────────────────────────────────
    "shoulders": MuscleGroup.SHOULDERS,
    "shoulder": MuscleGroup.SHOULDERS,
    "delts": MuscleGroup.SHOULDERS,
    "deltoids": MuscleGroup.SHOULDERS,
    "schultern": MuscleGroup.SHOULDERS,
    "schulter": MuscleGroup.SHOULDERS,
    # ── Arms ─────────────────────────────────────────────────────────────────
    # `arms` is not a group of its own: an exercise that loads both heads is a
    # compound, and one that loads neither is not an arm exercise. Mapping the
    # generic label to biceps would quietly attribute every triceps set to the
    # wrong muscle, so it maps to OTHER and the raw value survives beside it.
    "arms": MuscleGroup.OTHER,
    "arme": MuscleGroup.OTHER,
    "biceps": MuscleGroup.BICEPS,
    "bicep": MuscleGroup.BICEPS,
    "bizeps": MuscleGroup.BICEPS,
    "triceps": MuscleGroup.TRICEPS,
    "tricep": MuscleGroup.TRICEPS,
    "trizeps": MuscleGroup.TRICEPS,
    "forearms": MuscleGroup.FOREARMS,
    "forearm": MuscleGroup.FOREARMS,
    "unterarme": MuscleGroup.FOREARMS,
    "grip": MuscleGroup.FOREARMS,
    # ── Legs ─────────────────────────────────────────────────────────────────
    # `legs` and `beine` are the coarse label most apps ship. Quads is the honest
    # reading — a squat, a leg press and a lunge are what fills that category —
    # and the provider's own word stays in `exercise_category` either way.
    "legs": MuscleGroup.QUADS,
    "leg": MuscleGroup.QUADS,
    "beine": MuscleGroup.QUADS,
    "quads": MuscleGroup.QUADS,
    "quadriceps": MuscleGroup.QUADS,
    "oberschenkel": MuscleGroup.QUADS,
    "hamstrings": MuscleGroup.HAMSTRINGS,
    "hamstring": MuscleGroup.HAMSTRINGS,
    "beinbeuger": MuscleGroup.HAMSTRINGS,
    "glutes": MuscleGroup.GLUTES,
    "glute": MuscleGroup.GLUTES,
    "gesaess": MuscleGroup.GLUTES,
    # `str.casefold()` maps ß to "ss", so the lookup never sees "gesäß" and an
    # entry spelled that way would be dead. Every key here is stored already
    # folded, which `test_every_alias_resolves_to_a_real_group` pins.
    "gesäss": MuscleGroup.GLUTES,
    "po": MuscleGroup.GLUTES,
    "calves": MuscleGroup.CALVES,
    "calf": MuscleGroup.CALVES,
    "waden": MuscleGroup.CALVES,
    # ── Core ─────────────────────────────────────────────────────────────────
    "core": MuscleGroup.CORE,
    "abs": MuscleGroup.CORE,
    "abdominals": MuscleGroup.CORE,
    "obliques": MuscleGroup.CORE,
    "bauch": MuscleGroup.CORE,
    "rumpf": MuscleGroup.CORE,
    # ── Whole body ───────────────────────────────────────────────────────────
    "full body": MuscleGroup.FULL_BODY,
    "fullbody": MuscleGroup.FULL_BODY,
    "total body": MuscleGroup.FULL_BODY,
    "compound": MuscleGroup.FULL_BODY,
    "olympic": MuscleGroup.FULL_BODY,
    "ganzkoerper": MuscleGroup.FULL_BODY,
    "ganzkörper": MuscleGroup.FULL_BODY,
    # `upper body` and `lower body` are halves, not muscles. Neither maps to a
    # single group without inventing a fact, so both stay OTHER.
    "upper body": MuscleGroup.OTHER,
    "lower body": MuscleGroup.OTHER,
    "oberkoerper": MuscleGroup.OTHER,
    "oberkörper": MuscleGroup.OTHER,
    "unterkoerper": MuscleGroup.OTHER,
    "unterkörper": MuscleGroup.OTHER,
    # ── Conditioning logged in a strength session ────────────────────────────
    "cardio": MuscleGroup.CARDIO,
    "conditioning": MuscleGroup.CARDIO,
    "ausdauer": MuscleGroup.CARDIO,
    "rowing": MuscleGroup.CARDIO,
    "running": MuscleGroup.CARDIO,
    # ── Explicitly nothing ───────────────────────────────────────────────────
    "other": MuscleGroup.OTHER,
    "misc": MuscleGroup.OTHER,
    "sonstiges": MuscleGroup.OTHER,
}


def resolve_muscle_group(raw: str | None) -> MuscleGroup | None:
    """Map a provider's category onto the canonical vocabulary.

    Returns ``None`` for anything unrecognised — including an empty value — rather
    than guessing. ``None`` is a signal the caller acts on: store
    :attr:`MuscleGroup.OTHER` *and* name the raw value in the field report, so a
    provider that changed its vocabulary shows up in the Data Quality Center
    instead of quietly becoming ``other`` forever.

    >>> resolve_muscle_group("Brust")
    <MuscleGroup.CHEST: 'chest'>
    >>> resolve_muscle_group("Upper-Body")
    <MuscleGroup.OTHER: 'other'>
    >>> resolve_muscle_group("Kettlebell") is None
    True
    """
    if not raw:
        return None
    return MUSCLE_GROUP_ALIASES.get(_normalise(str(raw)))
