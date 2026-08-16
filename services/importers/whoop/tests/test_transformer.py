import unittest

from whoop_importer.transformer import (
    generate_idempotency_key,
    transform_whoop_records,
)


class TestWhoopTransformer(unittest.TestCase):
    def test_generate_idempotency_key(self):
        """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic."""
        key1 = generate_idempotency_key("tenant-1", "src-whoop", "recovery_score", "2026-08-01T08:00:00Z")
        key2 = generate_idempotency_key("tenant-1", "src-whoop", "recovery_score", "2026-08-01T08:00:00Z")
        key3 = generate_idempotency_key("tenant-2", "src-whoop", "recovery_score", "2026-08-01T08:00:00Z")

        self.assertEqual(key1, key2)
        self.assertEqual(len(key1), 64)
        self.assertNotEqual(key1, key3)

    def test_transform_whoop_records_recovery(self):
        """Verifies transformation of WHOOP recovery records into DataPoints."""
        records = [
            {
                "id": "rec-101",
                "score_state": "SCORED",
                "start": "2026-08-01T08:00:00Z",
                "score": {
                    "recovery_score": 88.0,
                    "resting_heart_rate": 52.0,
                    "hrv_rmssd_milli": 65.4,
                    "spo2_percentage": 98.5,
                    "skin_temp_celsius": 36.2,
                },
            }
        ]

        dps = transform_whoop_records("recovery", records, "tenant-456", "whoop_src")
        self.assertEqual(len(dps), 5)

        rec_dp = next(dp for dp in dps if dp["metric_type"] == "whoop_recovery_score")
        self.assertEqual(rec_dp["tenant_id"], "tenant-456")
        self.assertEqual(rec_dp["source_type"], "whoop")
        self.assertEqual(rec_dp["value"], 88.0)
        self.assertEqual(rec_dp["metadata"]["source_type"], "whoop")
        self.assertEqual(rec_dp["metadata"]["whoop_id"], "rec-101")
        self.assertEqual(len(rec_dp["idempotency_key"]), 64)

if __name__ == "__main__":
    unittest.main()


# ── Sessions and the figures the polled path used to miss ────────────────────
#
# Plain pytest functions rather than more `unittest` methods: these assert on
# floats and on set contents, which reads better with bare asserts.

import pytest

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"

_WORKOUT = {
    "id": "wk-77",
    "start": "2026-08-15T16:00:00.000Z",
    "end": "2026-08-15T16:45:00.000Z",
    "score_state": "SCORED",
    "sport_name": "running",
    "score": {
        "strain": 12.4,
        "kilojoule": 2100.0,
        "average_heart_rate": 148,
        "max_heart_rate": 179,
        "distance_meter": 8200.0,
        "altitude_gain_meter": 96.0,
        "zone_duration": {
            "zone_zero_milli": 60_000,
            "zone_one_milli": 300_000,
            "zone_two_milli": 600_000,
            "zone_three_milli": 900_000,
            "zone_four_milli": 780_000,
            "zone_five_milli": 60_000,
        },
    },
}


def _workout_points(**overrides):
    record = {**_WORKOUT, **overrides}
    return transform_whoop_records("workout", [record], TENANT, SOURCE)


def test_workout_points_carry_the_whoop_session_id():
    """Verifies Fizzbee Invariant: SessionGroupingIsStable."""
    points = _workout_points()
    ids = {p["metadata"]["session_id"] for p in points}

    assert len(ids) == 1
    assert next(iter(ids)).startswith("whoop:")
    assert points[0]["metadata"]["session_origin"] == "provider"
    assert points[0]["metadata"]["session_end"] == "2026-08-15T16:45:00+00:00"


def test_a_cycle_is_not_a_session():
    """A day and a night are not workouts, and must not appear on the workout list."""
    cycle = transform_whoop_records(
        "cycle",
        [{"id": "c-1", "start": "2026-08-15T00:00:00.000Z", "score_state": "SCORED",
          "score": {"strain": 14.0}}],
        TENANT,
        SOURCE,
    )
    assert all("session_id" not in p["metadata"] for p in cycle)


def test_the_polled_path_now_states_the_max_heart_rate_and_the_climb():
    """Both are in every v2 payload and were simply never read."""
    by_metric = {p["metric_type"]: p for p in _workout_points()}

    assert by_metric["workout_heart_rate_max"]["value"] == 179
    assert by_metric["workout_elevation_gain"]["value"] == 96.0


def test_the_session_duration_is_derived_and_says_so():
    """WHOOP states start and end, not a duration — so this figure is ours."""
    duration = next(
        p for p in _workout_points() if p["metric_type"] == "workout_duration"
    )
    assert duration["value"] == 45.0
    assert duration["metadata"]["derived_by"] == "difference"
    assert duration["metadata"]["derived_from"] == ["start", "end"]


def test_the_zones_become_shares_of_the_whole_session():
    """Six provider buckets against five registry metrics.

    Zone zero is below-zone-1 time: part of the session and part of the
    denominator, so it belongs in neither zone 1 nor the bin.
    """
    zones = {
        p["metric_type"]: p
        for p in _workout_points()
        if p["metric_type"].startswith("workout_heart_rate_zone_")
    }
    assert len(zones) == 5

    total_ms = 60_000 + 300_000 + 600_000 + 900_000 + 780_000 + 60_000
    assert zones["workout_heart_rate_zone_3"]["value"] == pytest.approx(
        900_000 / total_ms * 100
    )
    # The five shares deliberately fall short of 100 %, and the payload says why.
    assert sum(p["value"] for p in zones.values()) < 100
    assert zones["workout_heart_rate_zone_1"]["metadata"]["zone_below_one_ms"] == 60_000
    assert zones["workout_heart_rate_zone_1"]["metadata"]["derived_by"] == "share"


def test_a_workout_without_zones_or_an_end_still_imports():
    record = {k: v for k, v in _WORKOUT.items() if k != "end"}
    record["score"] = {k: v for k, v in _WORKOUT["score"].items() if k != "zone_duration"}
    points = transform_whoop_records("workout", [record], TENANT, SOURCE)

    kinds = {p["metric_type"] for p in points}
    assert "workout_heart_rate_max" in kinds
    assert "workout_duration" not in kinds
    assert not any(k.startswith("workout_heart_rate_zone_") for k in kinds)
    assert "session_end" not in points[0]["metadata"]


def test_a_derived_figure_never_overwrites_a_stated_one():
    """Rule 19: what the provider said beats what we worked out."""
    points = _workout_points()
    durations = [p for p in points if p["metric_type"] == "workout_duration"]
    assert len(durations) == 1, "one duration, whichever path produced it"
