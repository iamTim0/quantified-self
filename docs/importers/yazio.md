# Yazio importer

## Purpose

The Yazio importer normalizes raw data into tenant-scoped Quantified Self metrics and
publishes them over NATS JetStream. Core takes care of storage, deduplication and the later
API queries.

## Data access

- Source: a Yazio OAuth/API token from the app integration.
- The credentials are configured in the dashboard and stored encrypted in Core.
- The importer fetches them from Core at run time and stays idle without a valid configuration.

!!! note "The OAuth client is not our secret"
    Signing in to Yazio uses their mobile app's client. Its `client_id` and `client_secret`
    sit inside a shipped app, which makes them public, and we could not rotate them anyway.
    They used to be hardcoded in `client.py`, where they looked like a leaked secret; they
    now live in the configuration as `YAZIO_CLIENT_ID` / `YAZIO_CLIENT_SECRET` — with the
    same values as the default, replaceable for an installation with its own client.

    The user's own credentials are untouched by this: they come from the dashboard and are
    loaded encrypted from Core.

## Setup

1. Open the data source under **Connectors** in the dashboard.
2. Enter the credentials, or the export configuration.
3. Save; Core encrypts the credentials with Fernet AES-256.
4. For active importers, click **Sync now**, or wait for Core's scheduler to find the
   connector due. The importer has no timer of its own — it acts on the task Core
   publishes; see [Architecture](../architecture.md#scheduled-imports).

## Data flow

```text
external source -> importer -> qs.ingest.yazio -> Core -> data_points
```

## Main metrics

- `nutrition_energy`
- `nutrition_protein`
- `nutrition_carbohydrates`
- `nutrition_fat`

## Retrieving the data

```http
GET /api/v1/data/metrics?metric_type=nutrition_energy&start_time=<iso>&end_time=<iso>&limit=1000
Authorization: Bearer <jwt>
X-Tenant-ID: <tenant-id>
X-Request-ID: <request-id>
```

Filter by further `metric_type` values as needed:

| `metric_type` | Meaning | Unit |
| --- | --- | --- |
| `nutrition_energy` | calories for the day | `kcal` |
| `nutrition_protein` | protein for the day | `g` |
| `nutrition_carbohydrates` | carbohydrates for the day | `g` |
| `nutrition_fat` | fat for the day | `g` |
| `nutrition_fiber` | fibre for the day | `g` |
| `nutrition_meal_energy` | calories per meal; the meal is in `metadata.meal_category` | `kcal` |
| `nutrition_item_energy` | calories per entry | `kcal` |
| `nutrition_item_amount` | amount of an entry that carries no calorie figure | `g` |
| `nutrition_recipe_portions` | number of recipe portions | `count` |

`nutrition_energy` is the same metric Apple Health writes its dietary energy to — both
sources land in one series.

Meals are no longer metrics of their own. A separate name used to appear per meal label
(`breakfast_calories`, `lunch_calories`, …), depending on which labels the provider happened
to return. The meal is a property of the measurement, so it lives in
`metadata.meal_category`.

The full definition of every metric — its unit, its aggregation and the former names that
still point at it — is in [Metrics](../metrics.md).
