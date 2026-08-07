"""Tests for the weather client and transformer.

This suite was a single six-line test. The importer it covered could not have
worked against Open-Meteo at all: the client sent no coordinates and no time range,
and expected a JSON array where the API returns columnar data.

Maps to Fizzbee Invariants:
- NoDuplicateRecords
- IdempotencyKeyDeterministic
- TenantIsolation
"""

import httpx
import pytest
from weather_importer.client import ProviderClient, WeatherApiError
from weather_importer.transformer import transform

TENANT = "tenant-1"
SOURCE = "source-1"

COLUMNAR_RESPONSE = {
    "latitude": 52.52,
    "longitude": 13.41,
    "hourly": {
        "time": ["2026-08-05T00:00", "2026-08-05T01:00", "2026-08-05T02:00"],
        "temperature_2m": [18.1, 17.6, 17.2],
        "relative_humidity_2m": [72, 75, 78],
        "precipitation": [0.0, 0.2, 0.0],
    },
}


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
async def test_columnar_response_is_transposed_into_records(monkeypatch):
    """Open-Meteo returns parallel arrays, not rows."""
    _patch(monkeypatch, httpx.Response(200, json=COLUMNAR_RESPONSE))
    client = ProviderClient("https://api.open-meteo.com", latitude=52.52, longitude=13.41)

    records = await client.fetch(start_date="2026-08-05", end_date="2026-08-05")

    assert len(records) == 3
    assert records[0]["time"] == "2026-08-05T00:00"
    assert records[0]["temperature_2m"] == 18.1
    assert records[1]["relative_humidity_2m"] == 75


@pytest.mark.asyncio
async def test_coordinates_and_window_are_sent(monkeypatch):
    """The old client sent neither, so the response was never the requested data."""
    capture: dict = {}
    _patch(monkeypatch, httpx.Response(200, json=COLUMNAR_RESPONSE), capture)
    client = ProviderClient("https://api.open-meteo.com", latitude=52.52, longitude=13.41)

    await client.fetch(start_date="2026-08-01", end_date="2026-08-05")

    assert capture["params"]["latitude"] == 52.52
    assert capture["params"]["longitude"] == 13.41
    assert capture["params"]["start_date"] == "2026-08-01"
    assert capture["params"]["end_date"] == "2026-08-05"


@pytest.mark.asyncio
async def test_no_authorization_header_without_a_token(monkeypatch):
    """Open-Meteo's free endpoint needs no key; sending one is wrong."""
    capture: dict = {}
    _patch(monkeypatch, httpx.Response(200, json=COLUMNAR_RESPONSE), capture)
    client = ProviderClient("https://api.open-meteo.com", latitude=1.0, longitude=2.0)

    await client.fetch()

    assert "Authorization" not in capture["headers"]


@pytest.mark.asyncio
async def test_token_is_sent_when_configured(monkeypatch):
    capture: dict = {}
    _patch(monkeypatch, httpx.Response(200, json=COLUMNAR_RESPONSE), capture)
    client = ProviderClient("https://api.example.test", "secret", latitude=1.0, longitude=2.0)

    await client.fetch()

    assert capture["headers"]["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_missing_coordinates_is_a_clear_error(monkeypatch):
    _patch(monkeypatch, httpx.Response(200, json=COLUMNAR_RESPONSE))
    client = ProviderClient("https://api.open-meteo.com")

    with pytest.raises(WeatherApiError, match="latitude"):
        await client.fetch()


@pytest.mark.asyncio
async def test_http_error_is_wrapped(monkeypatch):
    _patch(monkeypatch, httpx.Response(500, text="boom"))
    client = ProviderClient("https://api.open-meteo.com", latitude=1.0, longitude=2.0)

    with pytest.raises(WeatherApiError):
        await client.fetch()


# ─── transformer ─────────────────────────────────────────────


def test_each_variable_becomes_its_own_metric():
    """A single metric named "weather" collapsed temperature and humidity together."""
    records = [
        {"time": "2026-08-05T00:00:00+00:00", "temperature_2m": 18.1, "relative_humidity_2m": 72}
    ]
    events = transform(records, TENANT, SOURCE)
    metrics = {e["metric_type"] for e in events}

    assert metrics == {"weather_temperature_c", "weather_humidity_pct"}


def test_idempotency_key_is_deterministic():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic."""
    records = [{"time": "2026-08-05T00:00:00+00:00", "temperature_2m": 18.1}]
    first = transform(records, TENANT, SOURCE)
    second = transform(records, TENANT, SOURCE)

    assert first[0]["idempotency_key"] == second[0]["idempotency_key"]


def test_records_without_a_timestamp_are_skipped():
    """The old code substituted now(), duplicating a row on every sync."""
    assert transform([{"temperature_2m": 18.1}], TENANT, SOURCE) == []


def test_unparseable_timestamp_is_skipped():
    assert transform([{"time": "not-a-date", "temperature_2m": 1.0}], TENANT, SOURCE) == []


def test_naive_timestamps_are_normalised_to_utc():
    """Open-Meteo emits local wall-clock without an offset."""
    events = transform([{"time": "2026-08-05T14:00", "temperature_2m": 20.0}], TENANT, SOURCE)
    assert events[0]["timestamp"].endswith("+00:00")


def test_tenant_isolation_in_keys():
    """Verifies Fizzbee Invariant: TenantIsolation."""
    record = [{"time": "2026-08-05T00:00:00+00:00", "temperature_2m": 18.1}]
    a = transform(record, "tenant-a", SOURCE)[0]
    b = transform(record, "tenant-b", SOURCE)[0]

    assert a["idempotency_key"] != b["idempotency_key"]


def test_non_numeric_values_are_skipped():
    events = transform(
        [{"time": "2026-08-05T00:00:00+00:00", "temperature_2m": None}], TENANT, SOURCE
    )
    assert events == []


def test_events_carry_top_level_source_type():
    events = transform([{"time": "2026-08-05T00:00:00+00:00", "temperature_2m": 1.0}], TENANT, SOURCE)
    assert events[0]["source_type"] == "weather"
