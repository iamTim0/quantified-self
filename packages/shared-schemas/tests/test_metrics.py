"""Tests for the metric registry.

Most of these are invariants on the catalog itself rather than on a function. That is
deliberate: the registry's value is that certain things cannot be true of it at once —
two metrics cannot claim one name, a name cannot mean two units, an alias cannot point
somewhere that no longer exists. A wrong entry is a wrong number in somebody's chart
months later, and only a test catches it at the moment it is written.
"""

import pytest
from pydantic import ValidationError
from shared_schemas.metrics import (
    CANONICAL_KEYS,
    DYNAMIC_NAMESPACES,
    METRIC_ALIASES,
    METRIC_CATALOG,
    Aggregation,
    MetricUnit,
    UnknownMetricTypeError,
    UnsupportedConversionError,
    canonical_metric_type,
    convert,
    describe,
    is_known_metric_type,
    metrics_for_source,
    resolve,
)

# ─── Catalog invariants ───────────────────────────────────────────────────────


def test_every_key_matches_its_entry():
    for key, definition in METRIC_CATALOG.items():
        assert definition.key == key


def test_keys_are_lowercase_snake_case():
    for key in CANONICAL_KEYS:
        assert key == key.lower()
        assert key.replace("_", "").isalnum()
        assert not key.startswith("_") and not key.endswith("_")


def test_no_alias_collides_with_a_canonical_key():
    """An alias that is also a key would make one name mean two metrics."""
    assert not set(METRIC_ALIASES) & set(METRIC_CATALOG)


def test_every_alias_resolves_to_a_real_metric():
    for alias, canonical in METRIC_ALIASES.items():
        assert canonical in METRIC_CATALOG, f"{alias!r} points at missing {canonical!r}"


def test_no_canonical_name_carries_its_unit_as_a_suffix():
    """The rule the registry exists to enforce: the unit is not part of the name.

    `calendar_busy_minutes` and `calendar_busy_hours` were the same quantity stored
    twice because the unit was in the name. Once it is, a unit change silently becomes
    a second metric instead of a conversion.
    """
    unit_suffixes = (
        "_kg", "_g", "_kcal", "_kj", "_ms", "_s", "_min", "_minutes", "_h", "_hours",
        "_m", "_meter", "_km", "_c", "_celsius", "_pct", "_percent", "_percentage",
        "_bpm", "_hpa", "_mm", "_kmh", "_milli",
    )
    offenders = [k for k in CANONICAL_KEYS if k.endswith(unit_suffixes)]
    assert offenders == []


def test_namespaces_do_not_shadow_catalogued_metrics():
    """A catalogued key starting with a namespace prefix would be ambiguous."""
    for namespace in DYNAMIC_NAMESPACES:
        shadowed = [k for k in CANONICAL_KEYS if k.startswith(namespace.prefix)]
        assert shadowed == [], f"{namespace.prefix!r} shadows {shadowed}"


def test_plausible_ranges_are_ordered_and_labels_present():
    for definition in METRIC_CATALOG.values():
        if definition.plausible_min is not None and definition.plausible_max is not None:
            assert definition.plausible_min < definition.plausible_max, definition.key
        assert definition.label_de.strip(), definition.key
        assert definition.label_en.strip(), definition.key
        assert definition.precision >= 0, definition.key


def test_runtime_unit_is_reserved_for_namespaces():
    """A catalogued metric with no unit would defeat the point of cataloguing it."""
    for definition in METRIC_CATALOG.values():
        assert definition.unit is not MetricUnit.RUNTIME, definition.key


def test_definitions_are_immutable():
    """Frozen so a consumer cannot patch the catalog for itself at runtime."""
    with pytest.raises(ValidationError):
        METRIC_CATALOG["steps"].unit = MetricUnit.KCAL


# ─── The cross-source promise ─────────────────────────────────────────────────


def test_one_quantity_from_two_sources_is_one_metric():
    """The whole point: Apple Health and WHOOP write the same name for one quantity."""
    for key in ("heart_rate_resting", "blood_oxygen", "respiratory_rate"):
        assert {"apple_health", "whoop"} <= set(METRIC_CATALOG[key].sources), key

    for key in ("workout_distance", "workout_energy", "workout_heart_rate_average"):
        assert {"apple_health", "whoop"} <= set(METRIC_CATALOG[key].sources), key

    # Apple Health's dietary energy and Yazio's daily total are also one metric.
    assert {"apple_health", "yazio"} <= set(METRIC_CATALOG["nutrition_energy"].sources)


def test_the_names_that_used_to_disagree_now_resolve_together():
    assert canonical_metric_type("workout_avg_heart_rate") == "workout_heart_rate_average"
    assert canonical_metric_type("workout_average_heart_rate") == "workout_heart_rate_average"
    assert canonical_metric_type("step_count") == "steps"
    assert canonical_metric_type("calories_consumed") == "nutrition_energy"
    assert canonical_metric_type("calories") == "nutrition_energy"


def test_energy_metrics_all_share_one_unit():
    """WHOOP reports kilojoules and Apple Health kilocalories; only one may be stored."""
    for key in ("energy_active", "energy_resting", "energy_total", "workout_energy",
                "nutrition_energy", "nutrition_item_energy", "nutrition_meal_energy"):
        assert METRIC_CATALOG[key].unit is MetricUnit.KCAL, key


def test_hrv_variants_stay_separate():
    """RMSSD and SDNN are different computations, so merging them would be wrong."""
    assert METRIC_CATALOG["hrv_rmssd"].key != METRIC_CATALOG["hrv_sdnn"].key
    assert "hrv_rmssd" not in METRIC_ALIASES
    assert METRIC_ALIASES["hrv"] == "hrv_sdnn"


def test_busy_hours_is_not_an_alias_of_busy_duration():
    """Mapping it would put 8 hours and 8 minutes into one series."""
    assert "calendar_busy_hours" not in METRIC_ALIASES
    assert not is_known_metric_type("calendar_busy_hours")


def test_counters_sum_and_measurements_average():
    assert METRIC_CATALOG["steps"].aggregation is Aggregation.SUM
    assert METRIC_CATALOG["nutrition_energy"].aggregation is Aggregation.SUM
    assert METRIC_CATALOG["heart_rate"].aggregation is Aggregation.AVERAGE
    assert METRIC_CATALOG["body_weight"].aggregation is Aggregation.LAST


# ─── Resolution ───────────────────────────────────────────────────────────────


def test_canonical_name_passes_through_and_alias_resolves():
    assert canonical_metric_type("steps") == "steps"
    assert canonical_metric_type("  steps  ") == "steps"
    assert canonical_metric_type("body_mass") == "body_weight"


def test_unknown_name_is_rejected_with_a_usable_message():
    with pytest.raises(UnknownMetricTypeError) as excinfo:
        canonical_metric_type("kalorien_gestern")
    message = str(excinfo.value)
    assert "kalorien_gestern" in message
    # The error has to say where to go next, or it is just a wall.
    assert "metrics.py" in message
    assert "custom_" in message


@pytest.mark.parametrize("name", ["", "   ", None])
def test_empty_names_are_rejected(name):
    with pytest.raises(UnknownMetricTypeError):
        canonical_metric_type(name)


def test_namespaced_names_are_accepted_but_not_catalogued():
    name = "home_assistant_living_room_temp"
    assert canonical_metric_type(name) == name
    assert resolve(name) is None  # no catalogued unit exists for it

    described = describe(name)
    assert described.unit is MetricUnit.RUNTIME
    assert described.is_dynamic
    assert described.label_de == "Living Room Temp"


def test_a_bare_namespace_prefix_is_not_a_metric():
    """`home_assistant_` alone names no entity."""
    assert not is_known_metric_type("home_assistant_")
    assert not is_known_metric_type("custom_")


def test_describe_rejects_what_canonical_metric_type_rejects():
    with pytest.raises(UnknownMetricTypeError):
        describe("nonsense")


def test_metrics_for_source():
    weather = metrics_for_source("weather")
    assert {d.key for d in weather} == {
        "weather_temperature",
        "weather_temperature_apparent",
        "weather_humidity",
        "weather_precipitation",
        "weather_pressure",
        "weather_wind_speed",
        "weather_cloud_cover",
        "weather_uv_index",
    }
    assert metrics_for_source("does_not_exist") == ()


# ─── Conversion ───────────────────────────────────────────────────────────────


def test_kilojoules_become_kilocalories():
    assert convert(1000.0, MetricUnit.KILOJOULE, MetricUnit.KCAL) == pytest.approx(239.0, abs=0.1)


@pytest.mark.parametrize(
    "value,source,target,expected",
    [
        (5000.0, MetricUnit.METER, MetricUnit.KILOMETER, 5.0),
        (2700.0, MetricUnit.SECOND, MetricUnit.MINUTE, 45.0),
        (8.0, MetricUnit.HOUR, MetricUnit.MINUTE, 480.0),
        (1.0, MetricUnit.MILE, MetricUnit.KILOMETER, 1.609344),
        (10.0, MetricUnit.POUND, MetricUnit.KILOGRAM, 4.5359237),
    ],
)
def test_supported_conversions(value, source, target, expected):
    assert convert(value, source, target) == pytest.approx(expected)


def test_conversion_to_the_same_unit_is_the_identity():
    assert convert(42.5, MetricUnit.KCAL, MetricUnit.KCAL) == 42.5


def test_round_trip_returns_the_original():
    for unit in (MetricUnit.KILOJOULE, MetricUnit.METER, MetricUnit.MILE, MetricUnit.POUND):
        target = {
            MetricUnit.KILOJOULE: MetricUnit.KCAL,
            MetricUnit.METER: MetricUnit.KILOMETER,
            MetricUnit.MILE: MetricUnit.KILOMETER,
            MetricUnit.POUND: MetricUnit.KILOGRAM,
        }[unit]
        assert convert(convert(100.0, unit, target), target, unit) == pytest.approx(100.0)


def test_nonsense_conversion_raises_rather_than_guessing():
    with pytest.raises(UnsupportedConversionError):
        convert(1.0, MetricUnit.GRAM, MetricUnit.METER)
