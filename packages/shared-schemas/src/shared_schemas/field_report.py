"""Which provider fields an importer used, and which it saw and did not.

The question this answers is "did we take everything?" — asked of the *shape* of a
payload, never of its contents. Four fields of Apple Health data were being dropped
silently for months because nobody could ask it: heart rate, blood pressure, workout
energy and workout distance all arrive under names the transformer did not read, and
nothing failed, so nothing said so.

**No values are recorded, ever.** Storing payloads would mean keeping a second copy
of the most sensitive data in the system, with its own retention question, and would
make the account deletion in `ProfileTab` incomplete unless it hunted that copy down
too. A path and the *kind* of thing that was at it is enough to notice a field going
unread, and is not health data.

The report is bounded by the provider's schema rather than by how much data arrived:
one entry per distinct path, however many records went past.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

#: More distinct paths than this and something is wrong with the payload -- a
#: provider that nests per-record identifiers into keys, say. Truncating protects
#: the report from becoming the thing it warns about.
MAX_TRACKED_PATHS = 500


def value_kind(value: Any) -> str:
    """What sort of thing sat at a path. Never the thing itself."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


class FieldSighting(BaseModel):
    """One path in a provider payload, and what became of it.

    The bounds are on the shared model rather than on the receiving endpoint, so
    the importer producing a report and the service storing it agree on what is
    acceptable instead of discovering the disagreement as a 422.
    """

    path: str = Field(..., min_length=1, max_length=512)
    kind: str = Field(..., max_length=16)
    occurrences: int = Field(1, ge=0)
    #: The canonical metric this path became, when it became one.
    metric_type: str | None = Field(None, max_length=128)


class FieldReport(BaseModel):
    """Everything one import saw, as a shape."""

    mapped: list[FieldSighting] = Field(default_factory=list, max_length=MAX_TRACKED_PATHS)
    unmapped: list[FieldSighting] = Field(default_factory=list, max_length=MAX_TRACKED_PATHS)
    truncated: bool = False


class FieldReportCollector:
    """Accumulates sightings while a transformer walks a payload.

    Deliberately not a payload walker of its own: only the transformer knows which
    of the paths it passed actually became a data point, and a generic walker would
    report every structural key — `data`, `metrics`, `0` — as an unmapped field.
    """

    def __init__(self, *, max_paths: int = MAX_TRACKED_PATHS) -> None:
        self._max_paths = max_paths
        self._mapped: dict[str, FieldSighting] = {}
        self._unmapped: dict[str, FieldSighting] = {}
        self._truncated = False

    def mapped(self, path: str, value: Any, metric_type: str, *, times: int = 1) -> None:
        """Record a path that produced a data point."""
        self._record(self._mapped, path, value, metric_type, times)

    def unmapped(self, path: str, value: Any, *, times: int = 1) -> None:
        """Record a path that was seen and produced nothing.

        This is the half worth reading: it is the list of things this platform is
        being given and quietly throwing away.

        ``times`` records a whole array's worth in one call, so a caller with a
        hundred thousand entries does not loop a hundred thousand times to add a
        hundred thousand to one counter.
        """
        self._record(self._unmapped, path, value, None, times)

    def _record(
        self,
        into: dict[str, FieldSighting],
        path: str,
        value: Any,
        metric_type: str | None,
        times: int = 1,
    ) -> None:
        existing = into.get(path)
        if existing is not None:
            # Mutated rather than `model_copy`-ed: measured at 0.33 µs against
            # 1.96 µs, and this runs once per field per record — a fifty-thousand
            # point push made roughly four hundred thousand of these.
            existing.occurrences += times
            return
        if len(self._mapped) + len(self._unmapped) >= self._max_paths:
            self._truncated = True
            return
        into[path] = FieldSighting(
            path=path, kind=value_kind(value), metric_type=metric_type, occurrences=times
        )

    def build(self) -> FieldReport:
        """The report to send to Core. Sorted so a diff between runs is readable.

        A path recorded as unmapped somewhere and mapped elsewhere counts as
        mapped: transformers meet the same key in many records, and one record
        lacking it is not a gap. Filtering here rather than on the way in is what
        makes that true regardless of which order the two sightings arrived in.
        """
        unmapped = [s for path, s in sorted(self._unmapped.items()) if path not in self._mapped]
        return FieldReport(
            mapped=[s for _, s in sorted(self._mapped.items())],
            unmapped=unmapped,
            truncated=self._truncated,
        )
