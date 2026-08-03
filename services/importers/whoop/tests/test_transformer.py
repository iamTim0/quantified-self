from whoop_importer.transformer import transform_record


def test_recovery_is_deterministic():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic."""
    record = {"cycle_id": 4, "start": "2026-08-01T08:00:00Z", "score_state": "SCORED", "score": {"recovery_score": 81, "hrv_rmssd_milli": 42.5}}
    first = transform_record("recovery", record, "tenant", "source")
    assert first == transform_record("recovery", record, "tenant", "source")
    assert {point["metric_type"] for point in first} == {"recovery_score", "hrv_rmssd_milli"}
    assert all(len(point["idempotency_key"]) == 64 for point in first)


def test_pending_score_is_ignored():
    """Verifies pending WHOOP records cannot publish incomplete measurements."""
    assert transform_record("sleep", {"score_state": "PENDING_SCORE", "start": "2026-08-01T00:00:00Z"}, "t", "s") == []
