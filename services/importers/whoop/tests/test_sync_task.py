"""Tests for sync task parsing and window resolution.

Core decides the import window and ships it in the ``qs.task.sync.*`` payload.
These tests pin the importer's half of that contract, including the fallback for
payloads that predate the field.

Maps to Fizzbee Invariants:
- TenantIsolation
- NoDuplicateData
"""

from datetime import datetime, timedelta, timezone

from whoop_importer.sync_task import (
    DEFAULT_LOOKBACK_DAYS,
    parse_sync_task,
    resolve_window,
)

NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
TENANT = "11111111-1111-1111-1111-111111111111"


SOURCE = "22222222-2222-2222-2222-222222222222"


def _payload(**overrides) -> dict:
    base = {
        "tenant_id": TENANT,
        "source_id": SOURCE,
        "source_type": "whoop",
        "request_id": "req_abc",
        "sync_run_id": "run_1",
        "mode": "smart",
        "window_start": "2026-08-06T06:00:00+00:00",
        "window_end": "2026-08-06T12:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_the_task_carries_the_connector_instance():
    """Which connector to sync, not just which kind.

    A tenant may hold several connectors of one type. The id decides whose
    credential is fetched and is the second component of every idempotency key
    the run produces, so a task without it cannot be acted on unambiguously.
    """
    task = parse_sync_task(_payload())
    assert task is not None
    assert task.source_id == SOURCE


def test_a_payload_without_a_source_id_still_parses():
    """An older Core published no source_id; the importer falls back to the type."""
    payload = _payload()
    del payload["source_id"]
    task = parse_sync_task(payload)
    assert task is not None
    assert task.source_id is None


def test_parses_a_full_payload():
    task = parse_sync_task(_payload())
    assert task is not None
    assert task.tenant_id == TENANT
    assert task.request_id == "req_abc"
    assert task.sync_run_id == "run_1"
    assert task.mode == "smart"
    assert task.is_force is False
    assert task.window_start == datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def test_payload_without_tenant_is_dropped():
    """Guessing a tenant is how one tenant's data lands in another's account."""
    assert parse_sync_task({"source_type": "whoop"}) is None
    assert parse_sync_task({"tenant_id": "", "source_type": "whoop"}) is None


def test_force_mode_is_recognised():
    task = parse_sync_task(_payload(mode="force"))
    assert task.is_force is True


def test_missing_mode_defaults_to_smart():
    task = parse_sync_task(_payload(mode=None))
    assert task.mode == "smart"


def test_resolves_the_window_core_supplied():
    task = parse_sync_task(_payload())
    start, end = resolve_window(task, {"lookback_days": 30}, now=NOW)
    assert start == datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


def test_falls_back_to_configured_lookback_for_legacy_payloads():
    """An older Core, or a replayed message, must still do something sane."""
    task = parse_sync_task(_payload(window_start=None, window_end=None))
    start, end = resolve_window(task, {"lookback_days": 7}, now=NOW)
    assert end == NOW
    assert start == NOW - timedelta(days=7)


def test_falls_back_to_configured_sub_day_lookback():
    task = parse_sync_task(_payload(window_start=None, window_end=None))
    start, end = resolve_window(task, {"lookback_hours": 6}, now=NOW)
    assert end == NOW
    assert start == NOW - timedelta(hours=6)


def test_falls_back_to_default_lookback_without_config():
    task = parse_sync_task(_payload(window_start=None, window_end=None))
    start, end = resolve_window(task, None, now=NOW)  # noqa: RUF059
    assert start == NOW - timedelta(days=DEFAULT_LOOKBACK_DAYS)


def test_unparseable_timestamps_are_ignored_not_crashed_on():
    """A malformed window degrades to the lookback rather than killing the sync."""
    task = parse_sync_task(_payload(window_start="not-a-date", window_end="also-bad"))
    start, end = resolve_window(task, {"lookback_days": 3}, now=NOW)
    assert end == NOW
    assert start == NOW - timedelta(days=3)


def test_naive_timestamps_are_treated_as_utc():
    task = parse_sync_task(_payload(window_start="2026-08-06T06:00:00"))
    assert task.window_start.tzinfo is not None
    assert task.window_start == datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def test_zulu_suffix_is_accepted():
    task = parse_sync_task(_payload(window_start="2026-08-06T06:00:00Z"))
    assert task.window_start == datetime(2026, 8, 6, 6, 0, tzinfo=timezone.utc)


def test_zero_lookback_never_produces_an_inverted_window():
    task = parse_sync_task(_payload(window_start=None, window_end=None))
    start, end = resolve_window(task, {"lookback_days": 0}, now=NOW)
    assert start < end
