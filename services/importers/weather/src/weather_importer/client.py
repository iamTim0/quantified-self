"""Async client for the weather provider API (Open-Meteo compatible).

The template client this replaces issued `GET {base_url}/v1/forecast` with no
coordinates, no time range and an `Authorization: Bearer` header, then expected a
JSON array back. Open-Meteo takes none of those: it requires latitude/longitude,
needs no credential at all, and answers with *columnar* data —
``{"hourly": {"time": [...], "temperature_2m": [...]}}`` — not a list of records.
So the old client could not have produced a single usable data point.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Variables requested by default. Each becomes its own metric series.
DEFAULT_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "surface_pressure",
    "wind_speed_10m",
    "cloud_cover",
)


class WeatherApiError(RuntimeError):
    """Raised when the weather provider cannot be queried."""


class ProviderClient:
    """Fetches hourly weather observations for a coordinate.

    ``token`` is optional: Open-Meteo's free endpoint needs no key, and requiring
    one would block the default provider for no reason. It is sent only when the
    tenant actually configured one, for deployments pointing at a commercial
    endpoint.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str = "UTC",
        variables: tuple[str, ...] = DEFAULT_HOURLY_VARIABLES,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or None
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone
        self.variables = variables

    async def fetch(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Return one record per hour, with each requested variable as a key."""
        if self.latitude is None or self.longitude is None:
            raise WeatherApiError(
                "Weather connector needs latitude and longitude in its configuration."
            )

        params: dict[str, Any] = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(self.variables),
            "timezone": self.timezone,
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    f"{self.base_url}/v1/forecast", headers=headers, params=params
                )
        except httpx.HTTPError as exc:
            raise WeatherApiError(f"Weather provider unreachable: {type(exc).__name__}") from exc

        if response.status_code in (401, 403):
            raise WeatherApiError("Weather provider rejected the configured credential.")
        if response.status_code >= 400:
            raise WeatherApiError(f"Weather provider returned HTTP {response.status_code}")

        return self._flatten(response.json())

    def _flatten(self, payload: Any) -> list[dict[str, Any]]:
        """Turn the columnar hourly response into one record per timestamp."""
        if isinstance(payload, list):
            # A provider that already returns rows needs no transposition.
            return payload
        if not isinstance(payload, dict):
            return []

        hourly = payload.get("hourly")
        if not isinstance(hourly, dict):
            return []

        times = hourly.get("time") or []
        if not isinstance(times, list):
            return []

        records: list[dict[str, Any]] = []
        for index, timestamp in enumerate(times):
            record: dict[str, Any] = {"time": timestamp}
            for variable, values in hourly.items():
                if variable == "time" or not isinstance(values, list):
                    continue
                if index < len(values):
                    record[variable] = values[index]
            records.append(record)
        return records
