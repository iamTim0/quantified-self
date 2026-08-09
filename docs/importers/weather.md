# Weather importer

## Purpose

The weather importer reads weather time series from an Open-Meteo-compatible API and
produces context metrics for sleep, activity and mood analyses.

## Recommended default: Open-Meteo

Open-Meteo offers HTTP GET APIs with JSON responses, consistent parameters, and no API key
for non-commercial use. For commercial use or higher limits, plan for a paid endpoint with
an API key.

## Example sources

- [Open-Meteo Forecast API](https://open-meteo.com/en/docs)
- [Open-Meteo Historical Weather API](https://open-meteo.com/)
- National weather services or self-hosted gateways, as long as they serve Open-Meteo-compatible JSON time series.

## Setup

The connector offers two modes: **Guided**, which builds the request from a location, and
**Own URL**, which sends a complete request URL you supply.

### Guided

1. Open the connector in the dashboard and search for your location by name. Picking a
   result fills in latitude and longitude; both stay editable, so a place the lookup does
   not know can be entered by hand.
2. Leave the provider URL as it is. It is prefilled with Open-Meteo, which needs **no API
   key** — replace it only for a self-hosted or commercial endpoint, and add a token then.
3. Start the sync; the importer publishes `qs.ingest.weather` events.

The place search is proxied by Core (`GET /api/v1/data/geocode`) rather than called from
the browser. The dashboard ships a `connect-src` allowlist that a direct call would require
widening for every script on the page, and a direct call would also hand the user's IP
address and home town to a third party.

In this mode the coordinates are the whole configuration: the importer builds the query
itself. Do not paste a complete URL into the **provider URL** field — that field is an origin,
and a query appended to it would be replaced by the importer's own.

### Own URL, for everything the guided mode does not cover

Switch the connector to **Own URL** and paste a complete request URL, query included. It is
sent exactly as written, so a URL copied from Open-Meteo's own documentation works — including
variables the guided mode does not request and, importantly, the **archive endpoint**:

```text
https://archive-api.open-meteo.com/v1/archive?latitude=52.52&longitude=13.41&hourly=temperature_2m
```

That matters because the forecast endpoint only reaches about 92 days back, while the
connector's lookback allows up to 365 — a range the guided mode cannot serve.

The import window still comes from Core's import planning, so smart import keeps working, but
only where you have not set `start_date` / `end_date` yourself. What you wrote always wins.

This used to fail silently: `params=` in httpx *replaces* a URL's query rather than merging
into it, so everything pasted was discarded, and the hardcoded `/v1/forecast` was appended to a
string that already ended in a query — landing inside it.

### Time zone

The importer always requests `timezone=UTC` and this is not configurable. Open-Meteo answers
with naive local wall-clock in whichever zone is asked for, and the transformer anchors naive
timestamps to UTC; asking for anything else therefore mislabels every reading by the offset,
silently, because the number still looks like a plausible time. Storage is UTC — which zone a
reader sees is decided by the dashboard at render time.

## Metrics

| Metric | Meaning | Recommendation |
| --- | --- | --- |
| `weather_temperature` | outside temperature (`°C`) | Compare against sleep quality, heart rate and activity level. |
| `weather_temperature_apparent` | apparent temperature (`°C`) | Put the strain of outdoor activity in context. |
| `weather_humidity` | humidity (`%`) | Set against sleep quality and indoor climate. |
| `weather_precipitation` | precipitation (`mm`) | Context for outdoor activity and GPS routes. |
| `weather_pressure` | air pressure (`hPa`) | Optional, for migraine or mood analyses. |
| `weather_wind_speed` | wind speed (`km/h`) | Context for running and cycling sessions. |
| `weather_cloud_cover` | cloud cover (`%`) | Together with the UV index, as a light context. |
| `weather_uv_index` | UV index (`index`) | Context for daylight and outdoor exposure. |

The names used to carry their unit as a suffix (`weather_temperature_c`,
`weather_wind_speed_kmh`). The unit now lives in the registry, which turns a change of unit
into a conversion rather than into a second metric.

`weather_uv_index` was registered, mapped in the transformer and listed here long before it
could exist: `uv_index` was missing from the importer's variable list, which is the only
place that decides what the provider is actually asked for. It is requested now.

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=weather_temperature&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).

### Why the provider URL is restricted

The URL is supplied by you and fetched by the importer, which runs inside the platform's
own private network alongside Core, the database and the broker — none of which are reachable
from outside. A URL that resolves to a private, loopback or link-local address is therefore
refused: otherwise anyone with an account could aim the importer at those services, or at a
cloud metadata endpoint, and read the outcome back from the connector's status message.

Running Open-Meteo on your own LAN is a legitimate reason to want exactly that. Set
`ALLOW_PRIVATE_PROVIDER_HOSTS=true` on the weather importer to permit it — deliberately, rather
than by default. Redirects are not followed either, since a permitted host could otherwise
redirect into the range the check just refused.
