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

1. Save the location coordinates, or a pre-configured API URL, in the dashboard connector.
2. Optionally choose the variables: temperature, precipitation, pressure, UV index.
3. Start the sync; the importer publishes `qs.ingest.weather` events.

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

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=weather_temperature&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).
