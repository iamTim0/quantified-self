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

        rec_dp = next(dp for dp in dps if dp["metric_type"] == "recovery_score")
        self.assertEqual(rec_dp["tenant_id"], "tenant-456")
        self.assertEqual(rec_dp["value"], 88.0)
        self.assertEqual(rec_dp["metadata"]["source_type"], "whoop")
        self.assertEqual(rec_dp["metadata"]["whoop_id"], "rec-101")
        self.assertEqual(len(rec_dp["idempotency_key"]), 64)

if __name__ == "__main__":
    unittest.main()
