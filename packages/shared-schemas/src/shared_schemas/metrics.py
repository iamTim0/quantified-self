"""The metric registry — one central definition of every metric the platform stores.

Before this module, ``metric_type`` was a free-form string invented independently in
every transformer. Whoop called a workout's mean pulse ``workout_average_heart_rate``
and Apple Health called the same quantity ``workout_avg_heart_rate``; Whoop reported
burned energy in kilojoules and Apple Health in kilocalories under names that gave no
hint of either; the calendar importer emitted ``calendar_busy_minutes`` *and*
``calendar_busy_hours``, the same number twice, because the unit lived in the name.
Nothing downstream could tell any of that apart, so ``find_cross_source_conflicts``
compared kJ against kcal and the correlation analysis happily reported r=1.0 between a
duration and the same duration in other units.

Two rules make that impossible from here on:

1. **One quantity, one name.** The name says what is measured, never who measured it
   and never in what unit. Two sources reporting the same physical quantity write the
   same ``metric_type``. Provider-proprietary composites, which are *not* comparable
   across sources, carry their vendor prefix on purpose (``whoop_strain``) so that
   nobody mistakes them for one.
2. **One name, one unit.** :attr:`MetricDefinition.unit` is the unit of every value
   ever stored under that key. Importers convert on the way in (see :func:`convert`);
   they do not invent a second metric for a second unit.

The registry is the single source of truth for both. Python services import it
directly; the dashboard consumes ``catalog.ts``, generated from this module by
``packages/shared-schemas/generate_catalog.py`` so the two cannot drift.

Open-ended providers do not get to bypass the catalog, but they are not forced into it
either: a :class:`MetricNamespace` declares a prefix under which unregistered names are
legal (Home Assistant exposes whatever entities a user happens to own, and a CSV import
maps whatever columns a user happens to have). Those keep their unit in the event
metadata, which is the honest answer when the unit is only known at runtime.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

__all__ = [
    "CANONICAL_KEYS",
    "DYNAMIC_NAMESPACES",
    "METRIC_ALIASES",
    "METRIC_CATALOG",
    "NEVER_PURGED_CATEGORIES",
    "Aggregation",
    "IngestResolution",
    "MetricCategory",
    "MetricDefinition",
    "MetricNamespace",
    "MetricUnit",
    "UnknownMetricTypeError",
    "UnsupportedConversionError",
    "canonical_metric_type",
    "convert",
    "describe",
    "is_known_metric_type",
    "metrics_for_source",
    "resolve",
]


class MetricUnit(StrEnum):
    """Units a value can carry.

    Members that no catalog entry uses as its canonical unit (``KILOJOULE``,
    ``SECOND``, ``HOUR``, ``MILE``, ``POUND``, ``FOOT``, ``YARD``, ``MILE_PER_HOUR``)
    exist because a *provider* reports in them and an importer has to name what it is
    converting from. Health Auto
    Export, for one, follows the phone's locale, so the same Apple Health metric arrives
    in miles or kilometres depending on whose phone it came from.
    """

    COUNT = "count"
    WATT = "W"
    KCAL = "kcal"
    KILOJOULE = "kJ"
    GRAM = "g"
    MILLIGRAM = "mg"
    MILLILITER = "mL"
    KILOGRAM = "kg"
    POUND = "lb"
    PERCENT = "%"
    BPM = "bpm"
    BREATHS_PER_MINUTE = "br/min"
    MILLISECOND = "ms"
    SECOND = "s"
    MINUTE = "min"
    HOUR = "h"
    METER = "m"
    CENTIMETER = "cm"
    METER_PER_SECOND = "m/s"
    FOOT = "ft"
    YARD = "yd"
    KILOMETER = "km"
    MILE = "mi"
    CELSIUS = "°C"
    HECTOPASCAL = "hPa"
    MMHG = "mmHg"
    MILLIMETER = "mm"
    DECIBEL = "dB"
    KILOMETER_PER_HOUR = "km/h"
    MILE_PER_HOUR = "mph"
    REVOLUTIONS_PER_MINUTE = "rpm"
    DEGREE = "°"
    ML_PER_KG_PER_MIN = "mL/kg/min"
    #: Steps per minute. Distinct from ``BPM`` on purpose: both are "per minute" and
    #: neither is the other, and a cadence stored as a pulse is a cadence nobody finds.
    STEPS_PER_MINUTE = "spm"
    #: Metabolic equivalent of task — how hard an activity is, as a multiple of rest.
    MET = "MET"
    INDEX = "index"
    #: HealthKit's name for "however many of this per minute". It is not a quantity
    #: of its own: Apple reports breathing rate *and* cadence in it, and which one it
    #: means is decided by the metric, not by the unit. It exists so an importer can
    #: name what it is converting from rather than storing a value unconverted.
    COUNT_PER_MINUTE = "count/min"
    #: The unit is only known at runtime and travels in the event metadata. Legal
    #: exclusively for metrics resolved through a :class:`MetricNamespace`.
    RUNTIME = ""


class Aggregation(StrEnum):
    """How several values of one metric collapse into a single number.

    The dashboard summary used to average everything, which is right for a pulse and
    wrong for steps: averaging a day's step counts answers a question nobody asked.
    """

    #: A momentary measurement — average over the period (heart rate, temperature).
    AVERAGE = "average"
    #: An accumulating quantity — sum over the period (steps, calories, duration).
    SUM = "sum"
    #: A standing value where only the newest reading is meaningful (body weight).
    LAST = "last"
    #: A peak that stays a peak however you slice the period.
    MAX = "max"


class IngestResolution(StrEnum):
    """The finest resolution an importer is allowed to persist.

    ``SECOND`` is not a smaller ``MINUTE``; it is close to "keep what the device
    sent". A watch samples heart rate every few seconds during a workout and every
    few minutes at rest, so a second bucket is bounded by the device rather than by
    the clock — it is not 86,400 rows a day, it is the sample count with duplicates
    inside one second collapsed. Minute buckets discarded exactly the part of that
    which mattered: a minute mean over an interval session is a flat line.

    It is deliberately *not* used for accumulating (``SUM``) metrics. The provider
    already states the day's total for steps, distance and energy, so sixty times
    the rows buys no information and risks the double count rule 19 forbids.

    ``metric_rollups`` has no second tier and is not getting one: a rollup exists to
    make a long-range query cheap, and a second rollup has the same cardinality as
    ``data_points``. Second-resolution data *is* ``data_points``.
    """

    RAW = "raw"
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


class MetricCategory(StrEnum):
    """Grouping for presentation and for scoping shares (``read_metric:<category>``)."""

    ACTIVITY = "activity"
    HEART = "heart"
    SLEEP = "sleep"
    BODY = "body"
    NUTRITION = "nutrition"
    WORKOUT = "workout"
    STRENGTH = "strength"
    LOCATION = "location"
    CALENDAR = "calendar"
    ENVIRONMENT = "environment"
    HOME = "home"
    #: Work recorded by a code-hosting platform: commits, changed lines, reviews.
    #:
    #: Its own category rather than a corner of `ACTIVITY`, because "commits" beside
    #: "steps" in one lane is not a grouping anybody reads as meaningful. The names
    #: underneath it say what was measured and not who measured it (rule 15) —
    #: `code_commits`, not `github_commits` — so a second forge reporting the same
    #: quantity later writes the same series rather than a parallel one.
    DEVELOPER = "developer"
    CUSTOM = "custom"


class Cadence(StrEnum):
    """How often a metric is expected to appear — the missing half of "is data missing?".

    Gap detection used to assume every metric produced a value every calendar day,
    for every metric that appeared even once. A rest day therefore *was* a gap in
    `workout_duration`, a scale stepped on twice a month made `body_weight` look
    93 % broken, and in both cases the honest answer is "nothing is missing".

    * ``DAILY`` — one value per day is the expectation. A missing day is a gap.
    * ``CONTINUOUS`` — sampled far more often than daily, at a rate the device
      decides. A gap is a span much longer than the cadence actually observed, not
      an empty calendar day.
    * ``EVENT`` — happens when it happens. Absence carries no information, so no
      gap is ever reported.
    """

    DAILY = "daily"
    CONTINUOUS = "continuous"
    EVENT = "event"


#: Categories whose fine-grained points *are* the measurement, rather than samples
#: of a quantity over time — so a rollup is not a substitute and the raw purge must
#: not touch them by default.
#:
#: A day rollup of ``strength_set_weight`` (``MAX``) is "the heaviest thing lifted
#: that day", which is not the workout. A ``location_point`` rollup is a count,
#: which is not the route — purging those would leave the coordinates
#: unrecoverable, with the rollup still cheerfully reporting how many there were.
#:
#: Expressed as a category rule rather than repeated on thirty definitions so that
#: a *new* workout or strength metric inherits it. Written thirty times, the next
#: metric someone adds would quietly get ninety days and nobody would notice until
#: the data was gone. A definition that wants a limit anyway states one explicitly,
#: as ``workout_heart_rate`` does.
NEVER_PURGED_CATEGORIES: frozenset[MetricCategory] = frozenset({
    MetricCategory.WORKOUT,
    MetricCategory.STRENGTH,
    MetricCategory.LOCATION,
})


class MetricDefinition(BaseModel):
    """What one metric key means, in the only place it is defined."""

    model_config = ConfigDict(frozen=True)

    key: str
    unit: MetricUnit
    aggregation: Aggregation
    category: MetricCategory
    label_de: str
    label_en: str
    #: ``source_type`` values that emit this metric. Empty for keys reachable only
    #: through manual import.
    sources: tuple[str, ...] = ()
    #: Names that mean this metric but must not be written. Importers canonicalise
    #: through :func:`canonical_metric_type`; the aliases exist so a provider field
    #: name, a documentation typo or a CSV header still resolves to one definition.
    aliases: tuple[str, ...] = ()
    #: Range a real reading falls into. Consumed by the data-quality checks; ``None``
    #: means unbounded on that side, not "unchecked".
    plausible_min: float | None = None
    plausible_max: float | None = None
    #: Decimal places for display. 0 means the quantity is only meaningful as a whole.
    precision: int = 1
    #: How often a reading is expected. Consumed by gap detection and by the
    #: "too thin" judgement in the analyses. ``EVENT`` by default because that is
    #: the answer that never invents a problem: a metric nobody has classified
    #: reports no gaps rather than a year of imaginary ones.
    cadence: Cadence = Cadence.EVENT
    #: Importers use this value before publishing. ``None`` derives a safe default:
    #: continuous metrics are minute data, event/daily metrics remain raw.
    ingest_resolution: IngestResolution | None = None
    #: Only fine-grained points (``raw`` and ``second``) are subject to this
    #: retention period; rollups are always retained. ``None`` means **never
    #: purge**, and it is a declaration rather than an omission: it belongs to the
    #: metrics whose fine-grained form *is* the data, where a rollup is not a
    #: substitute. A day rollup of ``strength_set_weight`` is "the heaviest thing
    #: lifted that day", which is not the workout; a ``location_point`` rollup is a
    #: count, which is not the route. Purging those is not keeping the aggregate,
    #: it is deleting the measurement.
    raw_retention_days: int | None = 90

    @model_validator(mode="before")
    @classmethod
    def _never_purge_session_shaped_metrics(cls, data: Any) -> Any:
        """Apply :data:`NEVER_PURGED_CATEGORIES` where no limit was stated.

        ``"raw_retention_days" not in data`` is what separates *defaulted* from
        *deliberately set*, which is why this runs before validation fills the
        default in. A definition that names a number keeps it.
        """
        if (
            isinstance(data, dict)
            and "raw_retention_days" not in data
            and data.get("category") in NEVER_PURGED_CATEGORIES
        ):
            return {**data, "raw_retention_days": None}
        return data

    @property
    def default_ingest_resolution(self) -> IngestResolution:
        """Return the registry default used by stateless importers."""
        if self.ingest_resolution is not None:
            return self.ingest_resolution
        return (
            IngestResolution.MINUTE
            if self.cadence is Cadence.CONTINUOUS
            else IngestResolution.RAW
        )

    @property
    def is_dynamic(self) -> bool:
        """True for definitions synthesised from a namespace rather than catalogued."""
        return self.unit is MetricUnit.RUNTIME


class MetricNamespace(BaseModel):
    """A prefix under which unregistered metric names are legal.

    Deliberately narrow. A namespace is for providers whose metric set is defined by
    the *user's* setup rather than by the provider — every Home Assistant install
    exposes different entities — and for manually mapped imports. It is not an escape
    hatch for an importer that could have catalogued its metrics.
    """

    model_config = ConfigDict(frozen=True)

    prefix: str
    category: MetricCategory
    label_de: str
    label_en: str
    sources: tuple[str, ...] = ()


class UnknownMetricTypeError(ValueError):
    """Raised for a metric name that is neither catalogued nor inside a namespace."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(
            f"Unknown metric_type {raw!r}. Register it in "
            "packages/shared-schemas/src/shared_schemas/metrics.py or emit it under one "
            f"of the dynamic namespaces: {', '.join(ns.prefix for ns in DYNAMIC_NAMESPACES)}"
        )


class UnsupportedConversionError(ValueError):
    """Raised when asked for a conversion the registry does not define."""

    def __init__(self, source: MetricUnit, target: MetricUnit) -> None:
        self.source = source
        self.target = target
        super().__init__(f"No conversion defined from {source.value!r} to {target.value!r}")


# ─── Unit conversion ──────────────────────────────────────────────────────────
#
# Only the conversions importers actually need, spelled out. A general dimensional
# analysis engine would let a caller convert grams to metres and find out at runtime.

_CONVERSIONS: dict[tuple[MetricUnit, MetricUnit], float] = {
    (MetricUnit.KILOJOULE, MetricUnit.KCAL): 1.0 / 4.184,
    (MetricUnit.KCAL, MetricUnit.KILOJOULE): 4.184,
    (MetricUnit.METER, MetricUnit.KILOMETER): 1e-3,
    (MetricUnit.KILOMETER, MetricUnit.METER): 1e3,
    (MetricUnit.CENTIMETER, MetricUnit.METER): 1e-2,
    (MetricUnit.METER, MetricUnit.CENTIMETER): 1e2,
    (MetricUnit.SECOND, MetricUnit.MINUTE): 1.0 / 60.0,
    (MetricUnit.MINUTE, MetricUnit.SECOND): 60.0,
    (MetricUnit.HOUR, MetricUnit.MINUTE): 60.0,
    (MetricUnit.MINUTE, MetricUnit.HOUR): 1.0 / 60.0,
    (MetricUnit.MILLISECOND, MetricUnit.SECOND): 1e-3,
    (MetricUnit.SECOND, MetricUnit.MILLISECOND): 1e3,
    (MetricUnit.GRAM, MetricUnit.KILOGRAM): 1e-3,
    (MetricUnit.KILOGRAM, MetricUnit.GRAM): 1e3,
    (MetricUnit.MILE, MetricUnit.KILOMETER): 1.609344,
    (MetricUnit.KILOMETER, MetricUnit.MILE): 1.0 / 1.609344,
    (MetricUnit.MILE, MetricUnit.METER): 1609.344,
    (MetricUnit.METER, MetricUnit.MILE): 1.0 / 1609.344,
    (MetricUnit.YARD, MetricUnit.KILOMETER): 0.0009144,
    (MetricUnit.KILOMETER, MetricUnit.YARD): 1.0 / 0.0009144,
    (MetricUnit.YARD, MetricUnit.METER): 0.9144,
    (MetricUnit.METER, MetricUnit.YARD): 1.0 / 0.9144,
    (MetricUnit.POUND, MetricUnit.KILOGRAM): 0.45359237,
    (MetricUnit.KILOGRAM, MetricUnit.POUND): 1.0 / 0.45359237,
    # Speed and elevation follow the phone's locale exactly as distance does, and
    # without these a workout recorded on a US phone stores miles per hour and feet
    # under a metric declared in km/h and metres — a wrong number that looks right.
    (MetricUnit.MILE_PER_HOUR, MetricUnit.KILOMETER_PER_HOUR): 1.609344,
    (MetricUnit.KILOMETER_PER_HOUR, MetricUnit.MILE_PER_HOUR): 1.0 / 1.609344,
    (MetricUnit.METER_PER_SECOND, MetricUnit.KILOMETER_PER_HOUR): 3.6,
    (MetricUnit.KILOMETER_PER_HOUR, MetricUnit.METER_PER_SECOND): 1.0 / 3.6,
    (MetricUnit.FOOT, MetricUnit.METER): 0.3048,
    (MetricUnit.METER, MetricUnit.FOOT): 1.0 / 0.3048,
    # Millimetres, for running form. Its absence was not cosmetic: Apple reports
    # `running_vertical_oscillation` in centimetres, the registry declares
    # millimetres, and with no rule here the importer stored the number
    # **unconverted** — every reading a tenth of what it should be, under a metric
    # whose unit says otherwise. 218 of them in two days on one deployment.
    (MetricUnit.CENTIMETER, MetricUnit.MILLIMETER): 10.0,
    (MetricUnit.MILLIMETER, MetricUnit.CENTIMETER): 0.1,
    (MetricUnit.MILLIMETER, MetricUnit.METER): 1e-3,
    (MetricUnit.METER, MetricUnit.MILLIMETER): 1e3,
    # HealthKit's `count/min` against the units that actually name the quantity.
    # Identities, because they *are* the same number — the conversion exists so the
    # value arrives declared rather than "stored unconverted, and we said so once in
    # a log line nobody reads". These three accounted for 4,179 warnings in 48 hours
    # on one deployment, which is a log nobody can scan for real problems.
    (MetricUnit.COUNT_PER_MINUTE, MetricUnit.BREATHS_PER_MINUTE): 1.0,
    (MetricUnit.BREATHS_PER_MINUTE, MetricUnit.COUNT_PER_MINUTE): 1.0,
    (MetricUnit.COUNT_PER_MINUTE, MetricUnit.STEPS_PER_MINUTE): 1.0,
    (MetricUnit.STEPS_PER_MINUTE, MetricUnit.COUNT_PER_MINUTE): 1.0,
    (MetricUnit.COUNT_PER_MINUTE, MetricUnit.BPM): 1.0,
    (MetricUnit.BPM, MetricUnit.COUNT_PER_MINUTE): 1.0,
    # A body-mass index is dimensionless, and HealthKit calls dimensionless `count`.
    (MetricUnit.COUNT, MetricUnit.INDEX): 1.0,
    (MetricUnit.INDEX, MetricUnit.COUNT): 1.0,
}


def convert(value: float, source: MetricUnit, target: MetricUnit) -> float:
    """Convert ``value`` from ``source`` to ``target``.

    >>> round(convert(1000.0, MetricUnit.KILOJOULE, MetricUnit.KCAL), 1)
    239.0
    """
    if source is target:
        return float(value)
    try:
        return float(value) * _CONVERSIONS[(source, target)]
    except KeyError:
        raise UnsupportedConversionError(source, target) from None


# ─── The catalog ──────────────────────────────────────────────────────────────
#
# Ordered by category so the generated documentation table reads top to bottom.

_DEFINITIONS: tuple[MetricDefinition, ...] = (
    # ── Activity ──────────────────────────────────────────────────────────────
    MetricDefinition(
        key="steps",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Schritte",
        label_en="Steps",
        sources=("apple_health",),
        aliases=("step_count", "steps_count"),
        plausible_min=0,
        plausible_max=200_000,
        precision=0,
        cadence=Cadence.DAILY,
        ingest_resolution=IngestResolution.MINUTE,
    ),
    MetricDefinition(
        key="distance",
        unit=MetricUnit.KILOMETER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Zurückgelegte Distanz",
        label_en="Distance travelled",
        sources=("apple_health",),
        aliases=(
            "distance_walking_running",
            "walking_running_distance",
            "distance_cycling",
            "distance_swimming",
            "distance_downhill_snow_sports",
        ),
        plausible_min=0,
        plausible_max=500,
        precision=2,
        cadence=Cadence.DAILY,
        ingest_resolution=IngestResolution.MINUTE,
    ),
    MetricDefinition(
        key="energy_active",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Aktive Energie",
        label_en="Active energy",
        sources=("apple_health",),
        aliases=("active_energy", "active_energy_burned"),
        plausible_min=0,
        plausible_max=15_000,
        precision=0,
        cadence=Cadence.DAILY,
        ingest_resolution=IngestResolution.MINUTE,
    ),
    MetricDefinition(
        key="energy_resting",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Grundumsatz",
        label_en="Resting energy",
        sources=("apple_health",),
        aliases=("resting_energy", "basal_energy_burned"),
        plausible_min=0,
        plausible_max=6_000,
        precision=0,
        cadence=Cadence.DAILY,
        ingest_resolution=IngestResolution.MINUTE,
    ),
    MetricDefinition(
        key="energy_total",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Gesamtumsatz",
        label_en="Total energy burned",
        # Whoop reports a cycle's total burn in kilojoules; the importer converts.
        sources=("whoop",),
        aliases=("cycle_kilojoule",),
        plausible_min=0,
        plausible_max=20_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="exercise_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Bewegungsminuten",
        label_en="Exercise time",
        sources=("apple_health",),
        aliases=("apple_exercise_time",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="stand_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Stehminuten",
        label_en="Stand time",
        sources=("apple_health",),
        aliases=("apple_stand_time",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="flights_climbed",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Etagen",
        label_en="Flights climbed",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="physical_effort",
        unit=MetricUnit.MET,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Körperliche Anstrengung",
        label_en="Physical effort",
        sources=("apple_health",),
        aliases=("physical_effort_mets",),
        plausible_min=0,
        plausible_max=30,
        precision=1,
    ),
    MetricDefinition(
        key="standing_events",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Stehstunden",
        label_en="Stand hours",
        sources=("apple_health",),
        aliases=("apple_stand_hour", "stand_hours"),
        plausible_min=0,
        plausible_max=24,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="daylight_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Zeit im Tageslicht",
        label_en="Time in daylight",
        sources=("apple_health",),
        aliases=("time_in_daylight",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="running_power",
        unit=MetricUnit.WATT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Laufleistung",
        label_en="Running power",
        sources=("apple_health",),
        aliases=("running_power_watts",),
        plausible_min=0,
        plausible_max=2_000,
        precision=0,
    ),
    MetricDefinition(
        key="running_speed",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Laufgeschwindigkeit",
        label_en="Running speed",
        sources=("apple_health",),
        aliases=("running_speed_kmh",),
        plausible_min=0,
        plausible_max=60,
        precision=1,
    ),
    MetricDefinition(
        key="running_stride_length",
        unit=MetricUnit.METER,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Laufschrittlänge",
        label_en="Running stride length",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=5,
        precision=2,
    ),
    MetricDefinition(
        key="running_vertical_oscillation",
        unit=MetricUnit.MILLIMETER,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Vertikale Laufbewegung",
        label_en="Running vertical oscillation",
        sources=("apple_health",),
        aliases=("running_vertical_oscillation_mm",),
        plausible_min=0,
        plausible_max=500,
        precision=1,
    ),
    MetricDefinition(
        key="running_ground_contact_time",
        unit=MetricUnit.MILLISECOND,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Lauf-Bodenkontaktzeit",
        label_en="Running ground contact time",
        sources=("apple_health",),
        aliases=("running_ground_contact_time_ms",),
        plausible_min=0,
        plausible_max=2_000,
        precision=0,
    ),
    MetricDefinition(
        key="walking_step_length",
        unit=MetricUnit.METER,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Schrittlänge beim Gehen",
        label_en="Walking step length",
        sources=("apple_health",),
        aliases=("walking_step_length_m",),
        plausible_min=0,
        plausible_max=3,
        precision=2,
    ),
    MetricDefinition(
        key="walking_speed",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Gehgeschwindigkeit",
        label_en="Walking speed",
        sources=("apple_health",),
        aliases=("walking_speed_kmh",),
        plausible_min=0,
        plausible_max=30,
        precision=1,
    ),
    MetricDefinition(
        key="walking_double_support",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Doppelstützphase beim Gehen",
        label_en="Walking double support",
        sources=("apple_health",),
        aliases=("walking_double_support_percentage",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="walking_asymmetry",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Gehasymmetrie",
        label_en="Walking asymmetry",
        sources=("apple_health",),
        aliases=("walking_asymmetry_percentage",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="walking_steadiness",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.LAST,
        category=MetricCategory.ACTIVITY,
        label_de="Gehrsicherheit",
        label_en="Walking steadiness",
        sources=("apple_health",),
        aliases=("apple_walking_steadiness",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="stair_ascent_speed",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Treppenaufstiegsgeschwindigkeit",
        label_en="Stair ascent speed",
        sources=("apple_health",),
        aliases=("stair_ascent_speed_kmh",),
        plausible_min=0,
        plausible_max=20,
        precision=1,
    ),
    MetricDefinition(
        key="stair_descent_speed",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Treppenabstiegsgeschwindigkeit",
        label_en="Stair descent speed",
        sources=("apple_health",),
        aliases=("stair_descent_speed_kmh",),
        plausible_min=0,
        plausible_max=20,
        precision=1,
    ),
    MetricDefinition(
        key="six_minute_walk_distance",
        unit=MetricUnit.METER,
        aggregation=Aggregation.LAST,
        category=MetricCategory.ACTIVITY,
        label_de="Sechs-Minuten-Gehstrecke",
        label_en="Six-minute walk distance",
        sources=("apple_health",),
        aliases=("six_minute_walk_test_distance",),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
    ),
    MetricDefinition(
        key="swimming_strokes",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Schwimmzüge",
        label_en="Swimming strokes",
        sources=("apple_health",),
        aliases=("swimming_stroke_count",),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
    ),
    MetricDefinition(
        key="handwashing_events",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Handwaschereignisse",
        label_en="Handwashing events",
        sources=("apple_health",),
        aliases=("handwashing_event",),
        plausible_min=0,
        plausible_max=200,
        precision=0,
    ),
    MetricDefinition(
        key="mindful_session_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Achtsamkeitsdauer",
        label_en="Mindful session duration",
        sources=("apple_health",),
        aliases=("mindful_session",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="toothbrushing_events",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Zähneputzereignisse",
        label_en="Toothbrushing events",
        sources=("apple_health",),
        aliases=("toothbrushing_event",),
        plausible_min=0,
        plausible_max=20,
        precision=0,
    ),
    MetricDefinition(
        key="audio_exposure_events",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ENVIRONMENT,
        label_de="Audioexpositionsereignisse",
        label_en="Audio exposure events",
        sources=("apple_health",),
        aliases=("audio_exposure_event", "headphone_audio_exposure_event"),
        plausible_min=0,
        plausible_max=200,
        precision=0,
    ),
    MetricDefinition(
        key="audio_exposure_environmental",
        unit=MetricUnit.DECIBEL,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Umgebungs-Audioexposition",
        label_en="Environmental audio exposure",
        sources=("apple_health",),
        aliases=("environmental_audio_exposure",),
        plausible_min=0,
        plausible_max=160,
        precision=1,
    ),
    MetricDefinition(
        key="audio_exposure_headphone",
        unit=MetricUnit.DECIBEL,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Kopfhörer-Audioexposition",
        label_en="Headphone audio exposure",
        sources=("apple_health",),
        aliases=("headphone_audio_exposure",),
        plausible_min=0,
        plausible_max=160,
        precision=1,
    ),
    MetricDefinition(
        key="audio_exposure_reduction",
        unit=MetricUnit.DECIBEL,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Geräuschreduzierung",
        label_en="Environmental sound reduction",
        sources=("apple_health",),
        aliases=("environmental_sound_reduction",),
        plausible_min=0,
        plausible_max=160,
        precision=1,
    ),
    MetricDefinition(
        key="whoop_strain",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.MAX,
        category=MetricCategory.ACTIVITY,
        # Vendor-prefixed on purpose: a 0–21 logarithmic index defined by Whoop, with
        # no counterpart at any other source. Comparing it to anything is a mistake.
        label_de="Whoop Strain (Tag)",
        label_en="Whoop strain (day)",
        sources=("whoop",),
        aliases=("strain",),
        plausible_min=0,
        plausible_max=21,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    # ── Heart ─────────────────────────────────────────────────────────────────
    MetricDefinition(
        key="blood_pressure_systolic",
        unit=MetricUnit.MMHG,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Blutdruck systolisch",
        label_en="Blood pressure, systolic",
        # Two metrics rather than one "120/80": they are two measurements, they
        # trend differently, and a string cannot be averaged or correlated.
        sources=("apple_health",),
        aliases=("systolic",),
        plausible_min=50,
        plausible_max=260,
        precision=0,
    ),
    MetricDefinition(
        key="blood_pressure_diastolic",
        unit=MetricUnit.MMHG,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Blutdruck diastolisch",
        label_en="Blood pressure, diastolic",
        sources=("apple_health",),
        aliases=("diastolic",),
        plausible_min=30,
        plausible_max=180,
        precision=0,
    ),
    MetricDefinition(
        key="heart_rate",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Puls",
        label_en="Heart rate",
        sources=("apple_health",),
        plausible_min=20,
        plausible_max=250,
        precision=0,
        cadence=Cadence.CONTINUOUS,
        # Second, not minute. A minute mean is the wrong summary of the one span
        # where the pulse actually moves: an interval session averages to a flat
        # line that no reading of it can undo. The cost is bounded by the device —
        # a watch sends every few seconds under load and every few minutes at
        # rest, so this preserves the workout and adds nothing to the idle hours.
        ingest_resolution=IngestResolution.SECOND,
    ),
    MetricDefinition(
        key="heart_rate_average",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Durchschnittspuls (Tag)",
        label_en="Average heart rate (day)",
        sources=("whoop",),
        aliases=("cycle_average_heart_rate",),
        plausible_min=20,
        plausible_max=200,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="heart_rate_max",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.MAX,
        category=MetricCategory.HEART,
        label_de="Maximalpuls (Tag)",
        label_en="Maximum heart rate (day)",
        sources=("whoop",),
        aliases=("max_heart_rate",),
        plausible_min=20,
        plausible_max=250,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="heart_rate_resting",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Ruhepuls",
        label_en="Resting heart rate",
        sources=("apple_health", "whoop"),
        aliases=("resting_heart_rate", "resting_hr", "resting_heart_rate_bpm"),
        plausible_min=25,
        plausible_max=120,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="heart_rate_walking_average",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Gehpuls (Durchschnitt)",
        label_en="Walking heart rate average",
        sources=("apple_health",),
        aliases=("walking_heart_rate_average",),
        plausible_min=40,
        plausible_max=200,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="heart_rate_recovery",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Herzfrequenz-Erholung",
        label_en="Heart-rate recovery",
        sources=("apple_health",),
        aliases=("heart_rate_recovery_one_minute",),
        plausible_min=0,
        plausible_max=200,
        precision=0,
    ),
    MetricDefinition(
        key="hrv_rmssd",
        unit=MetricUnit.MILLISECOND,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        # RMSSD and SDNN are different computations over the same RR intervals and are
        # not interchangeable, so they stay two metrics rather than one "hrv".
        label_de="HRV (RMSSD)",
        label_en="HRV (RMSSD)",
        sources=("whoop",),
        aliases=("hrv_rmssd_milli",),
        plausible_min=1,
        plausible_max=300,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="hrv_sdnn",
        unit=MetricUnit.MILLISECOND,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="HRV (SDNN)",
        label_en="HRV (SDNN)",
        sources=("apple_health",),
        aliases=("heart_rate_variability_sdnn", "hrv"),
        plausible_min=1,
        plausible_max=300,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="blood_oxygen",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Sauerstoffsättigung",
        label_en="Blood oxygen",
        sources=("apple_health", "whoop"),
        aliases=("spo2_percentage", "spo2", "oxygen_saturation"),
        plausible_min=50,
        plausible_max=100,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="respiratory_rate",
        unit=MetricUnit.BREATHS_PER_MINUTE,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.HEART,
        label_de="Atemfrequenz",
        label_en="Respiratory rate",
        sources=("apple_health", "whoop"),
        plausible_min=4,
        plausible_max=60,
        precision=1,
        cadence=Cadence.DAILY,
        ingest_resolution=IngestResolution.MINUTE,
    ),
    # ── Sleep ─────────────────────────────────────────────────────────────────
    MetricDefinition(
        key="sleep_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Schlafdauer",
        label_en="Sleep duration",
        sources=("apple_health", "whoop"),
        aliases=("sleep_analysis", "sleep", "sleep_duration_hours", "sleep_asleep_duration"),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_duration_deep",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Tiefschlaf",
        label_en="Deep sleep",
        sources=("apple_health", "whoop"),
        aliases=("sleep_deep_duration",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_duration_rem",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="REM-Schlaf",
        label_en="REM sleep",
        sources=("apple_health", "whoop"),
        aliases=("sleep_rem_duration",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_duration_light",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        # Apple calls this stage "Core"; every other vendor calls it light sleep.
        label_de="Leichtschlaf",
        label_en="Light sleep",
        sources=("apple_health", "whoop"),
        aliases=("sleep_core_duration", "sleep_light_duration"),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_duration_awake",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Wachzeit",
        label_en="Awake time",
        sources=("apple_health", "whoop"),
        aliases=("sleep_awake_duration",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_duration_in_bed",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Zeit im Bett",
        label_en="Time in bed",
        sources=("apple_health", "whoop"),
        aliases=("sleep_inbed_duration", "sleep_in_bed_duration"),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_efficiency",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Schlafeffizienz",
        label_en="Sleep efficiency",
        sources=("whoop",),
        aliases=("sleep_efficiency_percentage",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    # These are WHOOP's own sleep-planning figures. They are useful as series, but
    # are not interchangeable with a sleep duration or a vendor-independent score.
    MetricDefinition(
        key="whoop_sleep_need",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Whoop-Schlafbedarf",
        label_en="WHOOP sleep need",
        sources=("whoop",),
        aliases=("sleep_need_minutes",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="whoop_sleep_debt",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Whoop-Schlafdefizit",
        label_en="WHOOP sleep debt",
        sources=("whoop",),
        aliases=("sleep_debt_minutes",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="whoop_sleep_consistency",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Whoop-Schlafbeständigkeit",
        label_en="WHOOP sleep consistency",
        sources=("whoop",),
        aliases=("sleep_consistency_percentage",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="sleep_nap_count",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Nickerchen",
        label_en="Naps",
        sources=("whoop",),
        aliases=("naps",),
        plausible_min=0,
        plausible_max=50,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="whoop_sleep_performance",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Whoop Sleep Performance",
        label_en="Whoop sleep performance",
        sources=("whoop",),
        aliases=("sleep_performance_percentage", "whoop_sleep_performance_percent"),
        plausible_min=0,
        plausible_max=100,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="whoop_recovery_score",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Whoop Recovery",
        label_en="Whoop recovery",
        sources=("whoop",),
        aliases=("recovery_score",),
        plausible_min=0,
        plausible_max=100,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    # Oura reaches the platform as a CSV through the dashboard's visual mapper rather
    # than as an importer, but its columns still need somewhere to land -- and its
    # scores are vendor composites like WHOOP's, so they are prefixed for the same
    # reason: a "sleep score" is only comparable to another Oura sleep score.
    MetricDefinition(
        key="oura_sleep_score",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Oura Sleep Score",
        label_en="Oura sleep score",
        sources=("oura",),
        aliases=("sleep_score",),
        plausible_min=0,
        plausible_max=100,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="oura_readiness_score",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.SLEEP,
        label_de="Oura Readiness Score",
        label_en="Oura readiness score",
        sources=("oura",),
        aliases=("readiness_score",),
        plausible_min=0,
        plausible_max=100,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="oura_activity_score",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ACTIVITY,
        label_de="Oura Activity Score",
        label_en="Oura activity score",
        sources=("oura",),
        aliases=("activity_score",),
        plausible_min=0,
        plausible_max=100,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    # ── Body ──────────────────────────────────────────────────────────────────
    MetricDefinition(
        key="body_weight",
        unit=MetricUnit.KILOGRAM,
        aggregation=Aggregation.LAST,
        category=MetricCategory.BODY,
        label_de="Körpergewicht",
        label_en="Body weight",
        sources=("apple_health",),
        aliases=("body_mass", "weight"),
        plausible_min=20,
        plausible_max=400,
        precision=1,
    ),
    MetricDefinition(
        key="body_fat",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.LAST,
        category=MetricCategory.BODY,
        label_de="Körperfettanteil",
        label_en="Body fat",
        sources=("apple_health",),
        aliases=("body_fat_percentage",),
        plausible_min=1,
        plausible_max=70,
        precision=1,
    ),
    MetricDefinition(
        key="body_height",
        unit=MetricUnit.METER,
        aggregation=Aggregation.LAST,
        category=MetricCategory.BODY,
        label_de="Körpergröße",
        label_en="Body height",
        sources=("apple_health",),
        aliases=("height",),
        plausible_min=0.5,
        plausible_max=2.7,
        precision=2,
    ),
    MetricDefinition(
        key="body_mass_index",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.LAST,
        category=MetricCategory.BODY,
        label_de="Body-Mass-Index",
        label_en="Body mass index",
        sources=("apple_health",),
        aliases=("bmi",),
        plausible_min=5,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="lean_body_mass",
        unit=MetricUnit.KILOGRAM,
        aggregation=Aggregation.LAST,
        category=MetricCategory.BODY,
        label_de="Magere Körpermasse",
        label_en="Lean body mass",
        sources=("apple_health",),
        aliases=("lean_body_mass_kg",),
        plausible_min=1,
        plausible_max=300,
        precision=1,
    ),
    MetricDefinition(
        key="vo2_max",
        unit=MetricUnit.ML_PER_KG_PER_MIN,
        aggregation=Aggregation.LAST,
        category=MetricCategory.BODY,
        label_de="VO2max",
        label_en="VO2 max",
        sources=("apple_health",),
        plausible_min=10,
        plausible_max=95,
        precision=1,
    ),
    MetricDefinition(
        key="skin_temperature",
        unit=MetricUnit.CELSIUS,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.BODY,
        label_de="Hauttemperatur",
        label_en="Skin temperature",
        sources=("whoop",),
        aliases=("skin_temp_celsius",),
        plausible_min=20,
        plausible_max=45,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    # ── Nutrition ─────────────────────────────────────────────────────────────
    MetricDefinition(
        key="nutrition_energy",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        # Apple Health's dietary energy and Yazio's daily total are the same quantity;
        # they were `calories_consumed` and `calories` before this catalog existed.
        label_de="Kalorien",
        label_en="Calories",
        sources=("yazio", "apple_health"),
        aliases=(
            "calories",
            "yazio_calories",
            "calories_consumed",
            "dietary_energy_consumed",
            "nutrition_calories_kcal",
        ),
        plausible_min=0,
        plausible_max=20_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_protein",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Protein",
        label_en="Protein",
        sources=("yazio", "apple_health"),
        aliases=(
            "protein",
            "yazio_protein",
            "nutrition_protein_g",
            "dietary_protein",
        ),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_carbohydrates",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Kohlenhydrate",
        label_en="Carbohydrates",
        sources=("yazio", "apple_health"),
        aliases=(
            "carbohydrates",
            "carbs",
            "yazio_carbs",
            "nutrition_carbs_g",
            "dietary_carbohydrates",
        ),
        plausible_min=0,
        plausible_max=2_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_fat",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Fett",
        label_en="Fat",
        sources=("yazio", "apple_health"),
        aliases=("fat", "yazio_fat", "nutrition_fat_g", "dietary_fat_total"),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_fiber",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Ballaststoffe",
        label_en="Fibre",
        sources=("yazio", "apple_health"),
        aliases=("fiber", "yazio_fiber", "nutrition_fiber_g", "dietary_fiber"),
        plausible_min=0,
        plausible_max=500,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_sugar",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Zucker",
        label_en="Sugar",
        sources=("apple_health",),
        aliases=("dietary_sugar",),
        plausible_min=0,
        plausible_max=2_000,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_sodium",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Natrium",
        label_en="Sodium",
        sources=("apple_health",),
        aliases=("dietary_sodium",),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_fat_saturated",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Gesättigte Fettsäuren",
        label_en="Saturated fat",
        sources=("apple_health",),
        aliases=("dietary_fat_saturated",),
        plausible_min=0,
        plausible_max=1_000,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_fat_monounsaturated",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Einfach ungesättigte Fettsäuren",
        label_en="Monounsaturated fat",
        sources=("apple_health",),
        aliases=("dietary_fat_monounsaturated",),
        plausible_min=0,
        plausible_max=1_000,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_fat_polyunsaturated",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Mehrfach ungesättigte Fettsäuren",
        label_en="Polyunsaturated fat",
        sources=("apple_health",),
        aliases=("dietary_fat_polyunsaturated",),
        plausible_min=0,
        plausible_max=1_000,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_potassium",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Kalium",
        label_en="Potassium",
        sources=("apple_health",),
        aliases=("dietary_potassium",),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_cholesterol",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Cholesterin",
        label_en="Cholesterol",
        sources=("apple_health",),
        aliases=("dietary_cholesterol",),
        plausible_min=0,
        plausible_max=20_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_calcium",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Kalzium",
        label_en="Calcium",
        sources=("apple_health",),
        aliases=("dietary_calcium",),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_vitamin_c_intake",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Vitamin C",
        label_en="Vitamin C",
        sources=("apple_health",),
        aliases=("dietary_vitamin_c",),
        plausible_min=0,
        plausible_max=10_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_iron",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Eisen",
        label_en="Iron",
        sources=("apple_health",),
        aliases=("dietary_iron",),
        plausible_min=0,
        plausible_max=10_000,
        precision=1,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_caffeine",
        unit=MetricUnit.MILLIGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Koffein",
        label_en="Caffeine",
        sources=("apple_health",),
        aliases=("dietary_caffeine",),
        plausible_min=0,
        plausible_max=10_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="water_intake",
        unit=MetricUnit.MILLILITER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Wasseraufnahme",
        label_en="Water intake",
        sources=("apple_health",),
        aliases=("dietary_water", "water_consumed"),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="nutrition_meal_energy",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        # Replaces the interpolated `f"{meal_category}_calories"`, which minted a new
        # metric name for every meal label a provider happened to use. The meal is a
        # property of the reading, so it belongs in metadata["meal_category"].
        label_de="Kalorien je Mahlzeit",
        label_en="Calories per meal",
        sources=("yazio",),
        plausible_min=0,
        plausible_max=20_000,
        precision=0,
    ),
    MetricDefinition(
        key="nutrition_item_energy",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Kalorien je Eintrag",
        label_en="Calories per item",
        sources=("yazio",),
        aliases=("consumed_item_calories",),
        plausible_min=0,
        plausible_max=20_000,
        precision=0,
    ),
    MetricDefinition(
        key="nutrition_item_amount",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        # The logged portion of an item whose calories the provider did not give us.
        # It used to share `consumed_product` with the calorie metric, so one series
        # mixed grams and kilocalories.
        label_de="Menge je Eintrag",
        label_en="Amount per item",
        sources=("yazio",),
        aliases=("consumed_product",),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
    ),
    MetricDefinition(
        key="nutrition_recipe_portions",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Rezeptportionen",
        label_en="Recipe portions",
        sources=("yazio",),
        aliases=("consumed_recipe_portion",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    # ── Workout (cardio sessions) ─────────────────────────────────────────────
    MetricDefinition(
        key="workout_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Trainingsdauer",
        label_en="Workout duration",
        sources=("apple_health", "whoop"),
        aliases=("whoop_workout_duration_minutes",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="workout_distance",
        unit=MetricUnit.KILOMETER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Trainingsdistanz",
        label_en="Workout distance",
        sources=("apple_health", "whoop"),
        aliases=("workout_distance_meter",),
        plausible_min=0,
        plausible_max=500,
        precision=2,
    ),
    MetricDefinition(
        key="workout_energy",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Trainingsenergie",
        label_en="Workout energy",
        sources=("apple_health", "whoop"),
        aliases=("workout_active_energy", "workout_kilojoule"),
        plausible_min=0,
        plausible_max=15_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_energy_resting",
        unit=MetricUnit.KCAL,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Trainings-Grundumsatz",
        label_en="Workout resting energy",
        sources=("apple_health",),
        aliases=("workout_basal_energy_burned",),
        plausible_min=0,
        plausible_max=5_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_heart_rate_average",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls (Durchschnitt)",
        label_en="Workout heart rate (average)",
        sources=("apple_health", "whoop"),
        aliases=("workout_avg_heart_rate", "workout_average_heart_rate"),
        plausible_min=40,
        plausible_max=230,
        precision=0,
    ),
    # The series the two figures above summarise. Health Auto Export sends a
    # workout's `heartRateData` as an array of samples, and until now that array
    # was collapsed to a mean and a max and then discarded -- which is the whole
    # of what a workout's pulse looked like from the outside.
    #
    # Keyed apart from `heart_rate` even though both are bpm, and that is a rule 15
    # judgement rather than an oversight. Apple sends `metrics[].heart_rate`
    # (interval summaries) *and* `workouts[].heartRateData` (per sample) covering
    # overlapping wall-clock time in separate pushes. Under one name they interleave
    # without aligning, so `sample_count` and the min/max envelope stop meaning
    # anything, and the two cannot be given different retention. Session twins are
    # already keyed apart here for exactly this reason -- see `workout_steps`.
    MetricDefinition(
        key="workout_heart_rate",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls (Verlauf)",
        label_en="Workout heart rate (series)",
        sources=("apple_health",),
        plausible_min=20,
        plausible_max=250,
        precision=0,
        cadence=Cadence.CONTINUOUS,
        # Second rather than raw: a predictable ceiling of 3,600 points an hour,
        # and it routes every sample through the bucket path so it carries
        # `bucket_min`/`bucket_max`/`sample_count` like everything else.
        ingest_resolution=IngestResolution.SECOND,
        # A year, not forever: this is the one genuinely large series here, and
        # its mean and max survive permanently in the two metrics above.
        raw_retention_days=365,
    ),
    MetricDefinition(
        key="workout_heart_rate_max",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.MAX,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls (Maximum)",
        label_en="Workout heart rate (max)",
        sources=("apple_health", "whoop"),
        aliases=("workout_max_heart_rate",),
        plausible_min=40,
        plausible_max=240,
        precision=0,
    ),
    MetricDefinition(
        key="workout_heart_rate_zone_1",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls Zone 1",
        label_en="Workout heart-rate zone 1",
        sources=("whoop",),
        aliases=("heart_rate_zone_1",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="workout_heart_rate_zone_2",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls Zone 2",
        label_en="Workout heart-rate zone 2",
        sources=("whoop",),
        aliases=("heart_rate_zone_2",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="workout_heart_rate_zone_3",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls Zone 3",
        label_en="Workout heart-rate zone 3",
        sources=("whoop",),
        aliases=("heart_rate_zone_3",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="workout_heart_rate_zone_4",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls Zone 4",
        label_en="Workout heart-rate zone 4",
        sources=("whoop",),
        aliases=("heart_rate_zone_4",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    MetricDefinition(
        key="workout_heart_rate_zone_5",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls Zone 5",
        label_en="Workout heart-rate zone 5",
        sources=("whoop",),
        aliases=("heart_rate_zone_5",),
        plausible_min=0,
        plausible_max=100,
        precision=1,
    ),
    # Quantities a workout states about itself that the daily metrics do not hold. Each
    # is a session aggregate, keyed apart from its daily counterpart on purpose: a
    # workout's steps under `steps` would be added to a day that already counts them.
    MetricDefinition(
        key="workout_steps",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Schritte (Training)",
        label_en="Steps (workout)",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=200_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_speed_average",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Geschwindigkeit (Durchschnitt)",
        label_en="Speed (average)",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=120,
        precision=1,
    ),
    MetricDefinition(
        key="workout_speed_max",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.MAX,
        category=MetricCategory.WORKOUT,
        label_de="Geschwindigkeit (Maximum)",
        label_en="Speed (max)",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=200,
        precision=1,
    ),
    MetricDefinition(
        key="workout_cadence",
        unit=MetricUnit.STEPS_PER_MINUTE,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Schrittfrequenz",
        label_en="Cadence",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=300,
        precision=0,
    ),
    MetricDefinition(
        key="workout_cycling_cadence",
        unit=MetricUnit.REVOLUTIONS_PER_MINUTE,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Trittfrequenz (Radfahren)",
        label_en="Cycling cadence",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=250,
        precision=0,
    ),
    MetricDefinition(
        key="workout_cycling_power",
        unit=MetricUnit.WATT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Leistung (Radfahren)",
        label_en="Cycling power",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=2_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_elevation_gain",
        unit=MetricUnit.METER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Höhenmeter (Aufstieg)",
        label_en="Elevation gain",
        # WHOOP sends `altitude_gain_meter` on every v2 workout and it was simply
        # never read.
        sources=("apple_health", "whoop"),
        plausible_min=0,
        plausible_max=15_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_elevation_loss",
        unit=MetricUnit.METER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Höhenmeter (Abstieg)",
        label_en="Elevation loss",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=15_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_lap_length",
        unit=MetricUnit.METER,
        aggregation=Aggregation.LAST,
        category=MetricCategory.WORKOUT,
        label_de="Bahnlänge",
        label_en="Lap length",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=10_000,
        precision=1,
    ),
    MetricDefinition(
        key="workout_swim_cadence",
        unit=MetricUnit.STEPS_PER_MINUTE,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Schlagfrequenz (Schwimmen)",
        label_en="Swim cadence",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=200,
        precision=0,
    ),
    MetricDefinition(
        key="workout_swimming_strokes",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.WORKOUT,
        label_de="Schwimmzüge",
        label_en="Swimming strokes",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=100_000,
        precision=0,
    ),
    MetricDefinition(
        key="workout_intensity",
        unit=MetricUnit.MET,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.WORKOUT,
        label_de="Intensität",
        label_en="Intensity",
        sources=("apple_health",),
        plausible_min=0,
        plausible_max=30,
        precision=1,
    ),
    MetricDefinition(
        key="whoop_workout_strain",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.MAX,
        category=MetricCategory.WORKOUT,
        label_de="Whoop Strain (Training)",
        label_en="Whoop strain (workout)",
        sources=("whoop",),
        aliases=("workout_strain",),
        plausible_min=0,
        plausible_max=21,
        precision=1,
    ),
    # ── Strength training ─────────────────────────────────────────────────────
    #
    # Kept apart from `workout_*`: those are cardio-session aggregates, these are
    # resistance-training sets. Sharing the prefix made `workout_set_heart_rate_max`
    # look like a variant of `workout_heart_rate_max`, which it is not.
    MetricDefinition(
        key="strength_set_weight",
        unit=MetricUnit.KILOGRAM,
        aggregation=Aggregation.MAX,
        category=MetricCategory.STRENGTH,
        label_de="Satzgewicht",
        label_en="Set weight",
        sources=("streak",),
        aliases=("workout_set_weight_kg",),
        plausible_min=0,
        plausible_max=1_000,
        precision=1,
    ),
    MetricDefinition(
        key="strength_set_reps",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.STRENGTH,
        label_de="Wiederholungen",
        label_en="Repetitions",
        sources=("streak",),
        aliases=("workout_set_reps",),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
    ),
    MetricDefinition(
        key="strength_set_volume",
        unit=MetricUnit.KILOGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.STRENGTH,
        label_de="Satzvolumen",
        label_en="Set volume",
        sources=("streak",),
        aliases=("workout_set_volume",),
        plausible_min=0,
        plausible_max=100_000,
        precision=1,
    ),
    MetricDefinition(
        key="strength_set_heart_rate_max",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.MAX,
        category=MetricCategory.STRENGTH,
        label_de="Maximalpuls im Satz",
        label_en="Set peak heart rate",
        sources=("streak",),
        aliases=("workout_set_heart_rate_max",),
        plausible_min=40,
        plausible_max=240,
        precision=0,
    ),
    MetricDefinition(
        key="strength_session_volume",
        unit=MetricUnit.KILOGRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.STRENGTH,
        label_de="Trainingsvolumen",
        label_en="Session volume",
        sources=("streak",),
        aliases=("workout_total_volume",),
        plausible_min=0,
        plausible_max=1_000_000,
        precision=0,
    ),
    MetricDefinition(
        key="strength_session_sets",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.STRENGTH,
        label_de="Sätze",
        label_en="Sets",
        sources=("streak",),
        aliases=("workout_total_sets",),
        plausible_min=0,
        plausible_max=500,
        precision=0,
    ),
    # ── Location ──────────────────────────────────────────────────────────────
    MetricDefinition(
        key="location_point",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.LOCATION,
        label_de="Standortpunkte",
        label_en="Location points",
        # A route from a phone and a trace from Dawarich are the same quantity, so
        # they share a name (rule 15).
        sources=("dawarich", "apple_health"),
        plausible_min=0,
        plausible_max=1,
        precision=0,
    ),
    MetricDefinition(
        key="location_latitude",
        unit=MetricUnit.DEGREE,
        aggregation=Aggregation.LAST,
        category=MetricCategory.LOCATION,
        label_de="Breitengrad",
        label_en="Latitude",
        sources=("dawarich",),
        plausible_min=-90,
        plausible_max=90,
        precision=6,
    ),
    MetricDefinition(
        key="location_longitude",
        unit=MetricUnit.DEGREE,
        aggregation=Aggregation.LAST,
        category=MetricCategory.LOCATION,
        label_de="Längengrad",
        label_en="Longitude",
        sources=("dawarich",),
        plausible_min=-180,
        plausible_max=180,
        precision=6,
    ),
    # ── Calendar ──────────────────────────────────────────────────────────────
    MetricDefinition(
        key="calendar_event_count",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.CALENDAR,
        label_de="Termine",
        label_en="Calendar events",
        sources=("calendar",),
        plausible_min=0,
        plausible_max=200,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="calendar_busy_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.CALENDAR,
        # `calendar_busy_hours` is deliberately *not* an alias: it carried the same
        # quantity in a different unit, and mapping it here would mean 8 hours and
        # 8 minutes landing in one series. The importer no longer emits it.
        label_de="Belegte Zeit",
        label_en="Busy time",
        sources=("calendar",),
        aliases=("calendar_busy_minutes",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="calendar_meeting_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.CALENDAR,
        label_de="Termindauer",
        label_en="Meeting duration",
        sources=("calendar",),
        aliases=("calendar_meeting_duration_minutes",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    # ── Developer activity ────────────────────────────────────────────────────
    #
    # `code_`, not `github_`. A commit is a commit whether GitHub, GitLab or a
    # self-hosted forge reported it, and rule 15 is explicit that a name states what
    # was measured and never who measured it. The forge travels in `metadata`, and
    # `resolve_primary_source` is what settles it if two of them ever report the same
    # day — the same machinery that already settles two watches reporting `steps`.
    #
    # Per-repository series are deliberately *not* here: which repositories exist is
    # a property of one person's account, not of the platform, so they go under the
    # `github_` namespace below exactly as Home Assistant's entities do.
    MetricDefinition(
        key="code_commits",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Commits",
        label_en="Commits",
        sources=("github",),
        plausible_min=0,
        plausible_max=2_000,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_lines_added",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Hinzugefügte Zeilen",
        label_en="Lines added",
        sources=("github",),
        # No upper bound worth defending. A single commit that vendors a dependency
        # or checks in a generated lockfile is legitimately hundreds of thousands of
        # lines, and a plausibility ceiling here would flag real days as suspect.
        plausible_min=0,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_lines_removed",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Entfernte Zeilen",
        label_en="Lines removed",
        sources=("github",),
        plausible_min=0,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_repositories_touched",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.MAX,
        category=MetricCategory.DEVELOPER,
        label_de="Bearbeitete Repositories",
        label_en="Repositories touched",
        sources=("github",),
        # `MAX`, not `SUM`. This is a count of *distinct* repositories in a day, and
        # adding two days' distinct counts together answers a question nobody asked:
        # a week of touching the same repository daily would report seven.
        plausible_min=0,
        plausible_max=200,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_pull_requests_opened",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Geöffnete Pull Requests",
        label_en="Pull requests opened",
        sources=("github",),
        plausible_min=0,
        plausible_max=200,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_pull_requests_merged",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Gemergte Pull Requests",
        label_en="Pull requests merged",
        sources=("github",),
        plausible_min=0,
        plausible_max=200,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_reviews_submitted",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Abgegebene Reviews",
        label_en="Reviews submitted",
        sources=("github",),
        plausible_min=0,
        plausible_max=500,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_issues_opened",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.SUM,
        category=MetricCategory.DEVELOPER,
        label_de="Geöffnete Issues",
        label_en="Issues opened",
        sources=("github",),
        plausible_min=0,
        plausible_max=500,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    # No `code_issues_closed`. GitHub's contribution collection reports issues
    # *opened* per day and nothing equivalent for closing one — the closest is a
    # search query, which answers a whole range rather than a day and cannot
    # distinguish "closed by me" from "assigned to me". A registered `DAILY` metric
    # that nothing ever writes is worse than an absent one: the gap scan would
    # report a permanent, unfixable gap for every day of the workspace's history.
    MetricDefinition(
        key="code_contribution_streak",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.LAST,
        category=MetricCategory.DEVELOPER,
        label_de="Aktuelle Serie",
        label_en="Current streak",
        sources=("github",),
        # `LAST`, because a streak is a standing figure like body weight: the number
        # today, not a total of the numbers so far.
        plausible_min=0,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_followers",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.LAST,
        category=MetricCategory.DEVELOPER,
        label_de="Follower",
        label_en="Followers",
        sources=("github",),
        plausible_min=0,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    MetricDefinition(
        key="code_stars_received",
        unit=MetricUnit.COUNT,
        aggregation=Aggregation.LAST,
        category=MetricCategory.DEVELOPER,
        label_de="Sterne insgesamt",
        label_en="Stars received",
        sources=("github",),
        # The standing total across the account's own repositories, so `LAST` for the
        # same reason as `code_followers`. A day's *change* is a question the analysis
        # can ask of a `LAST` series; a `SUM` here would make it unanswerable.
        plausible_min=0,
        precision=0,
        cadence=Cadence.DAILY,
    ),
    # ── Environment ───────────────────────────────────────────────────────────
    MetricDefinition(
        key="weather_temperature",
        unit=MetricUnit.CELSIUS,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Außentemperatur",
        label_en="Outdoor temperature",
        sources=("weather",),
        aliases=("weather_temperature_c",),
        plausible_min=-70,
        plausible_max=60,
        precision=1,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_temperature_apparent",
        unit=MetricUnit.CELSIUS,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Gefühlte Temperatur",
        label_en="Apparent temperature",
        sources=("weather",),
        aliases=("weather_apparent_temperature_c",),
        plausible_min=-80,
        plausible_max=70,
        precision=1,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_humidity",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Luftfeuchtigkeit",
        label_en="Humidity",
        sources=("weather",),
        aliases=("weather_humidity_pct",),
        plausible_min=0,
        plausible_max=100,
        precision=0,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_precipitation",
        unit=MetricUnit.MILLIMETER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ENVIRONMENT,
        label_de="Niederschlag",
        label_en="Precipitation",
        sources=("weather",),
        aliases=("weather_precipitation_mm",),
        plausible_min=0,
        plausible_max=500,
        precision=1,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_pressure",
        unit=MetricUnit.HECTOPASCAL,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Luftdruck",
        label_en="Air pressure",
        sources=("weather",),
        aliases=("weather_pressure_hpa",),
        plausible_min=800,
        plausible_max=1_100,
        precision=0,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_wind_speed",
        unit=MetricUnit.KILOMETER_PER_HOUR,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Windgeschwindigkeit",
        label_en="Wind speed",
        sources=("weather",),
        aliases=("weather_wind_speed_kmh",),
        plausible_min=0,
        plausible_max=500,
        precision=1,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_cloud_cover",
        unit=MetricUnit.PERCENT,
        aggregation=Aggregation.AVERAGE,
        category=MetricCategory.ENVIRONMENT,
        label_de="Bewölkung",
        label_en="Cloud cover",
        sources=("weather",),
        aliases=("weather_cloud_cover_pct",),
        plausible_min=0,
        plausible_max=100,
        precision=0,
        cadence=Cadence.CONTINUOUS,
    ),
    MetricDefinition(
        key="weather_uv_index",
        unit=MetricUnit.INDEX,
        aggregation=Aggregation.MAX,
        category=MetricCategory.ENVIRONMENT,
        label_de="UV-Index",
        label_en="UV index",
        sources=("weather",),
        plausible_min=0,
        plausible_max=20,
        precision=1,
        cadence=Cadence.CONTINUOUS,
    ),
)


#: Every catalogued metric, keyed by its canonical name.
METRIC_CATALOG: dict[str, MetricDefinition] = {d.key: d for d in _DEFINITIONS}

#: Canonical names, in catalog order.
CANONICAL_KEYS: tuple[str, ...] = tuple(METRIC_CATALOG)


#: Prefixes under which unregistered names are legal. See :class:`MetricNamespace`.
DYNAMIC_NAMESPACES: tuple[MetricNamespace, ...] = (
    MetricNamespace(
        prefix="home_assistant_",
        category=MetricCategory.HOME,
        label_de="Home Assistant",
        label_en="Home Assistant",
        sources=("home_assistant",),
    ),
    MetricNamespace(
        prefix="apple_health_",
        category=MetricCategory.ACTIVITY,
        # Health Auto Export ships whatever HealthKit types the phone has recorded.
        # Anything not in the catalog lands here rather than claiming a bare name.
        label_de="Apple Health (nicht katalogisiert)",
        label_en="Apple Health (uncatalogued)",
        sources=("apple_health",),
    ),
    MetricNamespace(
        prefix="github_",
        category=MetricCategory.DEVELOPER,
        # Per-repository series. Which repositories exist is a property of one
        # person's account, not of the platform, so cataloguing them is not possible
        # and inventing bare names for them would break rule 15 twice over — the name
        # would carry the forge *and* be unregistered.
        #
        # The account-wide totals are catalogued as `code_*` instead; this namespace
        # is only ever the breakdown beneath them.
        label_de="GitHub (pro Repository)",
        label_en="GitHub (per repository)",
        sources=("github",),
    ),
    MetricNamespace(
        prefix="custom_",
        category=MetricCategory.CUSTOM,
        label_de="Eigene Metrik",
        label_en="Custom metric",
    ),
)


def _build_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for definition in _DEFINITIONS:
        for alias in definition.aliases:
            if alias in METRIC_CATALOG:
                raise AssertionError(
                    f"Alias {alias!r} on {definition.key!r} is also a canonical key"
                )
            if (owner := index.get(alias)) and owner != definition.key:
                raise AssertionError(
                    f"Alias {alias!r} is claimed by both {owner!r} and {definition.key!r}"
                )
            index[alias] = definition.key
    return index


#: Legacy or provider-specific name -> canonical key. Built at import so a duplicate
#: alias is an ImportError rather than a silently shadowed metric.
METRIC_ALIASES: dict[str, str] = _build_alias_index()


def _namespace_for(name: str) -> MetricNamespace | None:
    for namespace in DYNAMIC_NAMESPACES:
        if name.startswith(namespace.prefix) and len(name) > len(namespace.prefix):
            return namespace
    return None


def canonical_metric_type(raw: str) -> str:
    """Return the canonical name for ``raw``, or raise.

    Call this in the transformer *before* deriving the idempotency key — the key is
    ``SHA256(tenant_id + source_id + metric_type + timestamp)`` (AGENTS.md rule 4), so
    canonicalising afterwards would produce a key that does not match the name it is
    stored under.

    :raises UnknownMetricTypeError: if the name is neither catalogued, nor an alias,
        nor inside a dynamic namespace.
    """
    name = (raw or "").strip()
    if name in METRIC_CATALOG:
        return name
    if name in METRIC_ALIASES:
        return METRIC_ALIASES[name]
    if _namespace_for(name) is not None:
        return name
    raise UnknownMetricTypeError(raw)


def resolve(raw: str) -> MetricDefinition | None:
    """Return the catalog entry for ``raw``, or ``None`` if it has none.

    Returns ``None`` both for unknown names and for names inside a dynamic namespace —
    neither has a catalogued unit. Use :func:`describe` when you need something to
    display either way.
    """
    name = (raw or "").strip()
    if name in METRIC_CATALOG:
        return METRIC_CATALOG[name]
    canonical = METRIC_ALIASES.get(name)
    return METRIC_CATALOG[canonical] if canonical else None


def is_known_metric_type(raw: str) -> bool:
    """Whether ``raw`` may be written to the database."""
    try:
        canonical_metric_type(raw)
    except UnknownMetricTypeError:
        return False
    return True


def describe(raw: str) -> MetricDefinition:
    """A definition for ``raw`` suitable for display, synthesising one if needed.

    A namespaced metric gets :attr:`MetricUnit.RUNTIME` and a label derived from the
    part after the prefix, because that is genuinely all that is known about it until
    the event's metadata is read.

    :raises UnknownMetricTypeError: if the name is not writable at all.
    """
    if (definition := resolve(raw)) is not None:
        return definition

    name = (raw or "").strip()
    namespace = _namespace_for(name)
    if namespace is None:
        raise UnknownMetricTypeError(raw)

    readable = name[len(namespace.prefix) :].replace("_", " ").strip().title()
    return MetricDefinition(
        key=name,
        unit=MetricUnit.RUNTIME,
        aggregation=Aggregation.AVERAGE,
        category=namespace.category,
        label_de=readable,
        label_en=readable,
        sources=namespace.sources,
    )


def metrics_for_source(source_type: str) -> tuple[MetricDefinition, ...]:
    """Every catalogued metric a given connector emits, in catalog order."""
    return tuple(d for d in _DEFINITIONS if source_type in d.sources)
