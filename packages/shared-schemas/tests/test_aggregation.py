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


def test_a_bucket_keeps_its_spread_beside_its_average():
    """A minute's min and max must survive its collapse to one number.

    Core's `update_rollups_for_point` has min/max columns and fills both from the
    single value it is handed. Without a stated spread, a day's "maximum heart
    rate" was the highest minute *average* of that day — a sprint peaking at 186
    showed as 171, and nothing indicated the difference.
    """
    result = aggregate_events(
        [
            _event("2026-08-14T10:00:01+00:00", 140),
            _event("2026-08-14T10:00:20+00:00", 186),
            _event("2026-08-14T10:00:59+00:00", 160),
        ],
        {"heart_rate": {"resolution": IngestResolution.MINUTE.value, "aggregation": "average"}},
    )

    assert len(result) == 1
    assert result[0]["metadata"]["bucket_min"] == 140
    assert result[0]["metadata"]["bucket_max"] == 186
    assert result[0]["value"] == 162


def test_a_summed_bucket_states_no_spread():
    """A piece of a total is not a reading of a level, so it has no minimum."""
    events = [
        {**_event("2026-08-14T10:00:01+00:00", 5), "metric_type": "steps"},
        {**_event("2026-08-14T10:00:40+00:00", 7), "metric_type": "steps"},
    ]
    result = aggregate_events(
        events,
        {"steps": {"resolution": IngestResolution.MINUTE.value, "aggregation": "sum"}},
    )

    assert result[0]["value"] == 12
    assert "bucket_min" not in result[0]["metadata"]
    assert "bucket_max" not in result[0]["metadata"]


def test_second_resolution_collapses_only_within_one_second():
    """Two samples in one second become one point; the next second is its own."""
    result = aggregate_events(
        [
            _event("2026-08-14T10:00:01.100000+00:00", 150),
            _event("2026-08-14T10:00:01.900000+00:00", 154),
            _event("2026-08-14T10:00:02.000000+00:00", 158),
        ],
        {"heart_rate": {"resolution": IngestResolution.SECOND.value, "aggregation": "average"}},
    )

    assert len(result) == 2
    assert result[0]["value"] == 152
    assert result[0]["metadata"]["sample_count"] == 2
    assert result[0]["timestamp"] == "2026-08-14T10:00:01+00:00"
    assert result[1]["value"] == 158


def test_second_resolution_is_the_registry_default_for_heart_rate():
    """`heart_rate` is second-grained with no policy at all — the workout case."""
    result = aggregate_events(
        [
            _event("2026-08-14T10:00:01+00:00", 150),
            _event("2026-08-14T10:00:31+00:00", 172),
        ]
    )

    assert len(result) == 2, "a minute default would have flattened these into one"
    assert {point["value"] for point in result} == {150, 172}


def test_a_second_bucket_marks_its_resolution():
    """Retention keys off this marker, so a second point must carry it."""
    result = aggregate_events(
        [
            _event("2026-08-14T10:00:01.100000+00:00", 150),
            _event("2026-08-14T10:00:01.400000+00:00", 152),
        ],
        {"heart_rate": {"resolution": IngestResolution.SECOND.value, "aggregation": "average"}},
    )

    assert result[0]["metadata"]["ingest_resolution"] == "second"


def test_the_stream_path_keeps_the_spread_too():
    """`aggregate_stream` is the archive path; it must not differ from the batch one."""
    result = list(
        aggregate_stream(
            [
                _event("2026-08-14T10:00:01+00:00", 100),
                _event("2026-08-14T10:00:30+00:00", 190),
                _event("2026-08-14T10:01:05+00:00", 120),
            ],
            {"heart_rate": {"resolution": IngestResolution.MINUTE.value, "aggregation": "average"}},
        )
    )

    first = [point for point in result if point["timestamp"].startswith("2026-08-14T10:00")]
    assert first[0]["metadata"]["bucket_min"] == 100
    assert first[0]["metadata"]["bucket_max"] == 190


def test_a_spread_the_event_already_declared_is_not_narrowed():
    """An Apple Health workout sample states its own Min and Max.

    Collapsing to `min([its average])` would report a spread narrower than the one
    the phone measured — a value that arrived and vanished (rule 19).
    """
    result = aggregate_events(
        [
            {**_event("2026-08-14T10:00:01+00:00", 150),
             "metadata": {"units": "bpm", "provider_value": 150,
                          "bucket_min": 138, "bucket_max": 191}},
            {**_event("2026-08-14T10:00:20+00:00", 155),
             "metadata": {"units": "bpm", "provider_value": 155,
                          "bucket_min": 149, "bucket_max": 160}},
        ],
        {"heart_rate": {"resolution": IngestResolution.MINUTE.value, "aggregation": "average"}},
    )

    assert result[0]["metadata"]["bucket_min"] == 138
    assert result[0]["metadata"]["bucket_max"] == 191
