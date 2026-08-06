"""Import window planning and coverage analysis.

Three related jobs live here, all pure enough to test without a database:

1. **Adaptive windows** — how far back a sync should reach, derived from how often
   the connector actually polls and when it last succeeded, instead of always
   re-requesting a fixed 30-day lookback.
2. **Coverage analysis** — which parts of a requested range the tenant already has,
   determined coarse-to-fine rather than by inspecting every point.
3. **Gap detection** — which parts are missing relative to the observed measurement
   cadence, so the UI can propose an exact backfill range.

Core owns this rather than the importers because Core owns the history the
decisions are derived from. Importers receive a window and a mode in the sync task
and do as they are told, which keeps database ownership intact (AGENTS.md rule 1)
and puts the logic in one testable place.

**Safety rule.** Skipping work is only ever allowed for a range positively known to
be complete. Anything uncertain — partial buckets, irregular cadence, non-contiguous
coverage — is re-imported. Re-importing is cheap and idempotent; wrongly skipping
loses data permanently.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from statistics import median

# Overlap sizing. The brief's worked example is "hourly polling → about two hours
# of overlap", which OVERLAP_FACTOR=2 reproduces exactly; six-hourly then yields
# twelve hours, satisfying "correspondingly larger".
OVERLAP_FACTOR = 2.0
MIN_OVERLAP_HOURS = 2
MAX_OVERLAP_HOURS = 72

# Coarse-to-fine search bounds.
DEFAULT_COARSE_BUCKET_SECONDS = 86_400  # one day
MIN_BUCKET_SECONDS = 900  # stop refining at 15 minutes
FULLNESS_THRESHOLD = 0.9

# Above this many separate covered blocks the range is treated as irregular and
# boundary refinement is abandoned in favour of the safe answer.
MAX_BLOCKS_FOR_CONFIDENT_PLAN = 12


@dataclass(frozen=True)
class TimeRange:
    """A half-open interval ``[start, end)`` in UTC."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("TimeRange end must not precede start")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def is_empty(self) -> bool:
        return self.end <= self.start

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class BucketCount:
    """How many points fall in one time bucket."""

    start: datetime
    end: datetime
    count: int


@dataclass
class ImportPlan:
    """The outcome of analysing a requested import range."""

    requested: TimeRange
    covered: list[TimeRange] = field(default_factory=list)
    missing: list[TimeRange] = field(default_factory=list)
    recommended: TimeRange | None = None
    mode: str = "smart"
    reason: str = ""
    confidence: str = "high"
    expected_interval_seconds: float | None = None
    total_points: int = 0

    def to_dict(self) -> dict:
        return {
            "requested": self.requested.to_dict(),
            "covered_ranges": [r.to_dict() for r in self.covered],
            "missing_ranges": [r.to_dict() for r in self.missing],
            "recommended_range": self.recommended.to_dict() if self.recommended else None,
            "mode": self.mode,
            "reason": self.reason,
            "confidence": self.confidence,
            "expected_interval_seconds": self.expected_interval_seconds,
            "total_points": self.total_points,
            "skipped_ranges": [r.to_dict() for r in self.covered],
        }


# ─── 1. Adaptive windows ─────────────────────────────────────


def overlap_for_interval(poll_interval_hours: float) -> timedelta:
    """How much to re-request beyond the last successful sync.

    The overlap absorbs clock skew, late-arriving upstream data and a missed run,
    at the cost of duplicate events that idempotency already discards.
    """
    if poll_interval_hours <= 0:
        return timedelta(hours=MIN_OVERLAP_HOURS)
    hours = math.ceil(poll_interval_hours * OVERLAP_FACTOR)
    hours = max(MIN_OVERLAP_HOURS, min(MAX_OVERLAP_HOURS, hours))
    return timedelta(hours=hours)


def compute_sync_window(
    *,
    now: datetime,
    poll_interval_hours: float,
    lookback_days: int,
    last_success_end: datetime | None = None,
    earliest_known_gap: datetime | None = None,
) -> tuple[TimeRange, str]:
    """Decide the window for the next scheduled or manual sync.

    Returns the window and a human-readable German reason, which is surfaced in the
    UI and stored on the sync run so a later reader can tell why a range was chosen.
    """
    now = _as_utc(now)
    horizon = now - timedelta(days=max(1, lookback_days))

    if last_success_end is None:
        return (
            TimeRange(horizon, now),
            f"Erstimport: vollständiger Zeitraum der letzten {lookback_days} Tage.",
        )

    last_success_end = _as_utc(last_success_end)
    overlap = overlap_for_interval(poll_interval_hours)
    start = last_success_end - overlap
    reason = (
        f"Anschluss an den letzten erfolgreichen Import mit "
        f"{int(overlap.total_seconds() // 3600)} h Überlappung "
        f"(Abfrageintervall {poll_interval_hours:g} h)."
    )

    if earliest_known_gap is not None:
        earliest_known_gap = _as_utc(earliest_known_gap)
        if earliest_known_gap < start:
            start = earliest_known_gap
            reason = (
                f"Erweitert bis zur ältesten bekannten Datenlücke "
                f"({earliest_known_gap.date().isoformat()}), "
                f"Abfrageintervall {poll_interval_hours:g} h."
            )

    if start < horizon:
        start = horizon
        reason += f" Begrenzt auf das konfigurierte Lookback von {lookback_days} Tagen."

    if start >= now:
        # The connector already has everything up to now; nothing sensible to do
        # but re-check the most recent overlap.
        start = now - overlap

    return TimeRange(start, now), reason


# ─── 2. Coverage analysis, coarse to fine ────────────────────

BucketFetcher = Callable[[datetime, datetime, int], Awaitable[Sequence[BucketCount]]]


def classify_buckets(
    buckets: Sequence[BucketCount],
    *,
    expected_per_bucket: float | None = None,
    fullness_threshold: float = FULLNESS_THRESHOLD,
) -> tuple[list[str], float]:
    """Label each bucket ``full`` / ``partial`` / ``empty``.

    ``expected_per_bucket`` defaults to the median of the non-empty buckets, which
    adapts to whatever cadence the metric actually has without per-metric config.
    """
    non_empty = [b.count for b in buckets if b.count > 0]
    if expected_per_bucket is None:
        expected_per_bucket = float(median(non_empty)) if non_empty else 0.0

    labels: list[str] = []
    for bucket in buckets:
        if bucket.count <= 0:
            labels.append("empty")
        elif expected_per_bucket > 0 and bucket.count >= expected_per_bucket * fullness_threshold:
            labels.append("full")
        else:
            labels.append("partial")
    return labels, expected_per_bucket


def merge_adjacent(ranges: Sequence[TimeRange]) -> list[TimeRange]:
    """Collapse touching or overlapping ranges into the fewest equivalent ranges."""
    ordered = sorted((r for r in ranges if not r.is_empty()), key=lambda r: r.start)
    merged: list[TimeRange] = []
    for current in ordered:
        if merged and current.start <= merged[-1].end:
            if current.end > merged[-1].end:
                merged[-1] = TimeRange(merged[-1].start, current.end)
        else:
            merged.append(current)
    return merged


def subtract(outer: TimeRange, holes: Sequence[TimeRange]) -> list[TimeRange]:
    """Everything in ``outer`` not covered by ``holes``."""
    remaining: list[TimeRange] = []
    cursor = outer.start
    for hole in merge_adjacent(holes):
        if hole.end <= outer.start or hole.start >= outer.end:
            continue
        if hole.start > cursor:
            remaining.append(TimeRange(cursor, min(hole.start, outer.end)))
        cursor = max(cursor, hole.end)
    if cursor < outer.end:
        remaining.append(TimeRange(cursor, outer.end))
    return [r for r in remaining if not r.is_empty()]


def choose_bucket_seconds(window: TimeRange, target_buckets: int = 60) -> int:
    """Pick a first-pass granularity giving roughly ``target_buckets`` buckets."""
    span = max(1.0, window.duration.total_seconds())
    raw = span / max(1, target_buckets)
    for candidate in (900, 3_600, 10_800, 21_600, 43_200, 86_400, 604_800):
        if raw <= candidate:
            return candidate
    return 604_800


async def refine_boundary(
    fetch: BucketFetcher,
    span: TimeRange,
    *,
    looking_for: str,
    expected_per_bucket: float,
    min_bucket_seconds: int = MIN_BUCKET_SECONDS,
) -> datetime | None:
    """Binary-subdivide a partial bucket to locate where coverage actually changes.

    ``looking_for='end'`` finds the last instant that is still covered;
    ``looking_for='start'`` finds the first. Returns ``None`` when the boundary
    cannot be established, which callers must treat as "do not skip".

    Subdivision rather than a per-point scan is the point: each level costs one
    aggregate query and halves the uncertainty, so a day-sized partial bucket is
    resolved to 15 minutes in about six queries instead of reading every row.
    """
    low, high = span.start, span.end
    boundary: datetime | None = None

    while (high - low).total_seconds() > min_bucket_seconds:
        mid = low + (high - low) / 2
        first_half = TimeRange(low, mid)
        buckets = await fetch(
            first_half.start, first_half.end, int(first_half.duration.total_seconds())
        )
        count = sum(b.count for b in buckets)
        # Scale the expectation to the sub-range being probed.
        scaled_expectation = expected_per_bucket * (
            first_half.duration.total_seconds() / max(1.0, span.duration.total_seconds())
        )
        is_full = scaled_expectation > 0 and count >= scaled_expectation * FULLNESS_THRESHOLD

        if looking_for == "end":
            if is_full:
                boundary = mid
                low = mid
            else:
                high = mid
        else:
            if is_full:
                high = mid
            else:
                boundary = mid
                low = mid

    return boundary


async def analyse_coverage(
    fetch: BucketFetcher,
    window: TimeRange,
    *,
    coarse_bucket_seconds: int | None = None,
    expected_per_bucket: float | None = None,
) -> tuple[list[TimeRange], list[TimeRange], str, float, int]:
    """Work out which parts of ``window`` are already fully present.

    Returns ``(covered, missing, confidence, expected_per_bucket, total_points)``.
    ``confidence`` is ``"low"`` when the data is too irregular to trust block-level
    conclusions; callers must then skip nothing.
    """
    bucket_seconds = coarse_bucket_seconds or choose_bucket_seconds(window)
    buckets = list(await fetch(window.start, window.end, bucket_seconds))

    if not buckets:
        return [], [window], "high", 0.0, 0

    total_points = sum(b.count for b in buckets)
    if total_points == 0:
        return [], [window], "high", 0.0, 0

    labels, expectation = classify_buckets(
        buckets, expected_per_bucket=expected_per_bucket
    )

    full_ranges = [
        TimeRange(b.start, b.end) for b, label in zip(buckets, labels) if label == "full"
    ]
    covered = merge_adjacent(full_ranges)

    confidence = "high"
    if len(covered) > MAX_BLOCKS_FOR_CONFIDENT_PLAN:
        # Heavily fragmented coverage: block-level reasoning would be guesswork.
        confidence = "low"
        return covered, subtract(window, covered), confidence, expectation, total_points

    # Extend each covered block into the partial buckets on either side, so the
    # reported boundary is the real one rather than the coarse grid line.
    refined: list[TimeRange] = []
    for block in covered:
        start, end = block.start, block.end

        before = _bucket_at(buckets, labels, end, "partial")
        if before is not None:
            found = await refine_boundary(
                fetch,
                TimeRange(before.start, before.end),
                looking_for="end",
                expected_per_bucket=expectation,
            )
            if found is not None:
                end = found

        after = _bucket_ending_at(buckets, labels, start, "partial")
        if after is not None:
            found = await refine_boundary(
                fetch,
                TimeRange(after.start, after.end),
                looking_for="start",
                expected_per_bucket=expectation,
            )
            if found is not None:
                start = found

        refined.append(TimeRange(start, end))

    covered = merge_adjacent(refined)
    missing = subtract(window, covered)
    return covered, missing, confidence, expectation, total_points


def _bucket_at(
    buckets: Sequence[BucketCount], labels: Sequence[str], boundary: datetime, want: str
) -> BucketCount | None:
    """The bucket starting exactly at ``boundary`` with the wanted label."""
    for bucket, label in zip(buckets, labels):
        if bucket.start == boundary and label == want:
            return bucket
    return None


def _bucket_ending_at(
    buckets: Sequence[BucketCount], labels: Sequence[str], boundary: datetime, want: str
) -> BucketCount | None:
    """The bucket ending exactly at ``boundary`` with the wanted label."""
    for bucket, label in zip(buckets, labels):
        if bucket.end == boundary and label == want:
            return bucket
    return None


# ─── 3. Gap detection against observed cadence ───────────────


def detect_expected_interval(timestamps: Sequence[datetime]) -> float | None:
    """Estimate the measurement cadence in seconds as the median gap.

    The median is used rather than the mean so a single long outage does not
    inflate the estimate and hide every real gap behind it.
    """
    if len(timestamps) < 3:
        return None
    ordered = sorted(_as_utc(t) for t in timestamps)
    deltas = [
        (b - a).total_seconds()
        for a, b in pairwise(ordered)
        if (b - a).total_seconds() > 0
    ]
    if not deltas:
        return None
    return float(median(deltas))


def find_gaps(
    timestamps: Sequence[datetime],
    window: TimeRange,
    *,
    expected_interval_seconds: float | None = None,
    tolerance_factor: float = 2.5,
) -> list[TimeRange]:
    """Ranges inside ``window`` where the cadence was interrupted.

    A gap is any span longer than ``tolerance_factor`` times the observed cadence.
    The tolerance keeps normal jitter — a sensor that reports every 5 minutes give
    or take — from being reported as a data loss.
    """
    if not timestamps:
        return [window] if not window.is_empty() else []

    ordered = sorted(_as_utc(t) for t in timestamps if window.start <= _as_utc(t) <= window.end)
    if not ordered:
        return [window] if not window.is_empty() else []

    interval = expected_interval_seconds or detect_expected_interval(ordered)
    if not interval:
        return []

    threshold = timedelta(seconds=interval * tolerance_factor)
    gaps: list[TimeRange] = []

    if ordered[0] - window.start > threshold:
        gaps.append(TimeRange(window.start, ordered[0]))

    for previous, current in pairwise(ordered):
        if current - previous > threshold:
            gaps.append(TimeRange(previous, current))

    if window.end - ordered[-1] > threshold:
        gaps.append(TimeRange(ordered[-1], window.end))

    return gaps


# ─── Plan assembly ───────────────────────────────────────────


async def plan_import(
    fetch: BucketFetcher,
    window: TimeRange,
    *,
    mode: str = "smart",
    coarse_bucket_seconds: int | None = None,
) -> ImportPlan:
    """Turn a requested range into an actionable plan.

    In ``force`` mode nothing is skipped: the caller has explicitly asked for the
    whole range to be re-processed. Idempotency still applies, so this costs
    duplicate events rather than duplicate rows.
    """
    if mode == "force":
        return ImportPlan(
            requested=window,
            covered=[],
            missing=[window],
            recommended=window,
            mode="force",
            reason=(
                "Force-Modus: Der gesamte angeforderte Zeitraum wird erneut verarbeitet. "
                "Bereits vorhandene Datenpunkte werden durch die Idempotenzprüfung "
                "verworfen, es entsteht aber zusätzlicher Verarbeitungsaufwand."
            ),
            confidence="high",
        )

    covered, missing, confidence, expectation, total = await analyse_coverage(
        fetch, window, coarse_bucket_seconds=coarse_bucket_seconds
    )

    if confidence == "low":
        # Irregular data: report what we saw but do not act on it.
        return ImportPlan(
            requested=window,
            covered=[],
            missing=[window],
            recommended=window,
            mode="smart",
            reason=(
                "Die vorhandenen Daten sind zu unregelmäßig für eine sichere "
                "Bereichserkennung. Es wird der vollständige Zeitraum importiert."
            ),
            confidence="low",
            expected_interval_seconds=None,
            total_points=total,
        )

    if not missing:
        return ImportPlan(
            requested=window,
            covered=covered,
            missing=[],
            recommended=None,
            mode="smart",
            reason=(
                f"Der Zeitraum von {_fmt(window.start)} bis {_fmt(window.end)} ist "
                "bereits vollständig vorhanden und wird übersprungen."
            ),
            confidence=confidence,
            expected_interval_seconds=expectation or None,
            total_points=total,
        )

    recommended = TimeRange(missing[0].start, missing[-1].end)
    if covered:
        reason = (
            f"Bereits vorhanden: {_describe(covered)}. "
            f"Importiert wird nur der neue Zeitraum von {_fmt(recommended.start)} "
            f"bis {_fmt(recommended.end)}."
        )
    else:
        reason = (
            f"Für den Zeitraum von {_fmt(window.start)} bis {_fmt(window.end)} "
            "liegen noch keine Daten vor."
        )

    return ImportPlan(
        requested=window,
        covered=covered,
        missing=missing,
        recommended=recommended,
        mode="smart",
        reason=reason,
        confidence=confidence,
        expected_interval_seconds=expectation or None,
        total_points=total,
    )


# ─── helpers ─────────────────────────────────────────────────


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _fmt(value: datetime) -> str:
    return value.strftime("%d.%m.%Y %H:%M")


def _describe(ranges: Sequence[TimeRange]) -> str:
    return ", ".join(f"{_fmt(r.start)}–{_fmt(r.end)}" for r in ranges)
