# Home Assistant importer

## Purpose

The Home Assistant importer reads selected sensor states through the Home Assistant REST API
and makes indoor climate, light, noise or presence analysable as time series.

## Setup in Home Assistant

1. Sign in to Home Assistant in a browser.
2. Open your profile (`http://<home-assistant-host>:8123/profile`).
3. Under **Long-Lived Access Tokens**, create a token for Quantified Self.
4. Open the **Home Assistant** connector in the dashboard.
5. Save the base URL, the token and, optionally, the `entity_id` patterns to allow — for example `sensor.bedroom_temperature`.

Home Assistant REST requests use the header `Authorization: Bearer <TOKEN>`. Long-lived
tokens are created in the profile and are meant for integrations.

## Metrics

| Example entity | Normalized metric | What it is good for |
| --- | --- | --- |
| `sensor.living_room_temperature` | `home_assistant_living_room_temperature` | Compare sleep and recovery quality against room temperature. |
| `sensor.bedroom_humidity` | `home_assistant_bedroom_humidity` | Make dry air or high humidity visible. |
| `sensor.hallway_illuminance` | `home_assistant_hallway_illuminance` | Correlate the amount of light with the daily rhythm. |
| `binary_sensor.window_open` | `home_assistant_window_open` | States are stored as `1`/`0`. |

The metric name comes from the `entity_id`: everything after the dot, lowercased, with the
prefix `home_assistant_`. Which entities exist is decided by the user's own installation, not
by a vendor — which is why `home_assistant_` is registered as a *dynamic namespace*. Names
below it are legal without being catalogued, and they carry their unit in `metadata.unit`
(taken from `unit_of_measurement`) rather than in the registry.

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=home_assistant_living_room_temperature&start_time=<iso>&end_time=<iso>
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
```

## Security

The Home Assistant token is stored encrypted in Core and nowhere else. It must never reach a
NATS event, a log line or an `.env` file.

## References

- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Home Assistant Authentication API](https://developers.home-assistant.io/docs/auth_api)

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).
