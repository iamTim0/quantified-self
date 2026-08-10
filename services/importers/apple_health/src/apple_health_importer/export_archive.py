"""Reading `export.zip` — the archive the Health app itself produces.

Apple's own export is the one way to get a *whole* history out of an iPhone: it needs
no third-party app, no subscription and no API, and it reaches back to the first day
the phone recorded anything. What it is not is a second vocabulary. Every record here
resolves to the same canonical metric the push path writes, so an archive imported
after months of live syncing adds the missing years and rewrites nothing (rule 15) —
the idempotency key is the same function of the same connector, metric and timestamp.

**Scope.** The archive holds everything HealthKit ever stored, including special
categories a person never chose to send anywhere: symptoms, cycle tracking,
medications, mood, ECG traces. The push path is opt-in per category *in the export
app*, so what arrives there is what the user picked. An archive carries no such
choice, so this reader stores only metrics the registry catalogues, plus workouts and
their GPS routes, and reports everything else as seen-not-stored. That is a
deliberately narrower rule than the push path's, and the Data Quality Center is where
its consequences are visible rather than invisible.

**Bounds.** An upload is untrusted input. The archive is capped, what comes *out* of
it is counted while it is read rather than trusted from the header, and the XML goes
through `defusedxml`, because an export is a file somebody else's software wrote.
"""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime
from typing import IO, Any

from defusedxml.ElementTree import iterparse
from shared_schemas import FieldReportCollector
from shared_schemas.metrics import METRIC_CATALOG

from apple_health_importer.transformer import (
    SLEEP_STAGE_MAP,
    route_points,
    canonical_name,
    generate_idempotency_key,
    normalise_value,
    parse_timestamp,
)

logger = logging.getLogger(__name__)

#: Whole archive, compressed. A decade of dense recording is a few hundred megabytes.
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024

#: Total *extracted* bytes, counted as they are read. The ratio between this and the
#: figure above is what a zip bomb exploits, and the header's own claim about its size
#: is written by whoever built the archive.
MAX_EXTRACTED_BYTES = 16 * 1024 * 1024 * 1024

#: Records read from one archive. A ceiling on work, not on legitimate history.
MAX_RECORDS = 10_000_000

#: HealthKit type identifiers all start with one of these. Stripping the prefix leaves
#: the name in the same vocabulary the push path uses, so both go through
#: `canonical_name` and land on the same metric.
_HK_PREFIXES = (
    "HKQuantityTypeIdentifier",
    "HKCategoryTypeIdentifier",
    "HKDataTypeIdentifier",
    "HKCharacteristicTypeIdentifier",
    "HKCorrelationTypeIdentifier",
    "HKClinicalTypeIdentifier",
    "HKWorkoutActivityType",
)

#: Sleep stage as the XML spells it -> the key `SLEEP_STAGE_MAP` uses.
SLEEP_VALUE_STAGES: dict[str, str] = {
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAsleepCore": "core",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisInBed": "inBed",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAsleep": "asleep",
}

#: `WorkoutStatistics` type -> (canonical metric, which attribute carries the number).
#: Newer exports moved the workout's totals out of the element's own attributes and
#: into these children, so an export written this year has `totalDistance` on neither
#: the workout nor anywhere else unless this is read.
WORKOUT_STATISTICS: dict[str, tuple[str, str]] = {
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("workout_energy", "sum"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("workout_distance", "sum"),
    "HKQuantityTypeIdentifierDistanceCycling": ("workout_distance", "sum"),
    "HKQuantityTypeIdentifierDistanceSwimming": ("workout_distance", "sum"),
    "HKQuantityTypeIdentifierHeartRate": ("workout_heart_rate_average", "average"),
}

#: The same statistics element also carries the maximum, which is a second metric.
_HEART_RATE_MAX = ("HKQuantityTypeIdentifierHeartRate", "maximum", "workout_heart_rate_max")


class ArchiveTooLarge(RuntimeError):
    """The upload, or what it expands to, exceeds what we are willing to read."""


class ArchiveUnreadable(RuntimeError):
    """Not a ZIP, or not one holding an Apple Health export."""


class _CountingReader:
    """A read-only view of a ZIP member that refuses to hand out too many bytes.

    `ZipInfo.file_size` is a number the archive states about itself. This counts what
    actually arrives, which is the only figure a malicious archive cannot choose.
    """

    def __init__(self, handle: IO[bytes], budget: list[int]) -> None:
        self._handle = handle
        self._budget = budget

    def read(self, size: int = -1) -> bytes:
        chunk = self._handle.read(size)
        self._budget[0] -= len(chunk)
        if self._budget[0] < 0:
            raise ArchiveTooLarge("The archive expands to more than we will read.")
        return chunk


def provider_name(hk_type: str) -> str:
    """`HKQuantityTypeIdentifierStepCount` -> `step_count`.

    The bridge between Apple's own vocabulary and Health Auto Export's, which is what
    `METRIC_NAME_MAP` is written in. Without it the archive would name its metrics
    differently from the push path for the same readings.
    """
    name = hk_type
    for prefix in _HK_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix) :]
            break

    out: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index and not name[index - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _is_catalogued(metric_type: str) -> bool:
    return metric_type in METRIC_CATALOG


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw.strip())
    except (ValueError, AttributeError):
        return None


def _minutes_between(start: str, end: str) -> float | None:
    """Length of a sleep stage, which the XML states as two moments rather than a number."""
    first, second = parse_timestamp(start), parse_timestamp(end)
    if first is None or second is None:
        return None
    delta = datetime.fromisoformat(second) - datetime.fromisoformat(first)
    minutes = delta.total_seconds() / 60
    return minutes if minutes > 0 else None


def _point(
    tenant_id: str,
    source_id: str,
    metric_type: str,
    timestamp: str,
    value: float,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "metric_type": metric_type,
        "timestamp": timestamp,
        "value": value,
        "metadata": metadata,
        "idempotency_key": generate_idempotency_key(tenant_id, source_id, metric_type, timestamp),
    }


def _member(archive: zipfile.ZipFile, suffix: str) -> zipfile.ZipInfo | None:
    """Find a member by file name, ignoring the directory above it and its case.

    iOS writes `apple_health_export/Export.xml` with a capital E. Comparing exactly
    rejected a real 195 MB export for that one letter, and said "No export.xml was
    found in the archive" about an archive whose first member was the export — the
    route files two functions down are already matched case-blind for the same reason.
    """
    wanted = suffix.lower()
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename.rsplit("/", 1)[-1]
        if name.lower() == wanted:
            return info
    return None


def read_export(
    file: str | IO[bytes],
    *,
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every data point an Apple Health archive holds, as it is read.

    A generator rather than a list: a decade of heart rate is millions of readings, and
    materialising them all before publishing the first one is how an import becomes a
    memory problem instead of a slow one.
    """
    report = report or FieldReportCollector()

    try:
        opened = zipfile.ZipFile(file)
    except zipfile.BadZipFile as exc:
        raise ArchiveUnreadable("That file is not a ZIP archive.") from exc

    # Closed when this generator is exhausted *or* closed — which is why the caller
    # closes it explicitly before deleting the upload. On Windows an open handle makes
    # the file undeletable, so a generator abandoned half-read would leave somebody's
    # medical history on disk.
    with opened as archive:
        export = _member(archive, "export.xml")
        if export is None:
            raise ArchiveUnreadable(
                "No export.xml was found in the archive. Export from Health > your profile "
                "> Export All Health Data and upload the file you receive."
            )

        budget = [MAX_EXTRACTED_BYTES]
        routes: dict[str, tuple[str, str]] = {}
        seen = 0

        with archive.open(export) as handle:
            root = None
            for event, elem in iterparse(_CountingReader(handle, budget), events=("start", "end")):
                if event == "start":
                    # The first element opened is the document root, and it is the one
                    # that has to be emptied as we go: clearing a record frees its
                    # children but leaves the record itself hanging off the root, which
                    # for ten million of them is the whole file in memory in another
                    # shape.
                    if root is None:
                        root = elem
                    continue

                if elem.tag == "Record":
                    seen += 1
                    yield from _record_points(elem, tenant_id, source_id, report)
                elif elem.tag == "Workout":
                    seen += 1
                    yield from _workout_points(elem, tenant_id, source_id, report, routes)
                elif elem.tag in ("ClinicalRecord", "Audiogram", "VisionPrescription", "StateOfMind"):
                    # Named rather than ignored: this is the "not stored yet" half of
                    # the field report, and it is what makes the scope note above
                    # checkable from the interface instead of only from this file.
                    report.unmapped(f"export.{elem.tag}", elem.attrib.get("type", ""))
                else:
                    # Nothing is cleared here on purpose. A `MetadataEntry` ends
                    # *before* the workout that contains it, and clearing it there
                    # empties the attributes its parent is about to read.
                    continue

                if seen > MAX_RECORDS:
                    raise ArchiveTooLarge(f"The archive holds more than {MAX_RECORDS} records.")
                elem.clear()
                if root is not None:
                    root.clear()

        yield from _route_file_points(archive, budget, routes, tenant_id, source_id, report)


def _record_points(
    elem: Any,
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector,
) -> Iterator[dict[str, Any]]:
    """One `<Record>` — a measurement, or a sleep stage stated as an interval."""
    hk_type = elem.attrib.get("type", "")
    start = elem.attrib.get("startDate", "")
    if not hk_type or not start:
        return

    raw_name = provider_name(hk_type)
    metadata_base: dict[str, Any] = {
        "source_type": "apple_health",
        "original_metric_name": raw_name,
        "units": elem.attrib.get("unit", ""),
    }
    if elem.attrib.get("sourceName"):
        metadata_base["device_source"] = elem.attrib["sourceName"]

    if hk_type == "HKCategoryTypeIdentifierSleepAnalysis":
        stage = SLEEP_VALUE_STAGES.get(elem.attrib.get("value", ""))
        metric_type = SLEEP_STAGE_MAP.get(stage or "")
        minutes = _minutes_between(start, elem.attrib.get("endDate", ""))
        ts = parse_timestamp(start)
        if metric_type is None or minutes is None or ts is None:
            report.unmapped("export.Record.sleepAnalysis", elem.attrib.get("value", ""))
            return
        report.mapped("export.Record.sleepAnalysis", minutes, metric_type)
        # The archive states a sleep stage as two moments, never as a number, so this
        # duration is ours: rule 19 wants that on the record rather than implied.
        metadata = {
            **metadata_base,
            "units": "min",
            "sleep_stage": stage,
            "provider_value": minutes,
            "derived_from": ["startDate", "endDate"],
            "derived_by": "difference",
        }
        yield _point(tenant_id, source_id, metric_type, ts, minutes, metadata)
        return

    metric_type = canonical_name(raw_name)
    if not _is_catalogued(metric_type):
        # Deliberate: see the scope note at the top. An archive holds categories
        # nobody opted into sending, so an uncatalogued type is reported rather than
        # stored under a namespaced name.
        report.unmapped(f"export.Record.{raw_name}", elem.attrib.get("value", ""))
        return

    value = _number(elem.attrib.get("value"))
    ts = parse_timestamp(start)
    if value is None or ts is None:
        report.unmapped(f"export.Record.{raw_name}", elem.attrib.get("value", ""))
        return

    converted = normalise_value(value, elem.attrib.get("unit", ""), metric_type)
    metadata = {**metadata_base, "provider_value": value}
    report.mapped(f"export.Record.{raw_name}", value, metric_type)
    yield _point(tenant_id, source_id, metric_type, ts, converted, metadata)


def _workout_points(
    elem: Any,
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector,
    routes: dict[str, tuple[str, str]],
) -> Iterator[dict[str, Any]]:
    """One `<Workout>`: its totals, its per-statistic children, and its route file."""
    start = elem.attrib.get("startDate", "")
    ts = parse_timestamp(start)
    if ts is None:
        return

    activity = provider_name(elem.attrib.get("workoutActivityType", ""))
    # Apple's export gives a workout no id of its own. The start is what distinguishes
    # one session from the next, and it is already what the idempotency key is built
    # from, so nothing is invented by using it here.
    workout_id = ts
    metadata_base: dict[str, Any] = {
        "source_type": "apple_health",
        "workout_name": activity,
        "workout_id": workout_id,
    }
    if elem.attrib.get("sourceName"):
        metadata_base["device_source"] = elem.attrib["sourceName"]

    for attribute, unit_attribute, metric_type in (
        ("duration", "durationUnit", "workout_duration"),
        ("totalDistance", "totalDistanceUnit", "workout_distance"),
        ("totalEnergyBurned", "totalEnergyBurnedUnit", "workout_energy"),
    ):
        value = _number(elem.attrib.get(attribute))
        if value is None:
            continue
        units = elem.attrib.get(unit_attribute, "")
        report.mapped(f"export.Workout.{attribute}", value, metric_type)
        yield _point(
            tenant_id,
            source_id,
            metric_type,
            ts,
            normalise_value(value, units, metric_type),
            {**metadata_base, "units": units, "provider_value": value},
        )

    for child in elem:
        if child.tag == "WorkoutStatistics":
            yield from _statistics_points(child, tenant_id, source_id, ts, metadata_base, report)
        elif child.tag == "MetadataEntry":
            key = child.attrib.get("key", "")
            if key:
                report.unmapped(f"export.Workout.metadata.{key}", child.attrib.get("value"))
        elif child.tag == "WorkoutRoute":
            for reference in child:
                path = reference.attrib.get("path", "")
                if path:
                    routes[path.rsplit("/", 1)[-1]] = (workout_id, activity)


def _statistics_points(
    child: Any,
    tenant_id: str,
    source_id: str,
    ts: str,
    metadata_base: dict[str, Any],
    report: FieldReportCollector,
) -> Iterator[dict[str, Any]]:
    hk_type = child.attrib.get("type", "")
    units = child.attrib.get("unit", "")

    mapping = WORKOUT_STATISTICS.get(hk_type)
    if mapping is None:
        report.unmapped(f"export.Workout.statistics.{provider_name(hk_type)}", child.attrib.get("sum"))
        return

    metric_type, attribute = mapping
    value = _number(child.attrib.get(attribute))
    if value is not None:
        report.mapped(f"export.Workout.statistics.{attribute}", value, metric_type)
        yield _point(
            tenant_id,
            source_id,
            metric_type,
            ts,
            normalise_value(value, units, metric_type),
            {**metadata_base, "units": units, "provider_value": value},
        )

    stat_type, stat_attribute, stat_metric = _HEART_RATE_MAX
    if hk_type == stat_type:
        maximum = _number(child.attrib.get(stat_attribute))
        if maximum is not None:
            report.mapped(f"export.Workout.statistics.{stat_attribute}", maximum, stat_metric)
            yield _point(
                tenant_id,
                source_id,
                stat_metric,
                ts,
                normalise_value(maximum, units, stat_metric),
                {**metadata_base, "units": units, "provider_value": maximum},
            )


def _route_file_points(
    archive: zipfile.ZipFile,
    budget: list[int],
    routes: dict[str, tuple[str, str]],
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector,
) -> Iterator[dict[str, Any]]:
    """The GPX files beside `export.xml`, as `location_point` measurements.

    Read whether or not a workout claimed them: a route whose workout was written by
    an app the export lists differently is still somebody's run, and dropping it for a
    bookkeeping mismatch loses the part of the archive that cannot be re-derived.
    """
    for info in archive.infolist():
        if info.is_dir() or not info.filename.lower().endswith(".gpx"):
            continue

        name = info.filename.rsplit("/", 1)[-1]
        workout_id, workout_name = routes.get(name, ("", "route"))

        fixes: list[dict[str, Any]] = []
        with archive.open(info) as handle:
            for _event, elem in iterparse(_CountingReader(handle, budget), events=("end",)):
                # GPX is namespaced, so every tag arrives as `{...}trkpt`.
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag != "trkpt":
                    # `ele` and `time` end before the `trkpt` they belong to; clearing
                    # them here would empty the values it is about to read.
                    continue

                fix: dict[str, Any] = {
                    "latitude": _number(elem.attrib.get("lat")),
                    "longitude": _number(elem.attrib.get("lon")),
                }
                for point_child in elem:
                    child_tag = point_child.tag.rsplit("}", 1)[-1]
                    if child_tag == "ele":
                        fix["altitude"] = _number(point_child.text)
                    elif child_tag == "time":
                        fix["timestamp"] = (point_child.text or "").strip()
                    elif child_tag == "extensions":
                        for extension in point_child.iter():
                            extension_tag = extension.tag.rsplit("}", 1)[-1]
                            if extension_tag in ("speed", "course", "hAcc", "vAcc"):
                                fix[
                                    {
                                        "speed": "speed",
                                        "course": "course",
                                        "hAcc": "horizontalAccuracy",
                                        "vAcc": "verticalAccuracy",
                                    }[extension_tag]
                                ] = _number(extension.text)
                fixes.append(fix)
                elem.clear()

        yield from route_points(fixes, tenant_id, source_id, workout_id, workout_name, report)
