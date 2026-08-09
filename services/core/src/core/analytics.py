"""Pure analytics helpers used by tenant-scoped Core endpoints."""

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone, tzinfo
from math import sqrt
from typing import Any

from shared_schemas.metrics import METRIC_CATALOG, Cadence

from core.ingest_planning import TimeRange, find_gaps


def detect_daily_gaps(
    points: Iterable[tuple[str, datetime]],
    start: date,
    end: date,
    *,
    local_timezone: tzinfo = timezone.utc,
) -> list[dict[str, Any]]:
    """Missing days per metric — for the metrics where a missing day means anything.

    Every metric used to be judged against the calendar, which made a rest day a
    "gap" in `workout_duration` and a fortnightly weigh-in look 93 % broken. The
    registry now says how often each metric is expected (`Cadence`), and only
    `DAILY` metrics are counted against days at all:

    * ``DAILY`` — a day without a value is a gap, which is the original behaviour
      and the only case where it was ever right.
    * ``CONTINUOUS`` — sampled at whatever rate the device chooses, so a day is the
      wrong unit entirely. Handled by :func:`detect_cadence_gaps` below, which
      measures against the rate actually observed.
    * ``EVENT`` — absence carries no information. Never a gap.

    Days are bucketed in `local_timezone` rather than UTC. Bucketing on UTC put a
    CET user's 00:30 reading on the previous day, so the first and last day of every
    window were systematically wrong — reported as missing while the data was there.
    """
    observed: dict[str, set[date]] = defaultdict(set)
    for metric_type, timestamp in points:
        if _cadence_of(metric_type) is not Cadence.DAILY:
            continue
        observed[metric_type].add(timestamp.astimezone(local_timezone).date())

    days = (end - start).days + 1
    return [
        {
            "metric_type": metric,
            "missing_dates": [
                (start + timedelta(days=offset)).isoformat()
                for offset in range(max(days, 0))
                if start + timedelta(days=offset) not in dates
            ],
        }
        for metric, dates in sorted(observed.items())
    ]


def detect_cadence_gaps(
    points: Iterable[tuple[str, datetime]],
    window: TimeRange,
    *,
    tolerance_factor: float = 2.5,
) -> list[dict[str, Any]]:
    """Interruptions in metrics sampled faster than daily.

    A heart-rate monitor that stops for a week is a gap worth reporting, but a
    calendar day is the wrong unit to notice it with — the device decides its own
    rate. Each metric is measured against the cadence it actually kept, so a
    five-minute sensor and an hourly one are both judged fairly.

    This exists because leaving `CONTINUOUS` metrics out of `detect_daily_gaps`
    would otherwise have meant nine metrics — heart rate and every weather series —
    silently reporting no gaps at all, which is worse than the false alarms the
    cadence work set out to remove.
    """
    by_metric: dict[str, list[datetime]] = defaultdict(list)
    for metric_type, timestamp in points:
        if _cadence_of(metric_type) is Cadence.CONTINUOUS:
            by_metric[metric_type].append(timestamp)

    gaps: list[dict[str, Any]] = []
    for metric, timestamps in sorted(by_metric.items()):
        ranges = find_gaps(timestamps, window, tolerance_factor=tolerance_factor)
        if ranges:
            gaps.append(
                {
                    "metric_type": metric,
                    "missing_ranges": [r.to_dict() for r in ranges],
                }
            )
    return gaps


def _cadence_of(metric_type: str) -> Cadence:
    """The registry's cadence, or ``EVENT`` for a name it does not catalogue.

    Namespaced metrics (`home_assistant_*`, `apple_health_*`) are defined by the
    user's own setup, so nothing here can know how often they should appear —
    and claiming a gap in one would be an invention.
    """
    definition = METRIC_CATALOG.get(metric_type)
    return definition.cadence if definition is not None else Cadence.EVENT


def find_cross_source_conflicts(
    points: Iterable[dict[str, Any]], tolerance: float = 0.05
) -> list[dict[str, Any]]:
    """Find same-metric/day values from different sources outside a relative tolerance."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for point in points:
        grouped[(point["metric_type"], point["timestamp"].date().isoformat())].append(point)
    conflicts: list[dict[str, Any]] = []
    for (metric, day), candidates in grouped.items():
        sources = {candidate["source_id"] for candidate in candidates}
        values = [candidate["value"] for candidate in candidates if candidate["value"] is not None]
        if len(sources) > 1 and len(values) > 1:
            spread = max(values) - min(values)
            baseline = max(abs(value) for value in values) or 1.0
            if spread / baseline > tolerance:
                conflicts.append({"metric_type": metric, "date": day, "candidates": candidates})
    return conflicts


def pearson_pairs(series: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """Calculate Pearson correlations for metric series aligned by ISO date."""
    results: list[dict[str, Any]] = []
    metrics = sorted(series)
    for index, left in enumerate(metrics):
        for right in metrics[index + 1 :]:
            dates = sorted(set(series[left]) & set(series[right]))
            if len(dates) < 3:
                continue
            xs = [series[left][day] for day in dates]
            ys = [series[right][day] for day in dates]
            x_mean, y_mean = sum(xs) / len(xs), sum(ys) / len(ys)
            numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys, strict=True))
            denominator = sqrt(
                sum((x - x_mean) ** 2 for x in xs) * sum((y - y_mean) ** 2 for y in ys)
            )
            results.append(
                {
                    "metric_a": left,
                    "metric_b": right,
                    "coefficient": round(numerator / denominator, 4) if denominator else 0.0,
                    "sample_size": len(dates),
                }
            )
    return sorted(results, key=lambda item: abs(item["coefficient"]), reverse=True)
