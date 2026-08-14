"""Tests for pre-publish metric aggregation."""

from shared_schemas import aggregate_events, aggregate_stream
from shared_schemas.metrics import IngestResolution

TENANT = "00000000-0000-0000-0000-000000000001"
SOURCE = "11111111-1111-1111-1111-111111111111"


def _event(timestamp: str, value: float, **metadata: object) -> dict:
    return {
        "tenant_id": TENANT,
        "source_id": SOURCE,
        "metric_type": "heart_rate",
        "timestamp": timestamp,
        "value": value,
        "metadata": {"units": "bpm", "provider_value": value, **metadata},
        "idempotency_key": "old-key",
        "source_type": "apple_health",
    }


def test_continuous_values_are_collapsed_to_one_minute_with_provenance():
    """Verifies Fizzbee Invariant: NoDuplicateData."""
    result = aggregate_events(
        [
            _event("2026-08-14T10:00:01+00:00", 60),
            _event("2026-08-14T10:00:59+00:00", 80),
        ],
        {
            "heart_rate": {
                "resolution": IngestResolution.MINUTE.value,
                "aggregation": "average",
            }
        },
    )

    assert len(result) == 1
    assert result[0]["value"] == 70
    assert result[0]["metadata"]["sample_count"] == 2
    assert result[0]["metadata"]["derived_by"] == "average"
    assert result[0]["timestamp"] == "2026-08-14T10:00:00+00:00"


def test_provider_total_wins_over_interval_samples_in_the_same_bucket():
    """Verifies Rule 19: provider statements must not be double-counted."""
    result = aggregate_events(
        [
            _event("2026-08-14T10:00:01+00:00", 2),
            _event("2026-08-14T10:00:59+00:00", 3),
            _event("2026-08-14T10:00:00+00:00", 4, provider_total=True),
        ],
        {
            "heart_rate": {
                "resolution": IngestResolution.MINUTE.value,
                "aggregation": "sum",
            }
        },
    )

    assert len(result) == 1
    assert result[0]["value"] == 4
    assert result[0]["metadata"]["provider_total"] is True


def test_raw_policy_preserves_original_point():
    original = _event("2026-08-14T10:00:01+00:00", 60)
    result = aggregate_events([original], {"heart_rate": {"resolution": "raw"}})
    assert result == [original]


def test_daily_provider_total_replaces_interval_sum_for_the_day():
    """Verifies Rule 19: one authoritative provider total cannot share its day sum."""
    events = [
        {**_event("2026-08-14T00:00:01+00:00", 2), "metric_type": "steps"},
        {**_event("2026-08-14T00:00:59+00:00", 3), "metric_type": "steps"},
        {
            **_event("2026-08-14T00:00:00+00:00", 100, provider_total=True),
            "metric_type": "steps",
        },
    ]
    result = aggregate_events(
        events,
        {"steps": {"resolution": "minute", "aggregation": "sum"}},
    )

    assert len(result) == 1
    assert result[0]["value"] == 100
    assert result[0]["timestamp"] == "2026-08-14T00:00:00+00:00"
    assert result[0]["metadata"]["ingest_resolution"] == "day"


def test_stream_holds_sum_buckets_until_provider_total_decision():
    """Verifies Rule 19: streaming archives preserve provider-total precedence."""
    events = [
        {**_event("2026-08-14T00:00:01+00:00", 2), "metric_type": "steps"},
        {**_event("2026-08-14T00:00:59+00:00", 3), "metric_type": "steps"},
        {
            **_event("2026-08-14T00:00:00+00:00", 100, provider_total=True),
            "metric_type": "steps",
        },
    ]
    result = list(
        aggregate_stream(
            events,
            {"steps": {"resolution": "minute", "aggregation": "sum"}},
        )
    )

    assert [(point["timestamp"], point["value"]) for point in result] == [
        ("2026-08-14T00:00:00+00:00", 100)
    ]
