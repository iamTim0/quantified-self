# WHOOP importer

## Purpose

The WHOOP importer normalizes raw data into tenant-scoped Quantified Self metrics and
publishes them over NATS JetStream. Core takes care of storage, deduplication and the later
API queries.

## Data access

- Source: a WHOOP OAuth access token.
- The credentials are configured in the dashboard and stored encrypted in Core.
- The importer fetches them from Core at run time and stays idle without a valid configuration.

### Token renewal

WHOOP access tokens expire after about an hour, but the poll interval is typically six. So
without renewal the connector worked for exactly one hour, after which nothing came back but
`401`s until somebody pasted in a new token by hand.

Core therefore renews the token itself, **before** it expires (five minutes of lead time).
Reacting to a `401` instead would mean starting every import with a request that is certain
to fail.

Besides the access token, that needs:

| Field | Purpose |
| --- | --- |
| `refresh_token` | stored encrypted, never leaves Core |
| `client_id` | the OAuth client of the WHOOP application |
| `client_secret` | stored encrypted |
| `expires_in` | lifetime of the access token, in seconds |

WHOOP also swaps the refresh token on every renewal and invalidates the previous one; the new
one is stored. If the response carries none, the existing one is kept — deleting it would
make a still-valid connector impossible to renew.

If the refresh token is rejected (access revoked), Core answers `409` and says to connect the
connector again. Returning an already-expired token would only defer the error.

The importer only ever receives the short-lived access token. The refresh token and the client
secret do not cross the service boundary.

## Setup

1. Open the data source under **Connectors** in the dashboard.
2. Enter the credentials, or the export configuration.
3. Save; Core encrypts the credentials with Fernet AES-256.
4. For active importers, click **Sync now**, or wait for Core's scheduler to find the
   connector due. The importer has no timer of its own — it acts on the task Core
   publishes; see [Architecture](../architecture.md#scheduled-imports).

## Importing the emailed export

WHOOP will send your whole history as a ZIP of CSVs, which needs no OAuth application at all.
Request it in the app under Account, then upload the archive on the connector — see
[Uploading an export file](../features/file-import.md).

The export's columns resolve to the same metric names a polled sync writes, so the two do not
become separate series. Its units differ, though, and that is deliberate rather than incidental:
the export gives energy in kilocalories where the API gives kilojoules, and reading one as the
other would be wrong by a factor of four with nothing looking amiss.

WHOOP localises the archive to the account's language — file names and column headers both — so
both vocabularies are recognised; see
[Uploading an export file](../features/file-import.md#whoop---the-emailed-export). The export also
states more than the API's score objects do: a night's duration, its time in bed and its four
stages, and a workout's duration and maximum heart rate. Those are the same registry metrics the
rest of the platform uses, not export-only names.

## Data flow

```text
external source -> importer -> qs.ingest.whoop -> Core -> data_points
```

## Main metrics

- `whoop_recovery_score`
- `whoop_sleep_performance`
- `whoop_strain`
- `workout_duration`

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=whoop_recovery_score&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filter by further `metric_type` values as needed:

| `metric_type` | Meaning | Unit |
| --- | --- | --- |
| `whoop_recovery_score` | recovery | `%` |
| `whoop_strain` | strain for the day | `index` (0–21) |
| `whoop_workout_strain` | strain of one session | `index` (0–21) |
| `whoop_sleep_performance` | sleep performance | `%` |
| `sleep_efficiency` | sleep efficiency | `%` |
| `heart_rate_resting` | resting heart rate | `bpm` |
| `heart_rate_average` | average heart rate for the day | `bpm` |
| `hrv_rmssd` | heart-rate variability (RMSSD) | `ms` |
| `blood_oxygen` | blood oxygen | `%` |
| `respiratory_rate` | respiratory rate | `br/min` |
| `skin_temperature` | skin temperature | `°C` |
| `energy_total` | total energy burned for the day | `kcal` |
| `workout_energy` | energy of one session | `kcal` |
| `workout_distance` | distance of one session | `km` |
| `workout_heart_rate_average` | average heart rate of one session | `bpm` |

WHOOP reports energy in **kilojoules** and distances in **metres**. The importer converts both
into the registry's units (kcal and km respectively), so that the same quantity from Apple
Health and from WHOOP is comparable. The raw value stays in `metadata.provider_value`, its
source unit in `metadata.provider_unit`.

`whoop_recovery_score`, `whoop_strain` and `whoop_sleep_performance` keep their vendor prefix:
they are WHOOP's own figures, with no equivalent at any other source.

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).
