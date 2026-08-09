# Dawarich importer

## Purpose

The Dawarich importer normalizes raw data into tenant-scoped Quantified Self metrics and
publishes them over NATS JetStream. Core takes care of storage, deduplication and the later
API queries.

## Data access

- Source: a Dawarich API key and base URL.
- The credentials are configured in the dashboard and stored encrypted in Core.
- The importer fetches them from Core at run time and stays idle without a valid configuration.

## Setup

1. Open the data source under **Connectors** in the dashboard.
2. Enter the credentials, or the export configuration.
3. Save; Core encrypts the credentials with Fernet AES-256.
4. For active importers, click **Sync now**, or wait for Core's scheduler to find the
   connector due. The importer has no timer of its own — it acts on the task Core
   publishes; see [Architecture](../architecture.md#scheduled-imports).

## Data flow

```text
external source -> importer -> qs.ingest.dawarich -> Core -> data_points
```

## Main metrics

- `location_point`
- `location_latitude`
- `location_longitude`

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=location_point&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filter by further `metric_type` values as needed:

| `metric_type` | Meaning | Unit |
| --- | --- | --- |
| `location_point` | one recorded location point | `count` |
| `location_latitude` | latitude | `°` |
| `location_longitude` | longitude | `°` |

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).
