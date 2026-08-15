# Data resolution and rollups

## Purpose

High-frequency provider exports can contain one value per second. Persisting every
sample makes the importer, JetStream and Explorer do work that is not useful for
longer periods. The platform therefore applies a tenant-scoped resolution policy
before an importer publishes an event.

The default policy is metric-specific. Continuous measurements such as heart rate
use minute values; accumulating metrics such as energy, steps and distance use the
metric registry's safe aggregation rules. Provider totals always take precedence over
values derived from their component samples.

## Data flow

```text
Provider payload
    -> importer resolves the tenant policy from Core
    -> canonicalise metric, convert unit, aggregate bucket
    -> qs.ingest.<source_type>
    -> Core validates tenant and idempotency key
    -> data_points + incremental minute/hour/day rollups
```

Importers never connect to PostgreSQL. Core remains the only database owner and
updates rollups in the same transaction as the accepted data point. A JetStream
ack therefore means that both the point and its available rollup are queryable.

Derived points carry `derived_from`, `derived_by`, `sample_count`,
`metadata.provider_value` and `metadata.units`. Whole provider payloads are not
stored.

## Resolution policy

The workspace can inspect and change policies through:

```http
GET /api/v1/data/metrics/ingest-policy
PUT /api/v1/data/metrics/ingest-policy/{metric_type}
```

The request body is:

```json
{
  "resolution": "minute",
  "raw_retention_days": 90
}
```

Changes apply to future imports only. Existing data is not silently re-keyed or
rewritten. A deliberate re-import is required to rebuild historical data using a
new policy.

The importer-facing endpoint
`GET /api/v1/internal/data/sources/{source_id}/ingest-policy` returns the same
tenant-scoped effective policy. It does not return credentials or raw data.

## Query resolution

`GET /api/v1/data/metrics` supports `resolution=auto|raw|minute|hour|day`.
With `auto`, the Explorer selects:

| Requested period | Resolution |
| --- | --- |
| Up to 24 hours | minute |
| More than 24 hours and up to 90 days | hour |
| More than 90 days | day |

The server applies the time window and source filter before the limit. The response
declares the requested resolution, bucket timestamp, sample count and whether a
point is derived. If a workspace contains a mixture of historical raw points and
newer rollups, Core merges both sources instead of returning only the rollup rows.
The response sets `contains_legacy_raw=true`, and each compatibility point carries
`metadata.compatibility_fallback=true` and `metadata.resolution="raw"`. This keeps
the fallback bounded by the same limit while preventing the client from presenting
a newest-1,000-point sample as the complete history.

The fallback is only searched where it can change the answer. It is skipped when the
request found no rollups at all — the plain raw query answers that case — and, when
the rollup page came back full, it is bounded by the oldest bucket that page returned,
since anything beyond it ranks below `limit` rows that are already in hand. Both bounds
leave the returned points identical. They matter because the "is this point already in
a rollup?" test is evaluated per row: unbounded, a workspace whose data all arrived
after rollups existed paid a scan of its entire history, on every chart request, to
find nothing.

Analysis uses Core's internal `QueryMetricSeries` gRPC method for daily and hourly work. The method
returns one explicit bucket per `(metric_type, source_id, interval)`, with `sample_count` and an
absent value for gaps. It reads the matching rollup resolution first and aggregates only raw points
not already covered by a rollup. When several connector instances report the same canonical metric,
Core returns separate source series and an `AMBIGUOUS_METRIC_SOURCE` issue; it never adds them
together. Analysis excludes that metric until a source is selected. This keeps large analyses
bounded without silently treating a missing day as zero or a second connector as extra activity.

The Explorer requests each selected metric separately, and keeps the raw table query independent
from the chart query, so a chart is not truncated by the table's page size. It does **not** split
that request per connector instance: one query per metric carries a limit scaled by the number of
configured connectors, and the per-source series are separated client-side from the `source_id`
each point already carries. Splitting it multiplied the query count by the number of connectors —
eight connectors and three metrics meant twenty-four concurrent queries, each entitled to ten
thousand raw points, which is what made a whole-history drill-down stall the browser and the
database at once. The selected range is sent to Core as an explicit start/end window; it is not
hardcoded to a week.
The Analysis view offers the same connector-instance selection and sends its `source_id` to the
Analysis service. Leaving the selector on all sources is intentionally conservative: ambiguous
metrics are reported as unavailable instead of being guessed or combined.

`/api/v1/data/metrics/summary` combines day-rollup aggregates with uncovered legacy
points when both exist and reports `contains_legacy_raw=true`. Data imported before
rollups were introduced remains queryable through this compatibility fallback until
a backfill is run.

## Backfill and retention

Rollups are not backfilled automatically at service startup. For an existing large
database, run the explicit Core command once during a maintenance window:

```bash
python -m core.rollup_backfill --tenant-id <tenant-id>
```

The command is tenant-scoped, idempotent and updates one resolution at a time. New
accepted points maintain these rollups incrementally, so the historical backfill is
not a nightly full-history job. Raw retention is policy-driven and should be applied
through an explicit, reviewed maintenance job. For example, a nightly tenant-scoped
dry run is:

```bash
python -m core.retention --tenant-id <tenant-id> --dry-run
python -m core.retention --tenant-id <tenant-id>
```

The command removes only points marked as raw (or legacy points without a resolution marker),
keeps minute/hour/day rollups, and never runs automatically during service startup. Schedule it
per tenant through the operator's job runner after reviewing the dry-run count.

## Interpretation and limitations

- Minute aggregation reduces storage and query cost; it cannot restore information
  that the provider did not export.
- Historical data retains the resolution at which it was imported.
- Day rollups prefer the newest provider-stated total over interval samples for the same metric and day;
  raw inspection can still show both provenance paths.
- A provider export that ends before the requested period is shown as incomplete;
  a successful upload does not imply complete provider coverage.
- If the broker is full, the importer pauses instead of allowing unacknowledged
  events to be discarded.
