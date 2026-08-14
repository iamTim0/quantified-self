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
from shared_schemas.metrics import CANONICAL_KEYS
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


def test_an_export_never_spells_a_quantity_differently_from_the_api():
    """Rule 15: one quantity, one name, whichever way it arrived.

    Covering, not equal. An export reaches further back than the API window and states
    things the API's score objects do not — the four sleep stages, a session's duration —
    so it is legitimately the larger set. What it must never do is give a quantity both
    paths carry two different names, because that is what makes one quantity two series.
    """
    api_names = {m.metric_type for mappings in METRICS.values() for m in mappings}
    export_names = {m.metric_type for mappings in EXPORT_METRICS.values() for m in mappings}

    assert api_names <= export_names, api_names - export_names
    # And nothing invented on the way: every name is the registry's.
    assert export_names <= set(CANONICAL_KEYS), export_names - set(CANONICAL_KEYS)


#: Verbatim from a German account's export: Whoop localises the file names and the column
#: headers to the account's language, and an account's language must not decide whether
#: somebody can import their own data.
GERMAN_SLEEP_CSV = (
    "Startzeit des Zyklus,Beginn des Schlafs,Schlafleistung %,"
    "Atemfrequenz (Atemzüge/Min.),Schlafdauer (Min.),Dauer im Bett (Min.),"
    "Dauer des Leichtschlafs (Min.),Dauer des Tiefschlafs (Min.),"
    "Dauer des REM-Schlafs (Min.),Dauer des Aufwachens (Min.),Schlafeffizienz %\n"
    "2026-08-09 23:45:11,2026-08-09 23:45:11,78,14.9,457,506,204,95,158,49,90\n"
)

GERMAN_WORKOUTS_CSV = (
    "Startzeit des Zyklus,Startzeit des Trainings,Dauer (Min.),Name der Aktivität,"
    "Aktivitätsbelastung,Verbrannte Energie (cal),Max HF (Schläge pro Minute),"
    "Durchschnittliche HF (Schläge pro Minute)\n"
    "2026-08-09 23:45:11,2026-08-10 18:37:37,4,Radfahren,4.3,30.0,138,118\n"
    "2026-08-09 23:45:11,2026-08-10 20:10:00,32,Laufen,9.1,310.0,171,149\n"
)


def test_a_german_export_is_read():
    """`Schlaf.csv` and `Trainings.csv` were refused outright: no recognisable CSV.

    Whoop names the files and the columns in the account's language, so the whole
    archive was unreadable for a German account — the provider's vocabulary, which is
    this table's business to know.
    """
    values = {
        p["metric_type"]: p["value"]
        for p in _points(
            _archive({"Schlaf.csv": GERMAN_SLEEP_CSV, "Trainings.csv": GERMAN_WORKOUTS_CSV})
        )
    }

    assert values["whoop_sleep_performance"] == 78
    assert values["respiratory_rate"] == 14.9
    # The whole night, not only its score: nine columns, all of them registry metrics.
    assert values["sleep_duration"] == 457
    assert values["sleep_duration_in_bed"] == 506
    assert values["sleep_duration_light"] == 204
    assert values["sleep_duration_deep"] == 95
    assert values["sleep_duration_rem"] == 158
    assert values["sleep_duration_awake"] == 49
    assert values["workout_duration"] == 32
    assert values["workout_heart_rate_max"] == 171


def test_two_workouts_in_one_day_stay_two_workouts():
    """Verifies Fizzbee Invariant: NoDuplicateRecords.

    Every row carries the cycle it belongs to as well as its own start. Keyed on the
    cycle, both of a day's sessions hash identically and Core keeps the first — one
    workout a day, silently, with nothing anywhere reporting a loss.
    """
    points = _points(_archive({"Trainings.csv": GERMAN_WORKOUTS_CSV}))
    strains = [p for p in points if p["metric_type"] == "whoop_workout_strain"]

    assert sorted(p["value"] for p in strains) == [4.3, 9.1]
    assert len({p["idempotency_key"] for p in strains}) == 2


def test_cycle_rows_become_data_points():
    values = {p["metric_type"]: p["value"] for p in _points(_archive({"cycles.csv": CYCLES_CSV}))}

    assert values["whoop_strain"] == 14.2
    assert values["heart_rate_average"] == 62


def test_export_energy_is_read_as_kilocalories():
    """The export column says "cal" and means kcal; the API sends kilojoules.

    Routed through the API's mapping this figure would be divided by 4.184 —
    2450 would become 586 — and nothing would look wrong.
    """
    points = _points(_archive({"cycles.csv": CYCLES_CSV}))
    values = {p["metric_type"]: p["value"] for p in points}

    assert values["energy_total"] == 2450
    energy = next(p for p in points if p["metric_type"] == "energy_total")
    assert energy["metadata"]["provider_value"] == 2450
    assert energy["metadata"]["units"] == "kcal"


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


def test_a_physiological_cycle_row_emits_each_metric_once():
    """Verifies Fizzbee Invariant: NoDuplicateRecords.

    Recovery columns are part of the physiological-cycle row. They must be mapped
    by the cycle mapping once, rather than causing the same CSV row to be replayed
    through a second recovery mapping.
    """
    body = (
        "Cycle start time,Recovery score %,Heart rate variability (ms)\n"
        "2026-08-05 06:00:00,71,88\n"
    )
    points = _points(_archive({"physiological_cycles.csv": body}))

    assert len(points) == 2
    assert len({point["idempotency_key"] for point in points}) == 2


def test_real_english_export_headers_are_supported():
    """Actual WHOOP English headers become metrics or metadata without translation."""
    from shared_schemas import FieldReportCollector

    body = (
        "cycle start time,sleep onset,deep sleep / SWS duration (min),nap flag,"
        "sleep performance %\n"
        "2026-08-05 06:00:00,2026-08-05 23:00:00,95,True,78\n"
    )
    report = FieldReportCollector()
    points: list[dict] = []
    for kind, record in read_export(_archive({"sleeps.csv": body})):
        points.extend(
            transform_whoop_records(
                kind,
                [record],
                TENANT,
                SOURCE,
                require_scored=False,
                mappings=EXPORT_METRICS,
                report=report,
            )
        )

    values = {point["metric_type"]: point for point in points}
    assert values["sleep_duration_deep"]["value"] == 95
    assert values["whoop_sleep_performance"]["value"] == 78
    assert values["sleep_duration_deep"]["metadata"]["sleep_nap_flag"] is True
    assert report.build().unmapped == []


def test_journal_entries_are_reported_without_storing_their_contents():
    """Verifies Fizzbee Invariant: ArchiveIsNotRetained."""
    from shared_schemas import FieldReportCollector

    report = FieldReportCollector()
    records = list(
        read_export(
            _archive(
                {
                    "journal_entries.csv": (
                        "cycle start time,question text,answered yes,notes\n"
                        "2026-08-05 06:00:00,Did you sleep well?,True,private note\n"
                    )
                }
            )
        )
    )
    assert [kind for kind, _ in records] == ["journal"]

    transform_whoop_records(
        "journal",
        [records[0][1]],
        TENANT,
        SOURCE,
        require_scored=False,
        mappings=EXPORT_METRICS,
        report=report,
    )
    paths = {s.path for s in report.build().unmapped}
    assert "journal.question text" in paths
    assert "journal.answered yes" in paths
    assert "journal.notes" in paths


def test_repeated_sleep_columns_are_carried_without_double_counting():
    """A repeated sleep summary is metadata on the cycle point, not a second total."""
    from shared_schemas import FieldReportCollector

    body = "Cycle start time,Day Strain,Sleep debt (min)\n2026-08-05 06:00:00,14.2,35\n"
    report = FieldReportCollector()
    points: list[dict] = []
    for kind, record in read_export(_archive({"cycles.csv": body})):
        points.extend(transform_whoop_records(
            kind, [record], TENANT, SOURCE,
            require_scored=False, mappings=EXPORT_METRICS, report=report,
        ))

    strain = next(point for point in points if point["metric_type"] == "whoop_strain")
    assert strain["metadata"]["whoop_sleep_debt"] == 35
    paths = {s.path for s in report.build().mapped}
    assert "cycle.sleep_debt_minutes" in paths
    assert report.build().unmapped == []


def test_reported_whoop_fields_are_usable_as_metrics_or_metadata():
    """Every field from the provider report is stored or carried with its point."""
    from shared_schemas import FieldReportCollector

    cycles = (
        "Startzeit des Zyklus,Endzeit des Zyklus,Zeitzone des Zyklus,Beginn des Schlafs,"
        "Beginn des Aufwachens,Schlafbedarf (min.),Schlafbeständigkeit %,Schlafdefizit (min.),"
        "HRV RMSSD (ms),Max HR (bpm),Recovery score %,Respiratory rate (rpm),"
        "Resting heart rate (bpm),Skin temp (celsius),Sleep awake (min.),"
        "Sleep deep (min.),Sleep duration (min.),Sleep efficiency %,Sleep in bed (min.),"
        "Sleep light (min.),Sleep performance %,Sleep rem (min.),Blood oxygen %\n"
        "2026-08-05 06:00:00,2026-08-06 06:00:00,UTC,2026-08-05 23:00:00,"
        "2026-08-06 07:00:00,480,82,20,65,181,77,14.5,52,36.4,40,90,450,88,"
        "500,210,76,100,98\n"
    )
    sleeps = (
        "Startzeit des Zyklus,Beginn des Schlafs,Nickerchen,Schlafbedarf (min.),"
        "Schlafbeständigkeit %,Schlafdefizit (min.),Sleep awake (min.),"
        "Sleep deep (min.),Sleep duration (min.),Sleep efficiency %,Sleep in bed (min.),"
        "Sleep light (min.),Sleep performance %,Sleep rem (min.)\n"
        "2026-08-05 06:00:00,2026-08-05 23:00:00,1,480,82,20,40,90,450,88,"
        "500,210,76,100\n"
    )
    workouts = (
        "Startzeit des Zyklus,Startzeit des Trainings,Endzeit des Trainings,"
        "Endzeit des Zyklus,Zeitzone des Zyklus,GPS aktiviert,Name der Aktivität,"
        "HF-Zone 1 %,HF-Zone 2 %,HF-Zone 3 %,HF-Zone 4 %,HF-Zone 5 %,"
        "Aktivitätsbelastung,Dauer (Min.),Durchschnittliche HF (Schläge pro Minute)\n"
        "2026-08-05 06:00:00,2026-08-05 18:00:00,2026-08-05 18:45:00,"
        "2026-08-06 06:00:00,UTC,Ja,Laufen,10,20,30,25,15,8.1,45,145\n"
    )

    report = FieldReportCollector()
    points: list[dict] = []
    for kind, record in read_export(
        _archive({
            "physiologische_zyklen.csv": cycles,
            "Schlaf.csv": sleeps,
            "Trainings.csv": workouts,
        })
    ):
        points.extend(
            transform_whoop_records(
                kind,
                [record],
                TENANT,
                SOURCE,
                require_scored=False,
                mappings=EXPORT_METRICS,
                report=report,
            )
        )

    assert report.build().unmapped == []
    metric_names = {point["metric_type"] for point in points}
    assert {
        "hrv_rmssd",
        "heart_rate_max",
        "whoop_recovery_score",
        "respiratory_rate",
        "heart_rate_resting",
        "skin_temperature",
        "sleep_duration_awake",
        "sleep_duration_deep",
        "sleep_duration",
        "sleep_efficiency",
        "sleep_duration_in_bed",
        "sleep_duration_light",
        "whoop_sleep_performance",
        "sleep_duration_rem",
        "blood_oxygen",
        "whoop_sleep_need",
        "whoop_sleep_consistency",
        "whoop_sleep_debt",
        "sleep_nap_count",
        "workout_heart_rate_zone_1",
        "workout_heart_rate_zone_2",
        "workout_heart_rate_zone_3",
        "workout_heart_rate_zone_4",
        "workout_heart_rate_zone_5",
    } <= metric_names

    workout = next(point for point in points if point["metric_type"] == "workout_duration")
    assert workout["metadata"]["activity_name"] == "Laufen"
    assert workout["metadata"]["gps_enabled"] is True
    assert workout["metadata"]["workout_start_time"] == "2026-08-05 18:00:00"
    assert workout["metadata"]["workout_end_time"] == "2026-08-05 18:45:00"
    cycle = next(point for point in points if point["metric_type"] == "whoop_recovery_score")
    assert cycle["metadata"]["sleep_duration"] == 450
    assert not any(
        point["metric_type"] == "sleep_duration" and point["timestamp"] == "2026-08-05 06:00:00"
        for point in points
    )
