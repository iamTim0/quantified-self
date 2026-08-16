"""Unit tests for the statistical analyses.

Statistics are easy to get subtly wrong in ways no integration test would catch, so
these check the maths against constructed data with known answers, and check the two
editorial rules the module promises: nothing is phrased causally, and thin data
yields no result rather than a weak one.

Maps to Fizzbee Invariants:
- StrictTenantIsolationOnRead (the endpoint layer; here the pure maths)
"""

import math
from datetime import date, timedelta

import pytest
from analysis.insights import (
    ANALYSIS_VERSION,
    MIN_SAMPLE_FOR_CORRELATION,
    benjamini_hochberg,
    build_daily_series,
    compare_periods,
    correlation_p_value,
    correlation_pairs,
    detect_anomalies,
    lagged_correlations,
    moving_average,
    series_quality,
    strength_label,
    trend_for_metric,
    weekday_pattern,
)

START = date(2026, 5, 1)


def days(n: int, offset: int = 0) -> list[str]:
    return [(START + timedelta(days=i + offset)).isoformat() for i in range(n)]


def series_from(values: list[float], offset: int = 0) -> dict[str, float]:
    return dict(zip(days(len(values), offset), values))


# ─── correlation ─────────────────────────────────────────────


def test_perfect_positive_correlation():
    xs = [float(i) for i in range(20)]
    result = correlation_pairs({"a": series_from(xs), "b": series_from(xs)})

    assert len(result) == 1
    assert result[0]["pearson"] == pytest.approx(1.0)
    assert result[0]["spearman"] == pytest.approx(1.0)
    assert result[0]["direction"] == "positive"
    assert result[0]["strength_pct"] == pytest.approx(100.0)


def test_perfect_negative_correlation():
    xs = [float(i) for i in range(20)]
    result = correlation_pairs({"a": series_from(xs), "b": series_from(xs[::-1])})

    assert result[0]["pearson"] == pytest.approx(-1.0)
    assert result[0]["direction"] == "negative"
    assert result[0]["strength_pct"] == pytest.approx(100.0)


def test_thin_data_produces_no_correlation_at_all():
    """Below the sample floor there is no result, not a weak one.

    A correlation over four days is noise with a number attached; showing it would
    invite exactly the over-reading the module exists to avoid.
    """
    short = [float(i) for i in range(MIN_SAMPLE_FOR_CORRELATION - 1)]
    assert correlation_pairs({"a": series_from(short), "b": series_from(short)}) == []


def test_non_overlapping_series_are_not_correlated():
    """Two metrics measured on different days share no information."""
    a = series_from([float(i) for i in range(20)], offset=0)
    b = series_from([float(i) for i in range(20)], offset=100)
    assert correlation_pairs({"a": a, "b": b}) == []


def test_spearman_survives_an_outlier_that_breaks_pearson():
    """Rank correlation is why both are reported."""
    xs = [float(i) for i in range(20)]
    ys = [float(i) for i in range(19)] + [10_000.0]
    result = correlation_pairs({"a": series_from(xs), "b": series_from(ys)})[0]

    assert result["spearman"] == pytest.approx(1.0)
    assert result["pearson"] < result["spearman"]
    # The headline takes the conservative reading and the gap is flagged.
    assert result["coefficient"] == result["pearson"]
    assert any("outlier" in c for c in result["caveats"])


def test_insignificant_correlation_is_marked_as_such():
    """A weak association over few days must not read as a finding."""
    xs = [1.0, 5.0, 2.0, 8.0, 3.0, 9.0, 4.0, 6.0, 7.0, 2.5, 5.5, 3.5]
    ys = [4.0, 2.0, 9.0, 3.0, 7.0, 1.0, 8.0, 5.0, 2.0, 6.5, 3.0, 8.5]
    result = correlation_pairs({"a": series_from(xs), "b": series_from(ys)})

    if result:  # only asserted when the pair clears the sample floor
        r = result[0]
        if not r["significant"]:
            assert any("not statistically significant" in c for c in r["caveats"])


def test_correlation_never_uses_causal_language():
    """The wording rule is part of the contract, so it is tested."""
    xs = [float(i) for i in range(20)]
    result = correlation_pairs({"a": series_from(xs), "b": series_from(xs)})[0]
    text = result["interpretation"].lower()

    for forbidden in ("causes", "leads to", "makes ", "results in", "affects"):
        assert forbidden not in text, f"causal phrasing leaked: {forbidden}"
    assert "go together" in text


def test_p_value_is_small_for_a_strong_large_sample_correlation():
    assert correlation_p_value(0.9, 50) < 0.001


def test_p_value_is_large_for_a_weak_correlation():
    assert correlation_p_value(0.05, 20) > 0.5


def test_p_value_is_bounded():
    for r in (-1.0, -0.5, 0.0, 0.5, 1.0):
        for n in (3, 10, 100):
            p = correlation_p_value(r, n)
            assert 0.0 <= p <= 1.0, (r, n, p)


def test_benjamini_hochberg_returns_monotone_q_values_in_input_order():
    """Verifies the multiple-testing correction used by correlation_pairs."""
    p_values = [0.04, 0.001, 0.02, 0.8]
    q_values = benjamini_hochberg(p_values)

    assert q_values == pytest.approx([0.053333, 0.004, 0.04, 0.8], abs=1e-5)
    ordered = [
        q_values[index]
        for index, _ in sorted(enumerate(p_values), key=lambda item: item[1])
    ]
    assert ordered == sorted(ordered)


def test_correlation_exposes_bh_q_value_and_adjusted_significance():
    """The raw p-value remains available, but the decision uses the q-value."""
    values = [float(i) for i in range(30)]
    result = correlation_pairs(
        {"steps": series_from(values), "sleep": series_from(values)}
    )[0]

    assert result["multiple_testing_method"] == "benjamini_hochberg"
    assert result["q_value"] == pytest.approx(result["p_value"])
    assert result["interpretation_code"] == "correlation_association"
    assert result["interpretation_params"]["metric_a"] == "sleep"
    assert isinstance(result["caveat_codes"], list)


def test_correlation_caveats_have_stable_codes_and_params():
    """Dashboard localization branches on stable codes, never English prose."""
    xs = [float(i) for i in range(12)]
    ys = [1.0, 2.0, 1.5, 2.5, 2.0, 3.0, 2.7, 3.4, 3.1, 3.8, 3.3, 4.0]

    result = correlation_pairs({"a": series_from(xs), "b": series_from(ys)})[0]

    assert any(item["code"] == "small_overlap" for item in result["caveat_codes"])
    for caveat in result["caveat_codes"]:
        assert set(caveat) == {"code", "params"}
        assert isinstance(caveat["code"], str)
        assert isinstance(caveat["params"], dict)


@pytest.mark.parametrize(
    ("r", "expected"),
    [(0.05, "very weak"), (0.3, "weak"), (0.5, "moderate"), (0.7, "strong"), (0.95, "very strong")],
)
def test_strength_labels(r, expected):
    assert strength_label(r) == expected
    assert strength_label(-r) == expected


# ─── lagged ──────────────────────────────────────────────────


def test_lagged_correlation_finds_a_shifted_relationship():
    """b mirrors a two days later; the lag search should recover exactly that."""
    base = [float(i % 7) for i in range(40)]
    a = series_from(base)
    b = series_from([0.0, 0.0] + base[:-2])

    results = lagged_correlations({"a": a, "b": b})
    match = next((r for r in results if r["metric_a"] == "a" and r["metric_b"] == "b"), None)

    assert match is not None
    assert match["lag_days"] == 2
    assert abs(match["coefficient"]) > 0.9
    assert match["significance_method"] == "unadjusted_exploratory"
    assert match["interpretation_code"] == "lagged_association"


def test_lagged_correlation_states_that_order_is_not_cause():
    base = [float(i % 7) for i in range(40)]
    results = lagged_correlations(
        {"a": series_from(base), "b": series_from([0.0, 0.0] + base[:-2])}
    )
    assert results
    assert "not evidence of a cause" in results[0]["interpretation"]


# ─── trends ──────────────────────────────────────────────────


def test_rising_trend_is_detected():
    values = [float(i) for i in range(30)]
    trend = trend_for_metric(days(30), values)

    assert trend["direction"] == "rising"
    assert trend["slope_per_day"] == pytest.approx(1.0)
    assert trend["r_squared"] == pytest.approx(1.0)


def test_falling_trend_is_detected():
    values = [float(30 - i) for i in range(30)]
    assert trend_for_metric(days(30), values)["direction"] == "falling"


def test_flat_noisy_series_is_reported_as_stable():
    """A slope smaller than the day-to-day noise is not a trend."""
    values = [50.0 + (1.0 if i % 2 else -1.0) for i in range(30)]
    assert trend_for_metric(days(30), values)["direction"] == "flat"


def test_trend_needs_a_minimum_number_of_days():
    assert trend_for_metric(days(3), [1.0, 2.0, 3.0]) is None


def test_moving_average_is_none_until_the_window_is_full():
    ma = moving_average([1.0, 2.0, 3.0, 4.0], window=3)
    assert ma[0] is None and ma[1] is None
    assert ma[2] == pytest.approx(2.0)
    assert ma[3] == pytest.approx(3.0)


# ─── anomalies ───────────────────────────────────────────────


def test_anomaly_detection_flags_an_extreme_day():
    daily = series_from([50.0] * 29 + [500.0])
    result = detect_anomalies(daily)

    assert result is not None
    assert any(a["value"] == 500.0 for a in result["anomalies"])
    assert result["anomalies"][-1]["direction"] == "unusually high"


def test_baseline_is_not_dragged_by_the_outlier_it_should_detect():
    """Median/MAD, not mean/stdev — otherwise the outlier hides itself."""
    daily = series_from([50.0] * 29 + [5000.0])
    result = detect_anomalies(daily)

    assert result["baseline_median"] == pytest.approx(50.0)
    assert result["anomalies"], "a 100x outlier must be detected"


def test_stable_series_has_no_anomalies():
    daily = series_from([50.0 + (i % 3) for i in range(40)])
    result = detect_anomalies(daily)
    assert result["anomalies"] == []


def test_anomaly_detection_needs_enough_history():
    assert detect_anomalies(series_from([1.0, 2.0, 3.0])) is None


# ─── weekday routines ────────────────────────────────────────


def test_weekend_effect_is_detected():
    # 1 May 2026 is a Friday; weekends get a much higher value.
    daily = {}
    for i in range(42):
        d = START + timedelta(days=i)
        daily[d.isoformat()] = 100.0 if d.weekday() >= 5 else 50.0

    pattern = weekday_pattern(daily)
    assert pattern is not None
    assert pattern["weekend_effect"]["difference_pct"] == pytest.approx(100.0, abs=1)
    assert "higher" in pattern["weekend_effect"]["interpretation"]


def test_weekday_pattern_needs_two_weeks():
    assert weekday_pattern(series_from([1.0] * 5)) is None


def test_a_weekday_is_an_identifier_not_a_word():
    """Rule 16 and rule 17: the server names the day, the client says it.

    This field held German words, so an English reader was shown "Montag" and the
    dashboard had no way to say otherwise. It is a code now — lowercase, English,
    stable — and the language is the client's decision.
    """
    daily = {
        (START + timedelta(days=i)).isoformat(): float(i) for i in range(21)
    }
    pattern = weekday_pattern(daily)
    assert pattern is not None

    names = [entry["weekday"] for entry in pattern["per_weekday"]]
    assert names == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ], "Monday first, matching date.weekday()"
    assert all(name == name.lower() and name.isascii() for name in names)


def test_the_weekday_order_follows_the_calendar():
    """The nth entry describes the nth weekday, which is what makes it readable.

    A chart draws these in the order they arrive, so an off-by-one here would put
    Sunday's mean under Monday's label with nothing to give it away.
    """
    # A fortnight starting on a Friday, with one distinctive value on Sundays.
    daily = {}
    for i in range(28):
        day = START + timedelta(days=i)
        daily[day.isoformat()] = 99.0 if day.weekday() == 6 else 1.0

    per_day = {row["weekday"]: row["mean"] for row in weekday_pattern(daily)["per_weekday"]}
    assert per_day["sunday"] == 99.0
    assert set(per_day) - {"sunday"} == {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    }
    assert all(mean == 1.0 for day, mean in per_day.items() if day != "sunday")


# ─── period comparison ───────────────────────────────────────


def test_period_comparison_detects_a_real_shift():
    daily = series_from([10.0] * 20 + [20.0] * 20)
    result = compare_periods(
        daily,
        period_a=(days(1)[0], days(20)[-1]),
        period_b=(days(1, 20)[0], days(20, 20)[-1]),
    )

    assert result is not None
    assert result["difference_pct"] == pytest.approx(100.0)
    # Two perfectly constant windows at different levels are maximally separable.
    assert result["significant"] is True
    # Every comparison must still disclaim causation.
    assert "cause" in result["interpretation"].lower()


def test_period_comparison_reports_no_significance_for_noise():
    daily = series_from([10.0, 11.0, 9.0, 10.5, 9.5] * 8)
    result = compare_periods(
        daily,
        period_a=(days(1)[0], days(20)[-1]),
        period_b=(days(1, 20)[0], days(20, 20)[-1]),
    )
    assert result["significant"] is False


def test_period_comparison_needs_data_in_both_windows():
    daily = series_from([1.0, 2.0, 3.0])
    assert compare_periods(daily, period_a=("2026-01-01", "2026-01-05"), period_b=("2026-02-01", "2026-02-05")) is None


# ─── quality gate and assembly ───────────────────────────────


def test_quality_marks_a_sparse_series_as_insufficient():
    quality = series_quality(series_from([1.0] * 5), window_days=90)
    assert quality["sufficient"] is False
    assert "Too few days" in quality["note"]


def test_quality_accepts_a_dense_series():
    quality = series_quality(series_from([1.0] * 80), window_days=90)
    assert quality["sufficient"] is True
    assert quality["coverage_pct"] > 80


def test_an_event_metric_is_not_excluded_for_being_sparse():
    """Body weight measured 20 times in 90 days is not "too thin" — it is body weight.

    Coverage was measured against the calendar for every metric, so nothing
    event-driven could ever clear 50 %: weight, workouts and calendar metrics were
    permanently excluded from every analysis for having the density they are
    supposed to have.
    """
    quality = series_quality(series_from([80.0] * 20), window_days=90, metric_type="body_weight")

    assert quality["cadence"] == "event"
    assert quality["sufficient"] is True


def test_a_daily_metric_is_still_judged_on_density():
    """The relaxation must not reach the metrics the rule was written for."""
    quality = series_quality(series_from([1.0] * 20), window_days=90, metric_type="steps")

    assert quality["cadence"] == "daily"
    assert quality["sufficient"] is False


def test_the_sample_floor_applies_whatever_the_cadence():
    """A correlation over five points is not worth showing, however sparse the metric."""
    quality = series_quality(series_from([80.0] * 5), window_days=90, metric_type="body_weight")

    assert quality["sufficient"] is False


def test_build_daily_series_averages_within_a_day():
    from datetime import datetime, timezone

    rows = [
        ("hr", datetime(2026, 5, 1, 8, tzinfo=timezone.utc), 60.0),
        ("hr", datetime(2026, 5, 1, 20, tzinfo=timezone.utc), 80.0),
        ("hr", datetime(2026, 5, 2, 8, tzinfo=timezone.utc), 70.0),
    ]
    result = build_daily_series(rows)
    assert result["hr"]["2026-05-01"] == pytest.approx(70.0)
    assert result["hr"]["2026-05-02"] == pytest.approx(70.0)


def test_build_daily_series_skips_null_values():
    from datetime import datetime, timezone

    rows = [
        ("hr", datetime(2026, 5, 1, 8, tzinfo=timezone.utc), None),
        ("hr", datetime(2026, 5, 1, 9, tzinfo=timezone.utc), 60.0),
    ]
    assert build_daily_series(rows)["hr"]["2026-05-01"] == pytest.approx(60.0)


def test_analysis_version_is_reported():
    assert ANALYSIS_VERSION
    assert all(part.isdigit() for part in ANALYSIS_VERSION.split("."))


def test_no_analysis_returns_nan_or_infinity():
    """Every number must survive JSON serialisation."""
    xs = [float(i) for i in range(30)]
    result = correlation_pairs({"a": series_from(xs), "b": series_from(xs)})[0]
    for key in ("pearson", "spearman", "coefficient", "strength_pct", "p_value"):
        assert math.isfinite(result[key]), key
