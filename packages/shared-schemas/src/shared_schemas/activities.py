"""One activity, one name — the registry rule 15 states for metrics, for workouts.

A workout arrived carrying whatever its provider called it, and nothing else. WHOOP
wrote that under ``activity_name``, Apple Health under ``workout_name``, so a reader
had to know both keys; and what it found there was display prose in the user's own
language. In one workspace the same activity appeared as ``Radfahren``, ``Outdoor
Radfahren`` and ``Innenräume Radfahren``, while running arrived as ``Laufen`` from one
provider and ``Outdoor Ausführen`` — Apple's own odd translation of "Outdoor Run" —
from the other.

Rule 17 is the one that broke: **a field a client compares against is an identifier,
not prose.** There was no such field at all, so "which of these were runs" had no
answer that did not amount to matching translated strings, and the question could not
be asked of the data.

So every workout point now carries two things:

``activity_type``
    A key from :data:`ACTIVITY_TYPES` — stable, English, lowercase, the same for every
    provider. This is what a query filters on.

``activity_label``
    What the provider itself called it, unchanged. Kept because rule 19 says a value
    that arrived is stored or named, and because it is the only way to audit a mapping
    after the fact: when ``activity_label`` says ``Paddeltennis`` and ``activity_type``
    says ``padel``, both halves of that claim are visible.

The German literals in :data:`_ALIASES` are provider vocabulary, not repository prose —
the same category as ``HKWorkoutActivityTypeRunning``, and the same arrangement the
WHOOP archive reader already uses for its German CSV headers. Rule 16 governs the text
this project writes; it does not reach the strings other systems send us.

**An unrecognised activity becomes** :data:`OTHER` **and keeps its label.** Not a
guess, not a silent drop: a workout whose type nobody mapped is still a workout with a
date and a duration, and the label is right there to be read. Adding the alias later
costs one line here and a backfill run.
"""

from __future__ import annotations

import re
from types import MappingProxyType

#: What an activity is called when no alias matches. Never a failure: the point keeps
#: its `activity_label`, and rule 19's "named, not dropped" is satisfied by both.
OTHER = "other"

#: Canonical activity keys. Deliberately coarse — this is what a person groups their
#: training by, not a taxonomy of every sport a watch can record. A distinction worth
#: filtering on earns a key; everything else is `other` plus its label.
ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        "running",
        "cycling",
        "walking",
        "hiking",
        "swimming",
        "rowing",
        "strength_training",
        "functional_training",
        "yoga",
        "climbing",
        "skiing",
        "snowboarding",
        "tennis",
        "padel",
        "squash",
        "badminton",
        "golf",
        "football",
        "basketball",
        "boxing",
        "martial_arts",
        "dancing",
        "elliptical",
        "stair_climbing",
        "surfing",
        "paddling",
        "skating",
        "horse_riding",
        "pilates",
        "meditation",
        OTHER,
    }
)

#: Qualifiers that describe *where* an activity happened, not *what* it was. Apple
#: prefixes them onto the display name (`Outdoor Radfahren`, `Innenräume Radfahren`),
#: and keeping them would split one activity into three. Indoor-ness is not lost: the
#: importers already store `is_indoor` beside this.
_QUALIFIERS: tuple[str, ...] = (
    "outdoor",
    "indoor",
    "innenraeume",
    "innenraume",
    "draussen",
    "drinnen",
    "open water",
    "openwater",
    "pool",
    "traditional",
    "cross country",
    "downhill",
)

#: Provider vocabulary → canonical key. English, German, and Apple's own identifiers
#: after `HKWorkoutActivityType` has been stripped. A name that is already canonical
#: needs no entry; `_normalise` finds it directly.
_ALIASES: MappingProxyType[str, str] = MappingProxyType(
    {
        # running
        "run": "running",
        "runs": "running",
        "jogging": "running",
        "trail run": "running",
        "treadmill": "running",
        "laufen": "running",
        "joggen": "running",
        # Apple translates "Run" as "Ausführen" — the software sense of the word.
        "ausfuehren": "running",
        "laufband": "running",
        # cycling
        "bike": "cycling",
        "biking": "cycling",
        "cycle": "cycling",
        "cycling sport": "cycling",
        "handcycling": "cycling",
        "radfahren": "cycling",
        "rad": "cycling",
        "fahrradfahren": "cycling",
        "spinning": "cycling",
        # walking
        "walk": "walking",
        "gehen": "walking",
        "spazieren": "walking",
        "spaziergang": "walking",
        "nordic walking": "walking",
        # hiking
        "hike": "hiking",
        "wandern": "hiking",
        "trekking": "hiking",
        # swimming
        "swim": "swimming",
        "schwimmen": "swimming",
        "water fitness": "swimming",
        # rowing
        "row": "rowing",
        "rudern": "rowing",
        "ergometer": "rowing",
        # strength
        "strength": "strength_training",
        "weightlifting": "strength_training",
        "weight lifting": "strength_training",
        "weight training": "strength_training",
        "strength training": "strength_training",
        "resistance training": "strength_training",
        "krafttraining": "strength_training",
        "traditionelles krafttraining": "strength_training",
        "gewichtheben": "strength_training",
        # WHOOP's own activity name, and its German rendering.
        "strength trainer": "strength_training",
        "kraftgeraet": "strength_training",
        "kraftsport": "strength_training",
        # functional / mixed
        "functional strength training": "functional_training",
        "functional training": "functional_training",
        "funktionelles training": "functional_training",
        "cross training": "functional_training",
        "crossfit": "functional_training",
        "hiit": "functional_training",
        "high intensity interval training": "functional_training",
        "circuit training": "functional_training",
        "core training": "functional_training",
        "zirkeltraining": "functional_training",
        # racquet sports
        "table tennis": "tennis",
        "tischtennis": "tennis",
        "paddel tennis": "padel",
        "paddeltennis": "padel",
        "padel tennis": "padel",
        "pickleball": "padel",
        "federball": "badminton",
        # ball sports
        "soccer": "football",
        "fussball": "football",
        "basketball sport": "basketball",
        # other movement
        "yoga sport": "yoga",
        "pilates training": "pilates",
        "boxen": "boxing",
        "kickboxing": "boxing",
        "kampfsport": "martial_arts",
        "martial arts": "martial_arts",
        "kickboxen": "martial_arts",
        "dance": "dancing",
        "tanzen": "dancing",
        "klettern": "climbing",
        "bouldern": "climbing",
        "rock climbing": "climbing",
        "ski": "skiing",
        "skifahren": "skiing",
        "snow sports": "skiing",
        "snowboard": "snowboarding",
        "snowboarden": "snowboarding",
        "elliptical trainer": "elliptical",
        "crosstrainer": "elliptical",
        "stairs": "stair_climbing",
        "stair climbing": "stair_climbing",
        "treppensteigen": "stair_climbing",
        "surfing sport": "surfing",
        "surfen": "surfing",
        "paddle sports": "paddling",
        "paddling sport": "paddling",
        "stand up paddling": "paddling",
        "kayaking": "paddling",
        "kajak": "paddling",
        "canoeing": "paddling",
        "skating sports": "skating",
        "inline skating": "skating",
        "eislaufen": "skating",
        "equestrian sports": "horse_riding",
        "reiten": "horse_riding",
        "mind and body": "meditation",
        "meditation session": "meditation",
        "atemuebung": "meditation",
        # explicitly nothing more than "a workout happened"
        "workout": OTHER,
        "training": OTHER,
        "activity": OTHER,
        "aktivitaet": OTHER,
        "other workout": OTHER,
        "sonstiges": OTHER,
    }
)

_HK_PREFIX = re.compile(r"^hkworkoutactivitytype", re.IGNORECASE)
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

#: Transliterations, applied before anything else. Matching on the umlaut alone would
#: make the table depend on which normalisation form a provider happened to send.
_TRANSLITERATIONS = (
    ("ä", "ae"),
    ("ö", "oe"),
    ("ü", "ue"),
    ("ß", "ss"),
)


def _normalise(raw: str) -> str:
    """Fold a provider's spelling down to comparable words.

    `HKWorkoutActivityTypeTraditionalStrengthTraining`, `Traditional Strength
    Training` and `traditional_strength_training` are one thing said three ways, and
    every provider sends a different one of them.
    """
    text = _HK_PREFIX.sub("", raw.strip())
    text = _CAMEL_BOUNDARY.sub(" ", text).lower()
    for character, replacement in _TRANSLITERATIONS:
        text = text.replace(character, replacement)
    return _NON_ALPHANUMERIC.sub(" ", text).strip()


def _without_qualifiers(text: str) -> str:
    words = text.split()
    kept = [word for word in words if word not in _QUALIFIERS]
    # Multi-word qualifiers ("open water") survive the word filter, so remove them
    # from the joined form too.
    joined = " ".join(kept)
    for qualifier in _QUALIFIERS:
        if " " in qualifier:
            joined = joined.replace(qualifier, " ")
    return " ".join(joined.split())


def canonical_activity_type(raw: str | None) -> str:
    """Resolve a provider's activity name to a canonical key.

    Returns :data:`OTHER` for anything unrecognised, including an empty value. This
    never raises: an unmapped activity is a gap in the alias table, and failing an
    import over one would lose a workout that is otherwise perfectly well described.
    """
    if not raw:
        return OTHER

    normalised = _normalise(str(raw))
    if not normalised:
        return OTHER

    for candidate in (normalised, _without_qualifiers(normalised)):
        if not candidate:
            continue
        underscored = candidate.replace(" ", "_")
        if underscored in ACTIVITY_TYPES:
            return underscored
        if candidate in _ALIASES:
            return _ALIASES[candidate]
        # `Outdoor Cycling Sport` and friends: the alias table holds the phrase, the
        # canonical set holds the single word, and either may be what is left.
        singular = candidate.removesuffix("s")
        if singular in _ALIASES:
            return _ALIASES[singular]
        if singular.replace(" ", "_") in ACTIVITY_TYPES:
            return singular.replace(" ", "_")

    return OTHER


def activity_metadata(raw: str | None) -> dict[str, str]:
    """The two keys every workout point carries, from whatever the provider sent.

    The label is omitted rather than invented when the provider named nothing; the
    type is always present, so a filter never has to reason about a missing key.
    """
    metadata = {"activity_type": canonical_activity_type(raw)}
    label = (raw or "").strip()
    if label:
        metadata["activity_label"] = label
    return metadata
