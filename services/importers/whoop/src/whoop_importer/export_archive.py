"""Reading the Whoop data export — the ZIP that arrives by email.

Whoop will email an account's whole history as a ZIP of CSVs. That is a genuinely
different way in from the API: it needs no OAuth application, it reaches back
further than the API window, and it is the only option for somebody who just wants
their data once.

What it is *not* is a different set of numbers. Every column here resolves to a
canonical metric the polled importer already writes — a strain from an export and a
strain from a sync are the same quantity and must not become two series (rule 15).
The units differ, though, which is why ``EXPORT_METRICS`` exists beside the API's
table rather than being reused from it.

Bounded on purpose. An archive is an untrusted input: it is checked for size before
and *during* extraction, because a zip bomb's declared size is a claim by the
attacker and the only honest measurement is how many bytes actually come out.
"""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from collections.abc import Iterator
from typing import Any

from shared_schemas.metrics import MetricUnit

from whoop_importer.transformer import _Mapping

logger = logging.getLogger(__name__)

#: Whole archive, compressed. Comfortably above a decade of Whoop history.
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024

#: Total *extracted* bytes. The ratio between the two is what a zip bomb exploits.
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024

#: Rows read from one archive. A ceiling on work, not on legitimate history.
MAX_ROWS = 2_000_000

#: Which CSV feeds which record kinds. A file can feed several: Whoop's cycle
#: export carries the recovery columns too — recovery score, resting heart rate,
#: HRV, SpO2, skin temperature — and yielding that row under `cycle` alone dropped
#: all five without a word. The file names Whoop uses have varied, so each entry
#: lists the spellings seen.
#:
#: Whoop localises the export to the account's language: an archive from a German
#: account holds `physiologische_zyklen.csv`, `Schlaf.csv` and `Trainings.csv`, with
#: German column headers to match. That is the provider's vocabulary, not this
#: repository's language (rule 16 governs what we write, not what a provider sends), so
#: the spellings belong here beside the English ones. An account's language is not
#: something a user should have to change to get their own data in.
CSV_KINDS: dict[str, tuple[str, ...]] = {
    "physiological_cycles": ("cycle", "recovery"),
    "cycles": ("cycle", "recovery"),
    "sleeps": ("sleep",),
    "sleep": ("sleep",),
    "workouts": ("workout",),
    "workout": ("workout",),
    # German
    "physiologische_zyklen": ("cycle", "recovery"),
    "schlaf": ("sleep",),
    "trainings": ("workout",),
}

#: Export column -> the flat field name a record carries it under.
#: German spellings are verbatim from a real export; the English ones follow Whoop's
#: documented header names. A spelling that turns out to be wrong costs nothing but the
#: column it fails to match, which the field report then names.
COLUMN_FIELDS: dict[str, str] = {
    "day strain": "day_strain",
    "energy burned (cal)": "energy_kcal",
    "average hr (bpm)": "average_heart_rate",
    "max hr (bpm)": "max_heart_rate",
    "recovery score %": "recovery_score",
    "resting heart rate (bpm)": "resting_heart_rate",
    "heart rate variability (ms)": "hrv_rmssd_milli",
    "blood oxygen %": "spo2_percentage",
    "skin temp (celsius)": "skin_temp_celsius",
    "sleep performance %": "sleep_performance_percentage",
    "sleep efficiency %": "sleep_efficiency_percentage",
    "respiratory rate (rpm)": "respiratory_rate",
    "activity strain": "activity_strain",
    "distance (meters)": "distance_meter",
    "duration (min)": "workout_duration_minutes",
    # Sleep, which the export states in full and this table read none of: the registry
    # has held every one of these stages all along.
    "asleep duration (min)": "sleep_duration_minutes",
    "in bed duration (min)": "sleep_in_bed_minutes",
    "light sleep duration (min)": "sleep_light_minutes",
    "deep (sws) duration (min)": "sleep_deep_minutes",
    "rem duration (min)": "sleep_rem_minutes",
    "awake duration (min)": "sleep_awake_minutes",
    # German
    "tagesbelastung": "day_strain",
    "verbrannte energie (cal)": "energy_kcal",
    "durchschnittliche hf (schläge pro minute)": "average_heart_rate",
    "max hf (schläge pro minute)": "max_heart_rate",
    "erholungswert %": "recovery_score",
    "ruheherzfrequenz (schläge pro minute)": "resting_heart_rate",
    "herzfrequenzvariabilität (ms)": "hrv_rmssd_milli",
    "blutsauerstoff %": "spo2_percentage",
    "hauttemperatur (celsius)": "skin_temp_celsius",
    "schlafleistung %": "sleep_performance_percentage",
    "schlafeffizienz %": "sleep_efficiency_percentage",
    "atemfrequenz (atemzüge/min.)": "respiratory_rate",
    "aktivitätsbelastung": "activity_strain",
    "dauer (min.)": "workout_duration_minutes",
    "schlafdauer (min.)": "sleep_duration_minutes",
    "dauer im bett (min.)": "sleep_in_bed_minutes",
    "dauer des leichtschlafs (min.)": "sleep_light_minutes",
    "dauer des tiefschlafs (min.)": "sleep_deep_minutes",
    "dauer des rem-schlafs (min.)": "sleep_rem_minutes",
    "dauer des aufwachens (min.)": "sleep_awake_minutes",
}

#: What each field becomes — the same canonical metric names the polled importer
#: writes, so an export and a sync produce one series rather than two (rule 15).
#:
#: The units differ from the API's, which is the whole reason this table exists
#: separately: Whoop's export gives energy in kilocalories while its API gives
#: kilojoules, and routing the export through the API's mapping would divide every
#: figure by 4.184 without anything looking wrong.
EXPORT_METRICS: dict[str, tuple[_Mapping, ...]] = {
    "cycle": (
        _Mapping("whoop_strain", "", "day_strain"),
        _Mapping("energy_total", "", "energy_kcal"),
        _Mapping("heart_rate_average", "", "average_heart_rate"),
    ),
    "recovery": (
        _Mapping("whoop_recovery_score", "", "recovery_score"),
        _Mapping("heart_rate_resting", "", "resting_heart_rate"),
        _Mapping("hrv_rmssd", "", "hrv_rmssd_milli"),
        _Mapping("blood_oxygen", "", "spo2_percentage"),
        _Mapping("skin_temperature", "", "skin_temp_celsius"),
    ),
    "sleep": (
        _Mapping("whoop_sleep_performance", "", "sleep_performance_percentage"),
        _Mapping("sleep_efficiency", "", "sleep_efficiency_percentage"),
        _Mapping("respiratory_rate", "", "respiratory_rate"),
        # The export states the whole night — duration, time in bed and all four
        # stages — and every one of them has had a registry key since sleep was
        # first catalogued. Reading three columns out of nine meant an export
        # produced a sleep score and no sleep.
        _Mapping("sleep_duration", "", "sleep_duration_minutes"),
        _Mapping("sleep_duration_in_bed", "", "sleep_in_bed_minutes"),
        _Mapping("sleep_duration_light", "", "sleep_light_minutes"),
        _Mapping("sleep_duration_deep", "", "sleep_deep_minutes"),
        _Mapping("sleep_duration_rem", "", "sleep_rem_minutes"),
        _Mapping("sleep_duration_awake", "", "sleep_awake_minutes"),
    ),
    "workout": (
        _Mapping("whoop_workout_strain", "", "activity_strain"),
        _Mapping("workout_energy", "", "energy_kcal"),
        _Mapping("workout_heart_rate_average", "", "average_heart_rate"),
        _Mapping("workout_heart_rate_max", "", "max_heart_rate"),
        _Mapping("workout_duration", "", "workout_duration_minutes"),
        _Mapping("workout_distance", "", "distance_meter", MetricUnit.METER),
    ),
}

#: Columns that carry the moment a record belongs to.
#: The moment a record of each kind belongs to, in order of preference.
#:
#: Per kind rather than one list, because every file carries the *cycle* it belongs to
#: as well as its own start: `Trainings.csv` has both `Startzeit des Trainings` and
#: `Startzeit des Zyklus`, and a single ordering cannot be right for both a workout and
#: the cycle row it sits beside. Getting this wrong is silent and total — a workout keyed
#: on its cycle gives every session in a day the same timestamp, so the same
#: `idempotency_key`, and Core keeps the first and discards the rest as duplicates. One
#: workout per day, no error anywhere.
TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "cycle": ("cycle start time", "startzeit des zyklus", "start time"),
    "recovery": ("cycle start time", "startzeit des zyklus", "start time"),
    "sleep": (
        "sleep onset",
        "beginn des schlafs",
        "cycle start time",
        "startzeit des zyklus",
        "start time",
    ),
    "workout": (
        "workout start time",
        "startzeit des trainings",
        "cycle start time",
        "startzeit des zyklus",
        "start time",
    ),
}


class ArchiveTooLarge(RuntimeError):
    """The upload, or what it expands to, exceeds what we are willing to read."""


class ArchiveUnreadable(RuntimeError):
    """Not a ZIP, or not one containing anything we recognise."""


def _kinds_for(filename: str) -> tuple[str, ...]:
    """Which record kinds a CSV feeds, longest name first so `sleeps` beats `sleep`."""
    stem = filename.rsplit("/", 1)[-1].lower().removesuffix(".csv")
    for name in sorted(CSV_KINDS, key=len, reverse=True):
        if stem == name or stem.startswith(name):
            return CSV_KINDS[name]
    return ()


def _number(raw: str) -> float | None:
    text = raw.strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_export(data: bytes) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(kind, record)`` pairs the Whoop transformer can consume.

    Records come out flat, with the field names ``EXPORT_METRICS`` expects, and the
    caller passes that table to `transform_whoop_records`.
    """
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveTooLarge(
            f"The archive is larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB."
        )

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveUnreadable("That file is not a ZIP archive.") from exc

    members = [
        info for info in archive.infolist() if not info.is_dir() and _kinds_for(info.filename)
    ]
    if not members:
        raise ArchiveUnreadable(
            "No recognisable Whoop CSV was found in the archive. "
            f"Expected one of: {', '.join(sorted(CSV_KINDS))}."
        )

    extracted = 0
    rows = 0
    for info in members:
        kinds = _kinds_for(info.filename)

        with archive.open(info) as handle:
            # Decoded incrementally and counted as it comes: `info.file_size` is a
            # number the archive claims about itself, and a zip bomb lies about it.
            text = io.TextIOWrapper(handle, encoding="utf-8-sig", errors="replace")
            reader = csv.DictReader(text)
            for row in reader:
                extracted += sum(len(value or "") for value in row.values())
                if extracted > MAX_EXTRACTED_BYTES:
                    raise ArchiveTooLarge("The archive expands to more than we will read.")
                rows += 1
                if rows > MAX_ROWS:
                    raise ArchiveTooLarge(f"The archive holds more than {MAX_ROWS} rows.")

                # Per kind: the record differs between them only in which column its
                # timestamp came from, and that is exactly the part that must differ.
                for kind in kinds:
                    record = _to_record(row, kind)
                    if record is not None:
                        yield kind, record


def _to_record(row: dict[str, str], kind: str) -> dict[str, Any] | None:
    """One CSV row as the flat record shape the transformer reads, for one record kind."""
    normalised = {(key or "").strip().lower(): (value or "") for key, value in row.items()}

    timestamp = ""
    for column in TIMESTAMP_COLUMNS.get(kind, ()):
        if normalised.get(column, "").strip():
            timestamp = normalised[column].strip()
            break
    if not timestamp:
        # No timestamp means no deterministic idempotency key, so the row cannot be
        # deduplicated and would re-import forever. Skipped rather than stamped now().
        return None

    record: dict[str, Any] = {"start": timestamp}
    for column, value in normalised.items():
        field = COLUMN_FIELDS.get(column)
        if field is None:
            # Kept under the column's own name so the field report can name it.
            # Nesting them under one `_unmapped` object produced a single opaque
            # row and lost the very thing the report is for.
            record[column] = value
            continue
        number = _number(value)
        if number is not None:
            record[field] = number
    return record
