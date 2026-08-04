"""Pure analytics helpers used by tenant-scoped Core endpoints."""

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import sqrt
from typing import Any, Iterable


def detect_daily_gaps(
    points: Iterable[tuple[str, datetime]], start: date, end: date
) -> list[dict[str, Any]]:
    """Return missing UTC calendar days per metric within an inclusive window."""
    observed: dict[str, set[date]] = defaultdict(set)
    for metric_type, timestamp in points:
        observed[metric_type].add(timestamp.astimezone(timezone.utc).date())
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
