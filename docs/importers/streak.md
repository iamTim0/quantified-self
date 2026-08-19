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

## Sessions, exercises and muscle groups

Every point a Streak import produces carries a `session_id` derived from the workout
id Streak states, so a session's sets and its summary are one workout rather than
twenty unrelated events — see [Workout detail](../features/workout-detail.md).

`exercise.category` **is** the muscle group, and it is not stored as the canonical
value. The provider's own word is kept verbatim in `exercise_category`, and a
canonical `muscle_group` is stored beside it, so a renamed or localised category list
cannot silently split one group into two. An unrecognised category becomes `other`
*and* is named in the [Data Quality Center](../features/data-quality.md).

Streak is a webhook source with no published schema, so it now carries a field report
like every other importer. That is what makes "Streak sends this and we do not keep
it" answerable at all — it is also how anything richer than a category will be found.

Two defects were fixed alongside: a bodyweight session (reps, no weight) used to emit
**no** session points, because the set counter only advanced when both a weight and a
rep count were numeric; and a rep total was accumulated and never used.

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).

## Activity type

Every workout point carries `activity_type` — a canonical key such as `running`, `cycling` or
`strength_training` — beside `activity_label`, which is Streak's own wording, kept unchanged.

The type exists because the wording cannot be compared. Streak's workout title is whatever the user typed — "Push day" — so it is a label and never a type. The type comes from the connector instead: an app that records sets, reps and weight logs resistance training, so every Streak session is `strength_training`. A query filters on the canonical
key; see [Activity type](../importer-standard.md#activity-type) for the contract, and
[`python -m core.activity_backfill`](../operations.md#resolving-stored-workouts-into-activity-types)
for points stored before it existed.
