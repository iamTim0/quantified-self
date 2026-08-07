"""Tests for the Home Assistant client and transformer.

This suite was a single six-line test. The importer it covered read `/api/states`,
which returns only current values with no history, so a windowed sync was
impossible and every entity collapsed into one metric named `home_assistant`.

Maps to Fizzbee Invariants:
- NoDuplicateRecords
- IdempotencyKeyDeterministic
- TenantIsolation
"""

import httpx
import pytest
from home_assistant_importer.client import (
    HomeAssistantApiError,
    HomeAssistantUnauthorizedError,
    ProviderClient,
)
from home_assistant_importer.transformer import metric_name, transform

TENANT = "tenant-1"
SOURCE = "source-1"

HISTORY_RESPONSE = [
    [
        {
            "entity_id": "sensor.living_room_temp",
            "state": "21.5",
            "last_changed": "2026-08-05T10:00:00+00:00",
            "attributes": {"unit_of_measurement": "°C", "friendly_name": "Wohnzimmer"},
        },
        {
            "entity_id": "sensor.living_room_temp",
            "state": "22.0",
            "last_changed": "2026-08-05T11:00:00+00:00",
            "attributes": {"unit_of_measurement": "°C"},
        },
    ],
    [
        {
            "entity_id": "sensor.humidity",
            "state": "48",
            "last_changed": "2026-08-05T10:00:00+00:00",
            "attributes": {"unit_of_measurement": "%"},
        }
    ],
]


def _patch(monkeypatch, response: httpx.Response, capture: dict | None = None):
    async def fake_get(self, url, headers=None, params=None):  # noqa: ANN001
        if capture is not None:
            capture["url"] = url
            capture["headers"] = headers or {}
            capture["params"] = params or {}
        response.request = httpx.Request("GET", url)
        return response

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)


# ─── client ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_response_is_flattened(monkeypatch):
    """History arrives as a list of per-entity lists."""
    _patch(monkeypatch, httpx.Response(200, json=HISTORY_RESPONSE))
    client = ProviderClient("http://ha.local", "token")

    rows = await client.fetch(start_time="2026-08-05T00:00:00+00:00")

    assert len(rows) == 3
    assert rows[0]["entity_id"] == "sensor.living_room_temp"


@pytest.mark.asyncio
async def test_window_and_entity_filter_are_sent(monkeypatch):
    """Without filter_entity_id, Home Assistant returns every entity it knows."""
    capture: dict = {}
    _patch(monkeypatch, httpx.Response(200, json=HISTORY_RESPONSE), capture)
    client = ProviderClient(
        "http://ha.local", "token", entity_ids=["sensor.a", "sensor.b"]
    )

    await client.fetch(
        start_time="2026-08-05T00:00:00+00:00", end_time="2026-08-06T00:00:00+00:00"
    )

    assert capture["url"].endswith("/api/history/period/2026-08-05T00:00:00+00:00")
    assert capture["params"]["end_time"] == "2026-08-06T00:00:00+00:00"
    assert capture["params"]["filter_entity_id"] == "sensor.a,sensor.b"
    assert capture["headers"]["Authorization"] == "Bearer token"


@pytest.mark.asyncio
async def test_missing_token_is_rejected_before_any_request(monkeypatch):
    client = ProviderClient("http://ha.local", "")
    with pytest.raises(HomeAssistantUnauthorizedError):
        await client.fetch()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_token_raises_unauthorized(monkeypatch, status):
    _patch(monkeypatch, httpx.Response(status, text="nope"))
    client = ProviderClient("http://ha.local", "bad-token")

    with pytest.raises(HomeAssistantUnauthorizedError):
        await client.fetch()


@pytest.mark.asyncio
async def test_server_error_is_wrapped(monkeypatch):
    _patch(monkeypatch, httpx.Response(500, text="boom"))
    client = ProviderClient("http://ha.local", "token")

    with pytest.raises(HomeAssistantApiError):
        await client.fetch()


# ─── transformer ─────────────────────────────────────────────


def test_each_entity_becomes_its_own_metric():
    """Everything used to land in one series literally named "home_assistant"."""
    rows = [row for group in HISTORY_RESPONSE for row in group]
    events = transform(rows, TENANT, SOURCE)
    metrics = {e["metric_type"] for e in events}

    assert metrics == {"home_assistant_living_room_temp", "home_assistant_humidity"}


def test_metric_name_derivation():
    assert metric_name("sensor.living_room_temp") == "home_assistant_living_room_temp"
    assert metric_name("binary_sensor.door-1") == "home_assistant_door_1"
    assert metric_name("") == "home_assistant_unknown"


def test_unavailable_states_are_skipped():
    """"unavailable" means no reading, not zero."""
    rows = [
        {"entity_id": "sensor.a", "state": "unavailable", "last_changed": "2026-08-05T10:00:00+00:00"},
        {"entity_id": "sensor.a", "state": "unknown", "last_changed": "2026-08-05T11:00:00+00:00"},
    ]
    assert transform(rows, TENANT, SOURCE) == []


def test_boolean_states_are_mapped_to_numbers():
    rows = [
        {"entity_id": "binary_sensor.door", "state": "on", "last_changed": "2026-08-05T10:00:00+00:00"},
        {"entity_id": "binary_sensor.door", "state": "off", "last_changed": "2026-08-05T11:00:00+00:00"},
    ]
    events = transform(rows, TENANT, SOURCE)

    assert [e["value"] for e in events] == [1.0, 0.0]


def test_non_numeric_text_states_are_skipped():
    rows = [
        {"entity_id": "sensor.mode", "state": "eco", "last_changed": "2026-08-05T10:00:00+00:00"}
    ]
    assert transform(rows, TENANT, SOURCE) == []


def test_rows_without_a_timestamp_are_skipped():
    """The old code substituted now(), duplicating a row on every sync."""
    assert transform([{"entity_id": "sensor.a", "state": "1"}], TENANT, SOURCE) == []


def test_idempotency_key_is_deterministic():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic."""
    rows = [
        {"entity_id": "sensor.a", "state": "1", "last_changed": "2026-08-05T10:00:00+00:00"}
    ]
    assert (
        transform(rows, TENANT, SOURCE)[0]["idempotency_key"]
        == transform(rows, TENANT, SOURCE)[0]["idempotency_key"]
    )


def test_tenant_isolation_in_keys():
    """Verifies Fizzbee Invariant: TenantIsolation."""
    rows = [
        {"entity_id": "sensor.a", "state": "1", "last_changed": "2026-08-05T10:00:00+00:00"}
    ]
    a = transform(rows, "tenant-a", SOURCE)[0]
    b = transform(rows, "tenant-b", SOURCE)[0]

    assert a["idempotency_key"] != b["idempotency_key"]


def test_unit_and_friendly_name_are_preserved():
    rows = [
        {
            "entity_id": "sensor.living_room_temp",
            "state": "21.5",
            "last_changed": "2026-08-05T10:00:00+00:00",
            "attributes": {"unit_of_measurement": "°C", "friendly_name": "Wohnzimmer"},
        }
    ]
    meta = transform(rows, TENANT, SOURCE)[0]["metadata"]

    assert meta["unit"] == "°C"
    assert meta["friendly_name"] == "Wohnzimmer"
    assert meta["entity_id"] == "sensor.living_room_temp"


def test_events_carry_top_level_source_type():
    rows = [
        {"entity_id": "sensor.a", "state": "1", "last_changed": "2026-08-05T10:00:00+00:00"}
    ]
    assert transform(rows, TENANT, SOURCE)[0]["source_type"] == "home_assistant"
