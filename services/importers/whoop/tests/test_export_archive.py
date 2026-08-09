"""Reading the emailed Whoop export.

The properties worth pinning: an export produces the *same* metric names a polled
sync does, its units are converted from what the export actually uses rather than
from what the API uses, and an untrusted archive cannot make us read forever.

Maps to Fizzbee Invariants:
- IdempotencyKeyDeterministic
- NoDuplicateRecords
"""

import io
import zipfile

import pytest
from whoop_importer.export_archive import (
    EXPORT_METRICS,
    ArchiveTooLarge,
    ArchiveUnreadable,
    read_export,
)
from whoop_importer.transformer import METRICS, transform_whoop_records

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"

CYCLES_CSV = (
    "Cycle start time,Day Strain,Energy burned (cal),Average HR (bpm),Sleep debt (min)\n"
    "2026-08-05 06:00:00,14.2,2450,62,35\n"
)


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _points(archive: bytes) -> list[dict]:
    points: list[dict] = []
    for kind, record in read_export(archive):
        points.extend(
            transform_whoop_records(
                kind,
                [record],
                TENANT,
                SOURCE,
                require_scored=False,
                mappings=EXPORT_METRICS,
            )
        )
    return points


def test_an_export_produces_the_same_metric_names_as_the_api():
    """Rule 15: one quantity, one name, whichever way it arrived."""
    api_names = {m.metric_type for mappings in METRICS.values() for m in mappings}
    export_names = {m.metric_type for mappings in EXPORT_METRICS.values() for m in mappings}

    assert export_names == api_names


def test_cycle_rows_become_data_points():
    values = {p["metric_type"]: p["value"] for p in _points(_archive({"cycles.csv": CYCLES_CSV}))}

    assert values["whoop_strain"] == 14.2
    assert values["heart_rate_average"] == 62


def test_export_energy_is_read_as_kilocalories():
    """The export column says "cal" and means kcal; the API sends kilojoules.

    Routed through the API's mapping this figure would be divided by 4.184 —
    2450 would become 586 — and nothing would look wrong.
    """
    values = {p["metric_type"]: p["value"] for p in _points(_archive({"cycles.csv": CYCLES_CSV}))}

    assert values["energy_total"] == 2450


def test_rows_are_not_dropped_for_having_no_score_state():
    """The CSV has no such column; every row in an export is already final.

    The API guard would otherwise discard the entire file without a word.
    """
    assert _points(_archive({"cycles.csv": CYCLES_CSV})) != []


def test_the_same_export_twice_yields_the_same_keys():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic"""
    archive = _archive({"cycles.csv": CYCLES_CSV})

    first = [p["idempotency_key"] for p in _points(archive)]
    second = [p["idempotency_key"] for p in _points(archive)]

    assert first == second


def test_a_row_without_a_timestamp_is_skipped():
    """No timestamp means no deterministic key, so it would re-import forever."""
    csv_body = "Cycle start time,Day Strain\n,14.2\n"

    assert _points(_archive({"cycles.csv": csv_body})) == []


def test_a_file_that_is_not_a_zip_is_refused():
    with pytest.raises(ArchiveUnreadable):
        list(read_export(b"this is not a zip"))


def test_an_archive_with_nothing_recognisable_says_so():
    with pytest.raises(ArchiveUnreadable, match="recognisable"):
        list(read_export(_archive({"readme.txt": "hello"})))


def test_an_oversized_archive_is_refused_before_it_is_opened():
    """A zip bomb's declared size is a claim by whoever built it."""
    from whoop_importer import export_archive

    with pytest.raises(ArchiveTooLarge):
        list(read_export(b"x" * (export_archive.MAX_ARCHIVE_BYTES + 1)))


def test_expansion_is_bounded_while_it_is_read(monkeypatch):
    """The honest measurement is how many bytes actually come out."""
    from whoop_importer import export_archive

    monkeypatch.setattr(export_archive, "MAX_EXTRACTED_BYTES", 10)
    body = "Cycle start time,Day Strain\n" + "".join(
        f"2026-08-{day:02d} 06:00:00,14.2\n" for day in range(1, 28)
    )

    with pytest.raises(ArchiveTooLarge):
        list(read_export(_archive({"cycles.csv": body})))


def test_recovery_columns_in_the_cycle_file_are_not_lost():
    """They live in physiological_cycles.csv, not a file of their own.

    Yielding that row under `cycle` alone dropped recovery score, resting heart
    rate, HRV, SpO2 and skin temperature — five metrics, silently, while a
    set-comparison test on the two mapping tables still passed.
    """
    body = (
        "Cycle start time,Day Strain,Recovery score %,Resting heart rate (bpm),"
        "Heart rate variability (ms)\n"
        "2026-08-05 06:00:00,14.2,71,52,88\n"
    )
    values = {
        p["metric_type"]: p["value"] for p in _points(_archive({"physiological_cycles.csv": body}))
    }

    assert values["whoop_strain"] == 14.2
    assert values["whoop_recovery_score"] == 71
    assert values["heart_rate_resting"] == 52
    assert values["hrv_rmssd"] == 88


def test_unmapped_columns_are_reported_by_name():
    """One row per column, not one opaque object for all of them."""
    from shared_schemas import FieldReportCollector

    body = "Cycle start time,Day Strain,Sleep debt (min)\n2026-08-05 06:00:00,14.2,35\n"
    report = FieldReportCollector()
    for kind, record in read_export(_archive({"cycles.csv": body})):
        transform_whoop_records(
            kind, [record], TENANT, SOURCE,
            require_scored=False, mappings=EXPORT_METRICS, report=report,
        )

    unmapped = {s.path for s in report.build().unmapped}
    assert any(path.endswith("sleep debt (min)") for path in unmapped), unmapped
