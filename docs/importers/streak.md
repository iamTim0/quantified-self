# Streak importer

## Purpose

The Streak importer normalizes raw data into tenant-scoped Quantified Self metrics and
publishes them over NATS JetStream. Core takes care of storage, deduplication and the later
API queries.

## Data access

- Source: a Streak export, or a webhook configuration.
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
external source -> importer -> qs.ingest.streak -> Core -> data_points
```

## Main metrics

- `strength_set_weight`
- `strength_set_reps`
- `strength_session_volume`
- `strength_session_sets`

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=strength_set_weight&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filter by further `metric_type` values as needed:

| `metric_type` | Meaning | Unit |
| --- | --- | --- |
| `strength_set_weight` | weight of one set | `kg` |
| `strength_set_reps` | repetitions in one set | `count` |
| `strength_set_volume` | weight × repetitions | `kg` |
| `strength_set_heart_rate_max` | peak heart rate within one set | `bpm` |
| `strength_session_volume` | volume of the whole session | `kg` |
| `strength_session_sets` | number of sets in the session | `count` |

The prefix is `strength_`, not `workout_`: `workout_*` holds the aggregates of whole
endurance sessions from Apple Health and WHOOP. `strength_set_heart_rate_max` is the peak
heart rate of **one set**, `workout_heart_rate_max` that of an entire session — two
different quantities that looked like variants of each other under a shared prefix.

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).
