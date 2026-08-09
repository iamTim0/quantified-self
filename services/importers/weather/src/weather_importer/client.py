"""Async client for the weather provider API (Open-Meteo compatible).

The template client this replaces issued `GET {base_url}/v1/forecast` with no
coordinates, no time range and an `Authorization: Bearer` header, then expected a
JSON array back. Open-Meteo takes none of those: it requires latitude/longitude,
needs no credential at all, and answers with *columnar* data —
``{"hourly": {"time": [...], "temperature_2m": [...]}}`` — not a list of records.
So the old client could not have produced a single usable data point.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import parse_qsl, urlparse, urlunparse

import httpx

from weather_importer.config import settings

logger = logging.getLogger(__name__)

#: What a connector reaches with no configuration at all. Open-Meteo's free
#: endpoint needs no credential, which is why the connector can be created
#: without one -- see `PUSH_SOURCE_TYPES` and its siblings in Core.
DEFAULT_BASE_URL = "https://api.open-meteo.com"

# Variables requested by default. Each becomes its own metric series.
#
# `uv_index` was missing here while `weather_uv_index` was registered in the
# metric catalog, mapped in the transformer, documented and advertised in the
# dashboard's connector card. The metric could therefore never be produced: the
# only place that decides what to ask the provider for did not ask for it.
DEFAULT_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "surface_pressure",
    "wind_speed_10m",
    "cloud_cover",
    "uv_index",
)


class WeatherApiError(RuntimeError):
    """Raised when the weather provider cannot be queried."""


def resolves_to_private_address(host: str) -> bool:
    """Whether a hostname reaches an address that is not on the public internet.

    Every A/AAAA record is checked, not just the first: a name that resolves to
    one public and one private address would otherwise pass and then connect to
    the private one.

    A name that does not resolve is *not* treated as private — it simply fails at
    connect time, and refusing it here would only produce a worse error message.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
        ):
            return True
    return False


def assert_reachable_host(url: str, *, allow_private: bool) -> None:
    """Refuse a provider URL that points inside the network we are running in.

    The URL comes from the tenant and is fetched from inside the compose network,
    where core-service, the database and every other importer live and nothing
    else can reach them. Without this a signed-in member could aim the importer at
    any of them — or at a cloud metadata endpoint — and read the outcome back from
    the connector's own status message.
    """
    if allow_private:
        return
    host = urlparse(url).hostname
    if not host:
        raise WeatherApiError("The configured provider URL names no host.")
    if resolves_to_private_address(host):
        raise WeatherApiError(
            "The configured provider URL points inside a private network. "
            "Set ALLOW_PRIVATE_PROVIDER_HOSTS=true if that is deliberate."
        )


def coerce_coordinate(value: Any) -> float | None:
    """A coordinate as a float, or ``None`` when it is not one.

    The connector configuration is an untyped JSON blob, so a form that posts
    ``"52.52"`` and one that posts ``52.52`` both reach here. Open-Meteo happens
    to accept the string, which is exactly why this is worth normalising: a value
    that works by coincidence is one nobody notices is wrong until the provider
    changes its mind.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
        variables: tuple[str, ...] = DEFAULT_HOURLY_VARIABLES,
        request_url: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token or None
        self.latitude = coerce_coordinate(latitude)
        self.longitude = coerce_coordinate(longitude)
        self.variables = tuple(variables) or DEFAULT_HOURLY_VARIABLES
        #: A complete URL, query and all, supplied by the user. When set, it is
        #: honoured verbatim instead of being rebuilt.
        self.request_url = (request_url or "").strip() or None

    def _guided_request(self) -> tuple[str, dict[str, Any]]:
        """URL and parameters the importer builds itself from a location."""
        if self.latitude is None or self.longitude is None:
            raise WeatherApiError(
                "Weather connector needs latitude and longitude in its configuration."
            )
        return f"{self.base_url}/v1/forecast", {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(self.variables),
            # Always UTC, and deliberately not configurable. Open-Meteo answers with
            # naive local wall-clock in whatever zone is asked for, and the transformer
            # anchors naive timestamps to UTC. Asking for anything else therefore
            # mislabels every reading by the offset -- silently, because the number
            # still looks like a plausible time. Storage is UTC; which zone a reader
            # sees is the dashboard's decision, made at render time.
            "timezone": "UTC",
        }

    def _custom_request(self) -> tuple[str, dict[str, Any]]:
        """The user's own URL, with its query preserved.

        This is the case that used to fail silently. Passing `params=` to httpx
        *replaces* the query rather than merging into it, so every `hourly=` and
        `latitude=` the user had copied was discarded — and the hardcoded
        `/v1/forecast` was appended to a string that already ended in a query,
        landing inside it. Here the query is parsed out and passed on, so the URL
        means what it says.
        """
        parsed = urlparse(self.request_url or "")
        params: dict[str, Any] = dict(parse_qsl(parsed.query, keep_blank_values=True))
        # Overridden, not preserved. A URL copied from the provider's own page
        # often carries `timezone=Europe/Berlin`, and the transformer anchors naive
        # timestamps to UTC — so honouring it would store every reading an hour or
        # two off, silently, because the number still looks like a plausible time.
        # The one query parameter the user does not get to choose.
        if params.get("timezone", "UTC") != "UTC":
            logger.info("Overriding timezone=%r in the configured URL; storage is UTC.",
                        params["timezone"])
        params["timezone"] = "UTC"
        stripped = urlunparse(parsed._replace(query="", fragment=""))
        return stripped, params

    async def fetch(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Return one record per hour, with each requested variable as a key."""
        url, params = (
            self._custom_request() if self.request_url else self._guided_request()
        )

        # The window comes from Core's import planning either way, so a custom URL
        # still benefits from smart import. Anything the user set explicitly wins.
        if start_date:
            params.setdefault("start_date", start_date)
        if end_date:
            params.setdefault("end_date", end_date)

        assert_reachable_host(url, allow_private=settings.ALLOW_PRIVATE_PROVIDER_HOSTS)

        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        try:
            # Redirects are not followed: a permitted host could otherwise 302
            # into the private range the check above just refused.
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.get(url, headers=headers, params=params)
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
