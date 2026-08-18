# Data resolution and rollups

## Purpose

High-frequency provider exports can contain one value per second. Persisting every
sample makes the importer, JetStream and Explorer do work that is not useful for
longer periods. The platform therefore applies a tenant-scoped resolution policy
before an importer publishes an event.

The default policy is metric-specific. Accumulating metrics such as energy, steps
and distance use the metric registry's safe aggregation rules; heart rate is stored
per second (below). Provider totals always take precedence over values derived from
their component samples.

## The second tier

`IngestResolution` has five members — `raw`, `second`, `minute`, `hour`, `day` — and
`heart_rate` defaults to **`second`**.

A minute mean is the wrong summary of the one span where a pulse actually moves: an
interval session averages to a flat line that no reading of it can undo. So the
default is finer, and **it costs almost nothing**, because a second bucket is not
86,400 rows a day — it is *exactly what the device sent, with duplicates inside one
second collapsed*. A watch samples every few seconds under load and every few
minutes at rest, so second resolution preserves the workout and adds nothing at all
to the idle hours. Expect on the order of 2–4× the rows a minute default produces,
bounded by the device rather than by the clock.

It is deliberately **not** used for:

- `steps`, `distance`, `energy_active`, `energy_resting` — `SUM` metrics whose day
  total the provider already states. Sixty times the rows, no extra information, and
  a standing invitation to the double count rule 19 forbids.
- the `weather_*` family — continuous, but from an hourly forecast API, so a second
  bucket would be sixty copies of one number.

**There is no `second` rollup tier and there will not be one.** A rollup exists to
make a *long-range* query cheap, and a second rollup has the same cardinality as
`data_points` — it would double the storage to answer nothing faster. Second
resolution data *is* `data_points`, which is what a short-window query reads.

## Buckets keep their spread

A bucketed point carries `bucket_min` and `bucket_max` in its metadata alongside its
collapsed value, for momentary (`average` and `max`) metrics.

Without them the rollups were wrong in two ways at once. Core fills a rollup's
min/max columns from the single value it is handed, so a day's "maximum heart rate"
was in fact the highest minute *average* of that day — a sprint peaking at 186
showed as 171, with nothing saying so. And a rollup's mean was an unweighted mean of
bucket means, so a minute holding one sample counted for as much as a minute holding
sixty. `sample_count` now weights the sum, and the stated spread widens the min/max.

A spread an event already declares is folded in rather than replaced: an Apple Health
workout sample states the phone's own Min and Max for the interval it covers, and
collapsing to `min([its average])` would report a narrower range than the one that
was measured.

`GET /api/v1/data/metrics` returns `min` and `max` beside `value` at any non-raw
resolution, so a chart can draw the range a mean hides.

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

In the dashboard this lives in the Explorer's **Overview** view: every metric row has a
**Storage** column showing the resolution currently stored for that metric and whether it is
the registry default or a value set for this workspace. Changing it selects a new value and
requires a separate **Apply**, because the setting decides what future imports keep rather
than what the current view shows. It is deliberately one metric at a time.

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
| Up to 2 hours | raw (which for heart rate is per second) |
| More than 2 hours and up to 24 hours | minute |
| More than 24 hours and up to 90 days | hour |
| More than 90 days | day |

The two-hour row is what makes a workout-length window rich without a caller passing
anything. `resolution=second` is also accepted explicitly and reads `data_points`
directly, there being no second rollup to read.

**Rollup buckets are UTC.** `date_trunc('day')` runs in UTC and `/api/v1/data/metrics` takes
no timezone parameter, so a "day" here is a UTC day: for a reader at UTC+2 it runs from
22:00 to 22:00, and a reading taken at 23:30 belongs to the following bucket. That is
correct for a chart spanning weeks and wrong for anything that claims to describe *one day*,
which is why the daily story is a separate endpoint that takes the reader's offset and
bounds the window itself — see [The daily story](daily-story.md).

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
a rollup?" test has to be applied to every point the query considers: unbounded, a
workspace whose data all arrived after rollups existed scanned its entire history, on
every chart request, to find nothing.

Analysis uses Core's internal `QueryMetricSeries` gRPC method for daily and hourly work. The method
returns one explicit bucket per `(metric_type, source_id, interval)`, with `sample_count` and an
absent value for gaps. It reads the matching rollup resolution first and aggregates only raw points
not already covered by a rollup. When several connector instances report the same canonical metric,
Core returns separate source series and an `AMBIGUOUS_METRIC_SOURCE` issue; it never adds them
together. The issue names the connector that answers for the metric in `primary_source_id`, and
Analysis uses that series rather than dropping the metric — see
[Metric source selection](metric-source-selection.md). This keeps large analyses bounded without
silently treating a missing day as zero or a second connector as extra activity.

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
Analysis service. Leaving the selector on all sources is safe: a metric several connectors report
is answered by one of them — the workspace's stated preference, or otherwise the connector with the
most coverage — and the result names which. Values are never combined, because adding two step
counters counts the same walk twice. See [Metric source selection](metric-source-selection.md).

`/api/v1/data/metrics/summary` combines day-rollup aggregates with uncovered legacy
points when both exist and reports `contains_legacy_raw=true`. Data imported before
rollups were introduced remains queryable through this compatibility fallback until
a backfill is run.

The summary answers over a workspace's whole history and so has no time window to
bound that fallback with — it was the one query in the platform that scaled with the
amount of data rather than with the number of days on screen. It now runs **until it
comes back empty once**, and then stops for as long as Core is running.

That is sound because an import cannot create a point the fallback would find. Every
path that stores a `DataPoint` — the NATS consumer, the internal bulk-write endpoint
and the quarantine replay — updates that point's rollups in the same transaction, and
nothing deletes a rollup except the workspace wipe, which deletes the points too. A
point outside a rollup is therefore older than rollups themselves, and that set only
ever shrinks. Only the empty result is remembered; a workspace that still holds legacy
points is re-queried every time, because [retention](#backfill-and-retention) and the
backfill remove members of that set and a remembered total would go on reporting points
that are gone. The backfill consequently needs no cache invalidation: once it has
covered the last legacy point, the next summary comes back empty and stops scanning.

Measured on a 2,000,000-point workspace whose data was fully covered, the summary fell
from 276 ms to 18 ms, and stopped occupying eight parallel workers to do it. The state
is held in the Core process, not in the database, so restarting Core re-proves it —
which is also the answer for a database restored or edited outside the service.

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

The command removes only fine-grained points — those marked `raw` or `second`, and
legacy rows without a marker — keeps minute/hour/day rollups, and never runs
automatically during service startup. Schedule it per tenant through the operator's
job runner after reviewing the dry-run count.

### Some metrics are never purged

`raw_retention_days` may be `null`, which means *never*, and it is the default for
every `workout_*`, `strength_*` and `location_*` metric
(`shared_schemas.metrics.NEVER_PURGED_CATEGORIES`).

The principle: **a rollup substitutes for a fine-grained point only when the metric
is a quantity over time.** A day rollup of `strength_set_weight` is "the heaviest
thing lifted that day", which is not the workout. A `location_point` rollup is a
count, so purging the fixes would leave the aggregate cheerfully reporting how many
there were while the coordinates they carried were gone. Purging either is not
keeping the aggregate — it is deleting the measurement.

It is a category rule rather than thirty repeated settings, so a *new* workout or
strength metric inherits it; written thirty times, the next one added would quietly
get ninety days and nobody would notice until the data was gone. `workout_heart_rate`
states 365 explicitly, being the one genuinely large series, and its mean and maximum
survive permanently in `workout_heart_rate_average` and `_max`.

The dry run **names** the metrics it exempted, because a metric kept forever is a
decision somebody should be able to see — without that, its count could not
distinguish "nothing was old enough" from "these are never deleted at all".

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
