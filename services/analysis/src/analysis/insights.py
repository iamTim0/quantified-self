"""Statistical analyses over a tenant's daily metric series.

Everything here is a pure function over ``{metric: {iso_date: value}}`` so it can be
tested without a database, and so the reasoning about statistical validity lives in
one place rather than being spread across endpoints.

Two rules shape the whole module:

**Nothing is reported as causal.** These are associations between series. The wording
in every ``interpretation`` string says "goes together with", never "affects" or
"leads to", and every correlation carries the sample size, the significance and the
overlap so the reader can judge it.

**Insufficient data yields no result, not a weak one.** A correlation over four days
is noise with a number attached. Below ``MIN_SAMPLE_FOR_CORRELATION`` pairs nothing is
emitted at all, and results that clear that bar but not the significance threshold are
marked rather than silently presented as findings.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from statistics import fmean, median, pstdev
from typing import Any, Literal

from shared_schemas.metrics import METRIC_CATALOG, Cadence

# Bumped whenever the maths changes, so a stored or cached result can be traced back
# to the code that produced it.
ANALYSIS_VERSION = "2.0.0"

MIN_SAMPLE_FOR_CORRELATION = 10
MIN_SAMPLE_FOR_TREND = 7
MIN_SAMPLE_FOR_WEEKDAY = 14
MIN_SAMPLE_FOR_BASELINE = 14
SIGNIFICANCE_ALPHA = 0.05
MAX_LAG_DAYS = 7

Series = dict[str, dict[str, float]]


# ─── shared helpers ──────────────────────────────────────────


def _aligned(a: dict[str, float], b: dict[str, float], lag_days: int = 0):
    """Value pairs for days present in both series, optionally shifting ``b`` back.

    A positive lag asks: does today's `a` line up with `b` `lag` days later?
    """
    xs: list[float] = []
    ys: list[float] = []
    for day, x in a.items():
        target = day
        if lag_days:
            target = (date.fromisoformat(day) + timedelta(days=lag_days)).isoformat()
        y = b.get(target)
        if y is not None:
            xs.append(x)
            ys.append(y)
    return xs, ys


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = fmean(xs), fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else 0.0


def _ranks(values: list[float]) -> list[float]:
    """Average ranks, so ties do not distort Spearman."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Rank correlation — robust to outliers and monotone but non-linear links."""
    if len(xs) < 2:
        return 0.0
    return _pearson(_ranks(xs), _ranks(ys))


def _t_distribution_sf(t: float, df: int) -> float:
    """Two-sided p-value for a t statistic.

    Uses the regularised incomplete beta function via a continued fraction, which
    keeps the module dependency-free — Core does not otherwise need SciPy.
    """
    if df <= 0:
        return 1.0
    x = df / (df + t * t)
    return _betainc(df / 2.0, 0.5, x)


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(math.log(x) * a + math.log(1 - x) * b - lbeta) / a
    # Lentz's algorithm for the continued fraction.
    f, c, d = 1.0, 1.0, 0.0
    for i in range(200):
        m = i // 2
        if i == 0:
            numerator = 1.0
        elif i % 2 == 0:
            numerator = (m * (b - m) * x) / ((a + 2 * m - 1) * (a + 2 * m))
        else:
            numerator = -((a + m) * (a + b + m) * x) / ((a + 2 * m) * (a + 2 * m + 1))
        d = 1.0 + numerator * d
        if abs(d) < 1e-30:
            d = 1e-30
        d = 1.0 / d
        c = 1.0 + numerator / c
        if abs(c) < 1e-30:
            c = 1e-30
        f *= c * d
        if abs(1.0 - c * d) < 1e-8:
            break
    return front * (f - 1.0)


def correlation_p_value(r: float, n: int) -> float:
    """Two-sided p-value for a correlation coefficient."""
    if n < 3:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    t = abs(r) * math.sqrt((n - 2) / (1 - r * r))
    return min(1.0, _t_distribution_sf(t, n - 2))


def strength_label(r: float) -> str:
    a = abs(r)
    if a < 0.2:
        return "very weak"
    if a < 0.4:
        return "weak"
    if a < 0.6:
        return "moderate"
    if a < 0.8:
        return "strong"
    return "very strong"


def _direction_phrase(r: float) -> str:
    return "higher" if r > 0 else "lower"


# ─── result types ────────────────────────────────────────────


@dataclass
class Provenance:
    """Where a result came from, so it can be judged and reproduced."""

    analysis_version: str = ANALYSIS_VERSION
    computed_at: str = ""
    window_start: str | None = None
    window_end: str | None = None
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_version": self.analysis_version,
            "computed_at": self.computed_at,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "sources": self.sources,
        }


# ─── 1. correlations ─────────────────────────────────────────


def correlation_pairs(
    series: Series,
    *,
    min_sample: int = MIN_SAMPLE_FOR_CORRELATION,
    alpha: float = SIGNIFICANCE_ALPHA,
) -> list[dict[str, Any]]:
    """Pearson and Spearman for every metric pair with enough overlapping days.

    Both are reported: Pearson answers "do they move together linearly", Spearman
    "do they move together at all". A large gap between the two is itself a signal —
    usually an outlier or a non-linear relationship — and is surfaced as a caveat.
    """
    results: list[dict[str, Any]] = []
    metrics = sorted(series)

    for i, left in enumerate(metrics):
        for right in metrics[i + 1 :]:
            xs, ys = _aligned(series[left], series[right])
            n = len(xs)
            if n < min_sample:
                continue

            pearson = _pearson(xs, ys)
            spearman = _spearman(xs, ys)
            # Report on whichever is weaker: the conservative reading.
            headline = pearson if abs(pearson) <= abs(spearman) else spearman
            p_value = correlation_p_value(headline, n)

            caveats: list[str] = []
            if abs(pearson - spearman) > 0.25:
                caveats.append(
                    "Pearson and Spearman disagree noticeably — possibly an "
                    "outlier, or a relationship that is not linear."
                )
            if n < min_sample * 2:
                caveats.append(
                    f"Only {n} days in common — the result carries little weight."
                )
            if p_value > alpha:
                caveats.append(
                    "Not statistically significant: the relationship may be chance."
                )

            results.append(
                {
                    "metric_a": left,
                    "metric_b": right,
                    "pearson": round(pearson, 4),
                    "spearman": round(spearman, 4),
                    "coefficient": round(headline, 4),
                    "strength_pct": round(abs(headline) * 100, 1),
                    "direction": "positive" if headline >= 0 else "negative",
                    "strength_label": strength_label(headline),
                    "sample_size": n,
                    "p_value": round(p_value, 5),
                    "significant": bool(p_value <= alpha),
                    "interpretation": (
                        f"{left} and {right} go together: days with higher values for "
                        f"{left} come on average with {_direction_phrase(headline)} values "
                        f"for {right} ({strength_label(headline)}, n={n}). "
                        "That is a relationship, not a cause."
                    ),
                    "caveats": caveats,
                }
            )

    return sorted(results, key=lambda r: abs(r["coefficient"]), reverse=True)


def lagged_correlations(
    series: Series,
    *,
    max_lag: int = MAX_LAG_DAYS,
    min_sample: int = MIN_SAMPLE_FOR_CORRELATION,
) -> list[dict[str, Any]]:
    """Best time-shifted association per metric pair.

    A lag makes the ordering visible — "today's value lines up with tomorrow's" — but
    ordering still is not causation, and the wording keeps that explicit.
    """
    out: list[dict[str, Any]] = []
    metrics = sorted(series)

    for i, left in enumerate(metrics):
        for right in metrics:
            if right == left or (right in metrics[:i] and left in metrics):  # noqa: SIM102
                # Evaluate each ordered pair once; direction matters for lags.
                if metrics.index(right) < i:
                    continue
            if right == left:
                continue

            best: dict[str, Any] | None = None
            for lag in range(1, max_lag + 1):
                xs, ys = _aligned(series[left], series[right], lag_days=lag)
                if len(xs) < min_sample:
                    continue
                r = _spearman(xs, ys)
                if best is None or abs(r) > abs(best["coefficient"]):
                    best = {
                        "metric_a": left,
                        "metric_b": right,
                        "lag_days": lag,
                        "coefficient": round(r, 4),
                        "strength_pct": round(abs(r) * 100, 1),
                        "sample_size": len(xs),
                        "p_value": round(correlation_p_value(r, len(xs)), 5),
                    }
            if best and abs(best["coefficient"]) >= 0.3:
                best["significant"] = best["p_value"] <= SIGNIFICANCE_ALPHA
                best["interpretation"] = (
                    f"{best['metric_a']} goes together with {best['metric_b']} "
                    f"{best['lag_days']} day(s) later "
                    f"({strength_label(best['coefficient'])}, n={best['sample_size']}). "
                    "An order in time is not evidence of a cause."
                )
                out.append(best)

    return sorted(out, key=lambda r: abs(r["coefficient"]), reverse=True)


# ─── 2. trends ───────────────────────────────────────────────


def moving_average(values: list[float], window: int = 7) -> list[float | None]:
    """Trailing mean; ``None`` until the window is full, so no partial-window artefacts."""
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(round(fmean(values[i + 1 - window : i + 1]), 4))
    return out


def trend_for_metric(
    days: list[str], values: list[float], *, min_sample: int = MIN_SAMPLE_FOR_TREND
) -> dict[str, Any] | None:
    """Least-squares slope per day, with an r² so a weak fit is visible as weak."""
    n = len(values)
    if n < min_sample:
        return None

    xs = list(range(n))
    mx, my = fmean(xs), fmean(values)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, values)) / denom
    intercept = my - slope * mx

    ss_tot = sum((y - my) ** 2 for y in values)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, values))
    r_squared = 1 - ss_res / ss_tot if ss_tot else 0.0

    spread = pstdev(values) if n > 1 else 0.0
    # A slope smaller than a tenth of the day-to-day spread is indistinguishable
    # from noise at this resolution.
    if abs(slope) < spread * 0.1 or r_squared < 0.1:
        direction = "flat"
    else:
        direction = "rising" if slope > 0 else "falling"

    change_pct = (slope * n / abs(my) * 100) if my else 0.0

    return {
        "direction": direction,
        "slope_per_day": round(slope, 5),
        "change_pct_over_window": round(change_pct, 1),
        "r_squared": round(r_squared, 3),
        "sample_size": n,
        "first_day": days[0],
        "last_day": days[-1],
        "mean": round(my, 3),
        "moving_average_7d": moving_average(values, 7),
        "interpretation": (
            f"Over {n} days the course is {direction}"
            + (
                f" (about {abs(change_pct):.0f}% change across the period)."
                if direction != "flat"
                else "."
            )
            + (
                " The spread is wide, so the trend is uncertain."
                if r_squared < 0.3
                else ""
            )
        ),
    }


# ─── 3. weekday / routine patterns ───────────────────────────

#: Stable lowercase identifiers, in `date.weekday()` order — Monday is 0.
#:
#: These used to be German words, which was two rules at once: a service wrote
#: prose in a language the repository does not use (rule 16), and it decided the
#: reader's language on the server (rule 17). An English reader saw "Montag"; so
#: did a chart legend, an export and anything else that ever read this field.
#:
#: The name of a day is exactly what rule 17 means by a code: the dashboard
#: renders it through `weekday.<id>` and falls back to the value itself for one
#: it does not know, which is what keeps a report stored before this change
#: legible until it is recomputed.
WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def weekday_pattern(
    daily: dict[str, float], *, min_sample: int = MIN_SAMPLE_FOR_WEEKDAY
) -> dict[str, Any] | None:
    """Mean per weekday, plus how far weekend differs from the working week."""
    if len(daily) < min_sample:
        return None

    buckets: dict[int, list[float]] = defaultdict(list)
    for day, value in daily.items():
        buckets[date.fromisoformat(day).weekday()].append(value)

    per_day = [
        {
            "weekday": WEEKDAYS[i],
            "mean": round(fmean(buckets[i]), 3) if buckets.get(i) else None,
            "sample_size": len(buckets.get(i, [])),
        }
        for i in range(7)
    ]

    weekday_values = [v for i in range(5) for v in buckets.get(i, [])]
    weekend_values = [v for i in (5, 6) for v in buckets.get(i, [])]
    if len(weekday_values) < 3 or len(weekend_values) < 2:
        return {"per_weekday": per_day, "weekend_effect": None}

    wd, we = fmean(weekday_values), fmean(weekend_values)
    delta_pct = ((we - wd) / abs(wd) * 100) if wd else 0.0

    return {
        "per_weekday": per_day,
        "weekend_effect": {
            "weekday_mean": round(wd, 3),
            "weekend_mean": round(we, 3),
            "difference_pct": round(delta_pct, 1),
            "interpretation": (
                f"At the weekend the value averages "
                f"{abs(delta_pct):.0f}% {'higher' if delta_pct > 0 else 'lower'} "
                f"than on weekdays."
                if abs(delta_pct) >= 5
                else "No clear difference between weekends and weekdays."
            ),
        },
    }


# ─── 4. anomalies against a personal baseline ────────────────


def detect_anomalies(
    daily: dict[str, float],
    *,
    z_threshold: float = 2.5,
    min_sample: int = MIN_SAMPLE_FOR_BASELINE,
) -> dict[str, Any] | None:
    """Days that sit far from the person's own typical range.

    The baseline is the median and the median absolute deviation rather than mean and
    standard deviation: an outlier should not inflate the very yardstick used to
    detect it.
    """
    if len(daily) < min_sample:
        return None

    values = list(daily.values())
    centre = median(values)
    mad = median([abs(v - centre) for v in values])
    # 1.4826 scales MAD to be comparable with a standard deviation for normal data.
    scale = mad * 1.4826 or pstdev(values)
    if not scale:
        return None

    anomalies = []
    for day, value in sorted(daily.items()):
        z = (value - centre) / scale
        if abs(z) >= z_threshold:
            anomalies.append(
                {
                    "date": day,
                    "value": round(value, 3),
                    "deviation_score": round(z, 2),
                    "direction": "unusually high" if z > 0 else "unusually low",
                }
            )

    return {
        "baseline_median": round(centre, 3),
        "normal_range_low": round(centre - 2 * scale, 3),
        "normal_range_high": round(centre + 2 * scale, 3),
        "sample_size": len(values),
        "anomalies": anomalies[-20:],
        "interpretation": (
            f"Typical range: {round(centre - 2 * scale, 1)} to "
            f"{round(centre + 2 * scale, 1)}. "
            + (
                f"{len(anomalies)} day(s) fall clearly outside it."
                if anomalies
                else "No notable outliers."
            )
        ),
    }


# ─── 5. period comparison ────────────────────────────────────


def compare_periods(
    daily: dict[str, float],
    *,
    period_a: tuple[str, str],
    period_b: tuple[str, str],
) -> dict[str, Any] | None:
    """Compare two freely chosen windows of the same metric."""

    def collect(window: tuple[str, str]) -> list[float]:
        lo, hi = window
        return [v for d, v in daily.items() if lo <= d <= hi]

    a_values, b_values = collect(period_a), collect(period_b)
    if len(a_values) < 3 or len(b_values) < 3:
        return None

    a_mean, b_mean = fmean(a_values), fmean(b_values)
    delta = b_mean - a_mean
    delta_pct = (delta / abs(a_mean) * 100) if a_mean else 0.0

    # Welch's t-test: the two windows need not have equal variance or length.
    va = pstdev(a_values) ** 2 / len(a_values) if len(a_values) > 1 else 0.0
    vb = pstdev(b_values) ** 2 / len(b_values) if len(b_values) > 1 else 0.0
    se = math.sqrt(va + vb)

    if se > 0:
        t = delta / se
        denom = (va**2 / max(1, len(a_values) - 1)) + (vb**2 / max(1, len(b_values) - 1))
        df = max(1, int((va + vb) ** 2 / denom)) if denom > 0 else 1
        p = min(1.0, _t_distribution_sf(abs(t), df))
    elif delta != 0:
        # Both windows are perfectly constant at different levels. There is no
        # within-group variation for the difference to be attributable to, so this
        # is the most separable case there is — not, as a naive `if se:` guard would
        # have it, the least.
        p = 0.0
    else:
        # Constant and identical: nothing distinguishes the windows.
        p = 1.0

    return {
        "period_a": {"start": period_a[0], "end": period_a[1], "mean": round(a_mean, 3), "n": len(a_values)},
        "period_b": {"start": period_b[0], "end": period_b[1], "mean": round(b_mean, 3), "n": len(b_values)},
        "difference": round(delta, 3),
        "difference_pct": round(delta_pct, 1),
        "p_value": round(p, 5),
        "significant": bool(p <= SIGNIFICANCE_ALPHA),
        "interpretation": (
            f"In the second period the mean is {abs(delta_pct):.0f}% "
            f"{'higher' if delta > 0 else 'lower'}. "
            + (
                "The difference is statistically significant."
                if p <= SIGNIFICANCE_ALPHA
                else "The difference is not statistically significant and may be chance."
            )
            + " A difference between two periods says nothing about the cause."
        ),
    }


# ─── 6. data quality of the analysis input ───────────────────


def series_quality(
    daily: dict[str, float], window_days: int, metric_type: str | None = None
) -> dict[str, Any]:
    """How trustworthy the input to an analysis is.

    Coverage is measured against what the metric is *expected* to produce, not
    against the calendar. Judged against the calendar, an event-driven metric can
    never clear 50 % — nobody trains or weighs themselves daily — so body weight,
    workouts and every calendar-event metric were permanently excluded from every
    analysis for having exactly the density they are supposed to have.

    What stays unconditional is the sample size: a correlation over eight points is
    not worth showing whatever the cadence, so `MIN_SAMPLE_FOR_CORRELATION` still
    applies to all of them.
    """
    observed = len(daily)
    cadence = _cadence_of(metric_type)
    coverage = observed / window_days if window_days else 0.0

    if cadence is Cadence.DAILY:
        # A daily metric really should be there every day; half is a low bar.
        enough_density = coverage >= 0.5
    else:
        # For anything else the sample size is the only meaningful test.
        enough_density = True

    sufficient = observed >= MIN_SAMPLE_FOR_CORRELATION and enough_density
    return {
        "observed_days": observed,
        "window_days": window_days,
        "coverage_pct": round(coverage * 100, 1),
        "cadence": cadence.value,
        "sufficient": sufficient,
        "note": (
            "Enough data to work with."
            if sufficient
            else "Too few days for a reliable statement — analyses are hidden."
        ),
    }


def _cadence_of(metric_type: str | None) -> Cadence:
    """The registry's cadence, or ``EVENT`` for a name it does not catalogue."""
    if not metric_type:
        return Cadence.EVENT
    definition = METRIC_CATALOG.get(metric_type)
    return definition.cadence if definition is not None else Cadence.EVENT


# ─── assembly ────────────────────────────────────────────────


def build_daily_series(
    rows: Iterable[tuple[str, datetime, float]],
    aggregate: Literal["mean", "sum", "max"] = "mean",
) -> Series:
    """Collapse raw points into one value per metric per UTC day."""
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for metric, ts, value in rows:
        if value is None:
            continue
        day = ts.astimezone(timezone.utc).date().isoformat()
        buckets[metric][day].append(float(value))

    reducer = {"mean": fmean, "sum": sum, "max": max}[aggregate]
    return {
        metric: {day: round(float(reducer(vals)), 4) for day, vals in days.items()}
        for metric, days in buckets.items()
    }


# ─── 7. strength progression ─────────────────────────────────
#
# "Am I getting stronger" is not a correlation and not a trend over a daily
# series: it is a question about one exercise, and the thing that identifies an
# exercise lives in a metadata field. Core reads it (rule 1) and hands over sets
# through `QueryStrengthSets`; everything below is arithmetic over those rows and
# does no I/O, like the rest of this module.

#: Sessions an exercise needs before a direction is reported. Two points make a
#: line through any two numbers, and a line through two numbers is not a trend.
MIN_SESSIONS_FOR_PROGRESSION = 4

#: Exercises one bundle reports on. Ordered by how much work went into them, so
#: the cap keeps what somebody actually trains rather than what sorts first.
MAX_EXERCISES = 20


def estimated_one_rep_max(weight: float, reps: float) -> float | None:
    """Epley: `w × (1 + reps/30)`.

    An estimate, and only useful in the range it was fitted for. Above about ten
    repetitions it drifts high — a set of twenty says more about endurance than
    about a maximum — so it is not computed there rather than being computed and
    quietly wrong. A single repetition is its own answer.
    """
    if weight <= 0 or reps <= 0 or reps > 10:
        return None
    if reps == 1:
        return weight
    return weight * (1 + reps / 30.0)


def _session_key(entry: Any) -> str:
    """One training session, for an exercise that may be trained twice a day.

    The session id where the set carries one; the calendar date otherwise, which
    is what separated sessions before ids existed and is still right for a set
    stored back then.
    """
    return entry.session_id or entry.at.date().isoformat()


def exercise_progression(sets: list[Any]) -> list[dict[str, Any]]:
    """One entry per exercise: its sessions, its best sets, and where it is going.

    Grouped by session rather than by day so two sessions in one day are two data
    points, and sorted oldest first so the slope means what its sign says.
    """
    by_exercise: dict[str, list[Any]] = defaultdict(list)
    for entry in sets:
        if entry.exercise_title:
            by_exercise[entry.exercise_title].append(entry)

    results: list[dict[str, Any]] = []
    for exercise, entries in by_exercise.items():
        by_session: dict[str, list[Any]] = defaultdict(list)
        for entry in entries:
            by_session[_session_key(entry)].append(entry)

        sessions: list[dict[str, Any]] = []
        for rows in by_session.values():
            ordered = sorted(rows, key=lambda row: row.at)
            weighted = [row for row in ordered if row.has_weight and row.weight_kg > 0]
            top = max(weighted, key=lambda row: row.weight_kg) if weighted else None
            one_rm = estimated_one_rep_max(top.weight_kg, top.reps) if top else None
            sessions.append(
                {
                    "at": ordered[0].at.isoformat(),
                    "day": ordered[0].at.date().isoformat(),
                    "sets": len(ordered),
                    "reps": round(sum(row.reps for row in ordered), 1),
                    "volume_kg": round(sum(row.volume_kg for row in ordered), 1),
                    "top_set_weight_kg": round(top.weight_kg, 2) if top else None,
                    "estimated_1rm_kg": round(one_rm, 1) if one_rm is not None else None,
                    "muscle_group": ordered[0].muscle_group or None,
                }
            )
        sessions.sort(key=lambda item: item["at"])

        # What "stronger" means depends on the exercise, so the basis is chosen
        # rather than assumed, and the choice is reported.
        #
        #   * A loaded lift: the estimated one-rep max.
        #   * A loaded lift trained above ten reps, where Epley is not computed:
        #     total volume.
        #   * A bodyweight exercise: repetitions. It carries no load, so its volume
        #     is zero at every session — reporting "flat" for somebody who went from
        #     eight pull-ups to fifteen would be a wrong answer, not a missing one.
        candidates: list[tuple[str, list[tuple[str, float]]]] = [
            (
                "estimated_1rm",
                [(s["day"], s["estimated_1rm_kg"]) for s in sessions
                 if s["estimated_1rm_kg"] is not None],
            ),
            ("volume", [(s["day"], s["volume_kg"]) for s in sessions if s["volume_kg"]]),
            ("reps", [(s["day"], s["reps"]) for s in sessions if s["reps"]]),
        ]
        basis, series = next(
            (
                (name, points)
                for name, points in candidates
                if len(points) >= MIN_SESSIONS_FOR_PROGRESSION
            ),
            ("none", []),
        )
        trend = None
        if len(series) >= MIN_SESSIONS_FOR_PROGRESSION:
            trend = trend_for_metric(
                [day for day, _ in series],
                [value for _, value in series],
                min_sample=MIN_SESSIONS_FOR_PROGRESSION,
            )
            if trend is not None:
                # `moving_average_7d` is a window over *days*; these points are
                # sessions, which are days apart. Dropped rather than relabelled.
                trend.pop("moving_average_7d", None)
                trend["basis"] = basis

        best = max(
            (s for s in sessions if s["top_set_weight_kg"] is not None),
            key=lambda s: s["top_set_weight_kg"],
            default=None,
        )
        results.append(
            {
                "exercise_title": exercise,
                "muscle_group": next(
                    (s["muscle_group"] for s in sessions if s["muscle_group"]), None
                ),
                "sessions": len(sessions),
                "total_sets": sum(s["sets"] for s in sessions),
                "total_volume_kg": round(sum(s["volume_kg"] for s in sessions), 1),
                "best_set_weight_kg": best["top_set_weight_kg"] if best else None,
                "best_set_day": best["day"] if best else None,
                "latest_estimated_1rm_kg": next(
                    (s["estimated_1rm_kg"] for s in reversed(sessions)
                     if s["estimated_1rm_kg"] is not None),
                    None,
                ),
                "trend": trend,
                "history": sessions,
            }
        )

    results.sort(key=lambda item: item["total_volume_kg"], reverse=True)
    return results[:MAX_EXERCISES]


def muscle_group_volume(sets: list[Any]) -> list[dict[str, Any]]:
    """Where the work went, as a share of the whole.

    A share rather than a raw total, because the useful question is balance: a
    thousand kilos of pulling means nothing without knowing what was pushed.
    Sets carrying no volume — bodyweight work — are counted, because leaving them
    out would make a calisthenics programme look like no training at all.
    """
    volume: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for entry in sets:
        group = entry.muscle_group or "other"
        volume[group] += entry.volume_kg
        counts[group] += 1

    total_volume = sum(volume.values())
    total_sets = sum(counts.values())
    if not total_sets:
        return []

    return sorted(
        (
            {
                "muscle_group": group,
                "volume_kg": round(volume[group], 1),
                "sets": counts[group],
                "volume_share_pct": (
                    round(volume[group] / total_volume * 100, 1) if total_volume else None
                ),
                "set_share_pct": round(counts[group] / total_sets * 100, 1),
            }
            for group in counts
        ),
        key=lambda item: item["sets"],
        reverse=True,
    )


def strength_progression(sets: list[Any], *, truncated: bool = False) -> dict[str, Any]:
    """The strength half of the insights bundle.

    Empty rather than absent when a workspace logs no resistance training: a
    reader who has never lifted should see nothing here, not an error, and a
    consumer should not have to branch on a missing key.
    """
    exercises = exercise_progression(sets)
    return {
        "exercises": exercises,
        "muscle_groups": muscle_group_volume(sets),
        "sets_analysed": len(sets),
        "exercises_analysed": len(exercises),
        "truncated": truncated,
        "min_sessions_for_trend": MIN_SESSIONS_FOR_PROGRESSION,
        "disclaimer": (
            "An estimated one-rep max is Epley's formula applied to the heaviest "
            "set of a session, not a measurement. It is not computed above ten "
            "repetitions, where the formula drifts high."
        ),
    }
