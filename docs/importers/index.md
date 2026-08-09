# Importer overview

Every importer follows the same pattern: configure the data source in the dashboard, store
the encrypted credentials in Core, run the importer-specific worker, and publish
tenant-scoped events to NATS JetStream.

The machine-readable compatibility boundary for each importer is its
`services/importers/<name>/importer.contract.json`. See the generated
[importer contract catalog](../importer-contracts.md) for the supported input formats,
upstream schema references and normalized metric set. Update the contract and its
transformer tests together whenever a provider changes its payload.

| Importer | Kind | Data access | NATS subject | Main metrics |
| --- | --- | --- | --- | --- |
| Yazio | active | Yazio API / OAuth token | `qs.ingest.yazio` | Calories, macros, meals |
| WHOOP | active | WHOOP API / OAuth | `qs.ingest.whoop` | Sleep, recovery, strain, workouts |
| Apple Health | passive | Health Auto Export JSON / webhook | `qs.ingest.apple_health` | Steps, heart rate, sleep, energy |
| Dawarich | active | Dawarich API key | `qs.ingest.dawarich` | GPS points, latitude, longitude |
| Streak | passive | Export / webhook | `qs.ingest.streak` | Sets, reps, weights, volume |
| Home Assistant | active | REST API + long-lived token | `qs.ingest.home_assistant` | Sensor values, temperature, humidity |
| Weather | active | Open-Meteo-compatible HTTP API | `qs.ingest.weather` | Temperature, pressure, precipitation, UV |
| Calendar | active | ICS/iCalendar feed URL | `qs.ingest.calendar` | Events, busy hours, meeting duration |

*Active* means the platform fetches from the provider; *passive* means the data arrives when
the provider or the phone sends it. Neither kind keeps a timer: Core's scheduler decides when
an active connector is due and publishes a task the importer executes — see
[Architecture](../architecture.md#scheduled-imports).

In the dashboard's **Connectors** area, configured importers and their live status are shown in
the **Current importers** tab. Provider selection for a new importer is kept in the adjacent
**Add importer** tab, so adding another instance does not mix with the current status list.

## Retrieving the data

Imported data does not live in the importers, it lives in Core. Queries go through the
Gateway to Core and are tenant-scoped, for example:

```http
GET /api/v1/data/metrics?metric_type=weather_temperature&start_time=2026-08-01T00:00:00Z&end_time=2026-08-04T23:59:59Z
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

The response carries `data_points`; each element describes one normalized measurement with
its `metric_type`, timestamp, value, source and metadata.
