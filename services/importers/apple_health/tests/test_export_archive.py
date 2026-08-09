"""Reading Apple's own `export.zip`.

The properties worth pinning: an archive produces the *same* metric names the push
path does, sleep stages stated as intervals become durations, GPS routes survive, the
categories this platform does not store are named rather than silently dropped, and an
untrusted archive cannot make us read forever.

Maps to Fizzbee Invariants:
- IdempotencyKeyDeterministic
- NoDuplicateRecords
"""

import io
import zipfile

import pytest
from apple_health_importer.export_archive import (
    ArchiveTooLarge,
    ArchiveUnreadable,
    provider_name,
    read_export,
)
from apple_health_importer.transformer import transform_health_auto_export_json
from shared_schemas import FieldReportCollector

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"

EXPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_GB">
 <ExportDate value="2026-08-09 10:00:00 +0200"/>
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count"
         startDate="2026-08-05 06:00:00 +0200" endDate="2026-08-05 07:00:00 +0200" value="1240"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min"
         startDate="2026-08-05 06:30:00 +0200" endDate="2026-08-05 06:30:10 +0200" value="61"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureSystolic" sourceName="Cuff" unit="mmHg"
         startDate="2026-08-05 08:00:00 +0200" endDate="2026-08-05 08:00:00 +0200" value="118"/>
 <Record type="HKQuantityTypeIdentifierDistanceWalkingRunning" sourceName="iPhone" unit="km"
         startDate="2026-08-05 06:00:00 +0200" endDate="2026-08-05 07:00:00 +0200" value="1.4"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch"
         startDate="2026-08-05 01:00:00 +0200" endDate="2026-08-05 02:30:00 +0200"
         value="HKCategoryValueSleepAnalysisAsleepDeep"/>
 <Record type="HKCategoryTypeIdentifierAbdominalCramps" sourceName="iPhone"
         startDate="2026-08-05 09:00:00 +0200" endDate="2026-08-05 09:00:00 +0200"
         value="HKCategoryValueSeverityMild"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="45" durationUnit="min"
          totalDistance="8.2" totalDistanceUnit="km" totalEnergyBurned="450"
          totalEnergyBurnedUnit="kcal" sourceName="Watch"
          startDate="2026-08-05 17:00:00 +0200" endDate="2026-08-05 17:45:00 +0200">
  <MetadataEntry key="HKIndoorWorkout" value="0"/>
  <WorkoutStatistics type="HKQuantityTypeIdentifierHeartRate" average="141" maximum="176"
                     unit="count/min"/>
  <WorkoutRoute sourceName="Watch" startDate="2026-08-05 17:00:00 +0200">
   <FileReference path="/workout-routes/route_2026-08-05_5.00pm.gpx"/>
  </WorkoutRoute>
 </Workout>
 <ClinicalRecord type="Immunization" sourceName="Health"/>
</HealthData>
"""

ROUTE_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx xmlns="http://www.topografix.com/GPX/1/1" creator="Apple Health Export">
 <trk><trkseg>
  <trkpt lon="13.4050" lat="52.5200"><ele>34.2</ele><time>2026-08-05T15:00:00Z</time>
   <extensions><speed>3.1</speed><hAcc>4.0</hAcc></extensions></trkpt>
  <trkpt lon="13.4060" lat="52.5210"><ele>35.0</ele><time>2026-08-05T15:00:10Z</time></trkpt>
 </trkseg></trk>
</gpx>
"""


def _archive(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _points(files: dict[str, str] | None = None) -> tuple[list[dict], FieldReportCollector]:
    data = _archive(
        files
        or {
            "apple_health_export/export.xml": EXPORT_XML,
            "apple_health_export/workout-routes/route_2026-08-05_5.00pm.gpx": ROUTE_GPX,
        }
    )
    report = FieldReportCollector()
    points = list(
        read_export(io.BytesIO(data), tenant_id=TENANT, source_id=SOURCE, report=report)
    )
    return points, report


def _by_metric(points: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for point in points:
        grouped.setdefault(point["metric_type"], []).append(point)
    return grouped


def test_healthkit_identifiers_become_the_names_the_push_path_uses():
    """Rule 15: one quantity, one name, whichever way it arrived."""
    assert provider_name("HKQuantityTypeIdentifierStepCount") == "step_count"
    assert provider_name("HKQuantityTypeIdentifierVO2Max") == "vo2_max"
    assert provider_name("HKWorkoutActivityTypeRunning") == "running"

    archive_points, _ = _points()
    pushed = transform_health_auto_export_json(
        {"data": {"metrics": [
            {"name": "step_count", "units": "count",
             "data": [{"date": "2026-08-05 06:00:00 +0200", "qty": 1240}]}
        ]}},
        tenant_id=TENANT,
        source_id=SOURCE,
    )
    archive_steps = _by_metric(archive_points)["steps"][0]
    assert archive_steps["metric_type"] == pushed[0]["metric_type"]
    # Same connector, same metric, same moment -- so the same key, and the second
    # import of a reading already held writes nothing.
    assert archive_steps["idempotency_key"] == pushed[0]["idempotency_key"]


def test_quantities_arrive_converted_and_with_the_reading_that_was_reported():
    points, _ = _points()
    grouped = _by_metric(points)

    assert grouped["steps"][0]["value"] == 1240
    assert grouped["heart_rate"][0]["value"] == 61
    assert grouped["blood_pressure_systolic"][0]["value"] == 118
    # The archive states kilometres; the registry stores kilometres, so the number
    # stands, and the reported figure is kept either way.
    assert grouped["distance"][0]["metadata"]["provider_value"] == 1.4


def test_a_sleep_stage_is_an_interval_and_becomes_a_duration():
    """The XML gives sleep as two moments; the registry wants minutes."""
    points, _ = _points()
    deep = _by_metric(points)["sleep_duration_deep"][0]
    assert deep["value"] == pytest.approx(90.0)
    assert deep["metadata"]["sleep_stage"] == "deep"


def test_workout_totals_and_statistics_both_arrive():
    points, _ = _points()
    grouped = _by_metric(points)

    assert grouped["workout_duration"][0]["value"] == pytest.approx(45.0)
    assert grouped["workout_distance"][0]["value"] == pytest.approx(8.2)
    assert grouped["workout_energy"][0]["value"] == pytest.approx(450.0)
    # These live in a child element in current exports, not in the workout's own
    # attributes, so reading only the attributes loses both.
    assert grouped["workout_heart_rate_average"][0]["value"] == pytest.approx(141.0)
    assert grouped["workout_heart_rate_max"][0]["value"] == pytest.approx(176.0)


def test_the_route_becomes_location_points_with_the_workout_attached():
    points, _ = _points()
    route = _by_metric(points)["location_point"]

    assert len(route) == 2
    assert route[0]["metadata"]["latitude"] == pytest.approx(52.5200)
    assert route[0]["metadata"]["longitude"] == pytest.approx(13.4050)
    assert route[0]["metadata"]["altitude"] == pytest.approx(34.2)
    assert route[0]["metadata"]["speed"] == pytest.approx(3.1)
    assert route[0]["metadata"]["workout_name"] == "running"


def test_what_is_not_stored_is_named_rather_than_dropped():
    """The scope decision is visible in the Data Quality Center, not only in the code."""
    points, report = _points()
    stored = {point["metric_type"] for point in points}
    unmapped = {sighting.path for sighting in report.build().unmapped}

    assert not any(name.startswith("apple_health_abdominal") for name in stored)
    assert "export.Record.abdominal_cramps" in unmapped
    assert "export.ClinicalRecord" in unmapped
    assert "export.Workout.metadata.HKIndoorWorkout" in unmapped


def test_the_report_never_carries_a_value():
    """A field report records shape. A blood pressure is not a shape."""
    _, report = _points()
    serialised = report.build().model_dump_json()

    assert "118" not in serialised
    assert "52.52" not in serialised


def test_an_archive_without_an_export_is_refused_with_something_to_do_about_it():
    with pytest.raises(ArchiveUnreadable) as excinfo:
        list(read_export(io.BytesIO(_archive({"readme.txt": "nothing here"})),
                         tenant_id=TENANT, source_id=SOURCE))
    assert "export.xml" in str(excinfo.value)


def test_not_a_zip_is_refused():
    with pytest.raises(ArchiveUnreadable):
        list(read_export(io.BytesIO(b"this is not a zip"), tenant_id=TENANT, source_id=SOURCE))


def test_an_archive_that_expands_without_end_is_refused(monkeypatch):
    """A zip bomb's declared size is its own claim; only what comes out can be counted."""
    monkeypatch.setattr("apple_health_importer.export_archive.MAX_EXTRACTED_BYTES", 64)
    data = _archive({"apple_health_export/export.xml": EXPORT_XML})

    with pytest.raises(ArchiveTooLarge):
        list(read_export(io.BytesIO(data), tenant_id=TENANT, source_id=SOURCE))
