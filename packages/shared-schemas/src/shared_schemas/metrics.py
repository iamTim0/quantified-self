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

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CANONICAL_KEYS",
    "DYNAMIC_NAMESPACES",
    "METRIC_ALIASES",
    "METRIC_CATALOG",
    "Aggregation",
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
    ``SECOND``, ``HOUR``, ``METER``, ``MILE``, ``POUND``) exist because a *provider*
    reports in them and an importer has to name what it is converting from. Health Auto
    Export, for one, follows the phone's locale, so the same Apple Health metric arrives
    in miles or kilometres depending on whose phone it came from.
    """

    COUNT = "count"
    KCAL = "kcal"
    KILOJOULE = "kJ"
    GRAM = "g"
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
    KILOMETER = "km"
    MILE = "mi"
    CELSIUS = "°C"
    HECTOPASCAL = "hPa"
    MILLIMETER = "mm"
    KILOMETER_PER_HOUR = "km/h"
    DEGREE = "°"
    ML_PER_KG_PER_MIN = "mL/kg/min"
    INDEX = "index"
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
    CUSTOM = "custom"


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
    (MetricUnit.POUND, MetricUnit.KILOGRAM): 0.45359237,
    (MetricUnit.KILOGRAM, MetricUnit.POUND): 1.0 / 0.45359237,
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
    ),
    MetricDefinition(
        key="distance",
        unit=MetricUnit.KILOMETER,
        aggregation=Aggregation.SUM,
        category=MetricCategory.ACTIVITY,
        label_de="Zurückgelegte Distanz",
        label_en="Distance travelled",
        sources=("apple_health",),
        aliases=("distance_walking_running", "walking_running_distance"),
        plausible_min=0,
        plausible_max=500,
        precision=2,
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
    ),
    # ── Heart ─────────────────────────────────────────────────────────────────
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
    ),
    # ── Sleep ─────────────────────────────────────────────────────────────────
    MetricDefinition(
        key="sleep_duration",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Schlafdauer",
        label_en="Sleep duration",
        sources=("apple_health",),
        aliases=("sleep_analysis", "sleep", "sleep_duration_hours", "sleep_asleep_duration"),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="sleep_duration_deep",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Tiefschlaf",
        label_en="Deep sleep",
        sources=("apple_health",),
        aliases=("sleep_deep_duration",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="sleep_duration_rem",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="REM-Schlaf",
        label_en="REM sleep",
        sources=("apple_health",),
        aliases=("sleep_rem_duration",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="sleep_duration_light",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        # Apple calls this stage "Core"; every other vendor calls it light sleep.
        label_de="Leichtschlaf",
        label_en="Light sleep",
        sources=("apple_health",),
        aliases=("sleep_core_duration", "sleep_light_duration"),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="sleep_duration_awake",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Wachzeit",
        label_en="Awake time",
        sources=("apple_health",),
        aliases=("sleep_awake_duration",),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
    ),
    MetricDefinition(
        key="sleep_duration_in_bed",
        unit=MetricUnit.MINUTE,
        aggregation=Aggregation.SUM,
        category=MetricCategory.SLEEP,
        label_de="Zeit im Bett",
        label_en="Time in bed",
        sources=("apple_health",),
        aliases=("sleep_inbed_duration", "sleep_in_bed_duration"),
        plausible_min=0,
        plausible_max=1_440,
        precision=0,
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
    ),
    MetricDefinition(
        key="nutrition_protein",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Protein",
        label_en="Protein",
        sources=("yazio",),
        aliases=("protein", "yazio_protein", "nutrition_protein_g"),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
    ),
    MetricDefinition(
        key="nutrition_carbohydrates",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Kohlenhydrate",
        label_en="Carbohydrates",
        sources=("yazio",),
        aliases=("carbohydrates", "carbs", "yazio_carbs", "nutrition_carbs_g"),
        plausible_min=0,
        plausible_max=2_000,
        precision=0,
    ),
    MetricDefinition(
        key="nutrition_fat",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Fett",
        label_en="Fat",
        sources=("yazio",),
        aliases=("fat", "yazio_fat", "nutrition_fat_g"),
        plausible_min=0,
        plausible_max=1_000,
        precision=0,
    ),
    MetricDefinition(
        key="nutrition_fiber",
        unit=MetricUnit.GRAM,
        aggregation=Aggregation.SUM,
        category=MetricCategory.NUTRITION,
        label_de="Ballaststoffe",
        label_en="Fibre",
        sources=("yazio",),
        aliases=("fiber", "yazio_fiber", "nutrition_fiber_g"),
        plausible_min=0,
        plausible_max=500,
        precision=0,
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
        sources=("apple_health",),
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
    MetricDefinition(
        key="workout_heart_rate_max",
        unit=MetricUnit.BPM,
        aggregation=Aggregation.MAX,
        category=MetricCategory.WORKOUT,
        label_de="Trainingspuls (Maximum)",
        label_en="Workout heart rate (max)",
        sources=("apple_health",),
        aliases=("workout_max_heart_rate",),
        plausible_min=40,
        plausible_max=240,
        precision=0,
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
        sources=("dawarich",),
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
