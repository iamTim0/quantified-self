# Smart and force import

## What the feature does

When a connector is imported, the platform first works out which parts of the requested period
are **already complete**, and imports only the rest. The period itself is adapted automatically to
how often the connector actually imports.

New connectors start with a 168-hour (seven-day) lookback. The user can reduce that to six or twelve
hours, one day, or choose a longer provider-appropriate window. Before adaptive planning, every sync re-requested a fixed period
regardless of what was already
stored. That produced thousands of duplicate events per run. The idempotency check discarded them,
but they still spent processing time and the provider's API quota for nothing.

## Why Core decides, and not the importer

The decision needs the import history, and only `services/core/` owns the database (AGENTS.md rule
1). So Core computes the window and sends `window_start`, `window_end` and `mode` along in the NATS
task `qs.task.sync.<source>`. The importer executes what it is given.

```text
Dashboard ──► Gateway ──► Core (computes the window, creates the SyncRun)
                            │
                            ├──► NATS qs.task.sync.<source>  { window_start, window_end, mode, sync_run_id }
                            │                                        │
                            │                                   Importer
                            │                                        │
                            └──◄── NATS qs.ingest.<source> ◄─────────┘
```

## Adaptive import periods

The overlap follows the configured poll interval:

| Poll interval | Overlap |
| --- | --- |
| hourly | 2 hours |
| every 3 hours | 6 hours |
| every 6 hours | 12 hours |
| daily | 48 hours |
| weekly | 72 hours (the cap) |

So the next import starts that overlap **before** the end of the last successful run. Nothing is
lost when data arrives late at the provider, and a single failed run is caught up automatically.

Further rules:

- Without a previous successful run, the full configured lookback is used.
- The configured lookback is stored in hours, so high-frequency connectors can request only the
  current day or the last few hours. Older configurations that contain only `lookback_days` remain
  valid and are interpreted as 24 hours per day.
- If an older gap in the data is known, the window is extended back to it.
- The window is always capped at the configured lookback.
- Only a run with status `success` moves the resume point.
- A successful resume point is the provider coverage end reported by the importer, not the time
  at which Core happened to finish consuming the broker messages. A run with no provider coverage
  cannot advance the next window.
- When the connector declares supported metrics, Core evaluates coverage separately for every
  metric and intersects the results. Static providers also receive this manifest from the shared
  registry when an older connector row has no explicit manifest. A missing metric therefore keeps
  the window open even when another metric is dense.
- The coverage contract includes the source, metric manifest, schema revision and transform
  revision. Changing any of those invalidates the previous coverage and causes a conservative
  revalidation import. Dynamic providers without a manifest use the full configured window.

## Duplicate detection at the range level

The check runs **coarse to fine**, not data point by data point:

1. A single aggregate query counts the data points per time block across the whole period.
2. Each block is classified as **complete**, **partial** or **empty** against the observed data
   density (the median of the non-empty blocks).
3. The boundaries between present and missing ranges are refined by bisection — about six queries
   are enough to resolve a day-sized block to 15 minutes.

### The safety rule

A range is skipped **only** when it is demonstrably complete. Everything uncertain is imported:

- partially filled blocks,
- irregular measurement intervals,
- heavily fragmented coverage (many alternating present and missing blocks).

The reason is the asymmetry of the two mistakes: a redundant import is harmless thanks to
idempotency, while a range skipped in error means permanent data loss.

## Smart mode (the default)

Before it starts, the import dialog shows what is about to happen:

> "Already stored: 2026-07-01 00:00–2026-07-05 00:00. Only the new period from 2026-07-05 00:00 to
> 2026-07-08 12:00 will be imported."

If the whole period is already there, no task is created at all:

> "The period from … to … is already complete and will be skipped."

## Force mode

**Force everything** processes the entire given period again.

- Idempotency and data integrity stay in force — no duplicate rows appear.
- More duplicate events are produced, and with them noticeably more processing work.
- The run is marked `mode = force` in the import log.

Force is the right choice when the provider has corrected data retroactively.

## API

### Fetching an import plan

```http
POST /api/v1/data/sources/{source_type}/import-plan
Authorization: Bearer <jwt>

{ "start": "2026-07-01T00:00:00Z", "end": "2026-07-08T00:00:00Z", "mode": "smart" }
```

Response (abridged):

```json
{
  "requested":        { "start": "...", "end": "..." },
  "covered_ranges":   [ { "start": "...", "end": "..." } ],
  "missing_ranges":   [ { "start": "...", "end": "..." } ],
  "recommended_range":{ "start": "...", "end": "..." },
  "skipped_ranges":   [ { "start": "...", "end": "..." } ],
  "coverage_scope":   "metric_set",
  "coverage_metrics": [ "steps", "sleep_duration" ],
  "coverage_reason":  "coverage checked for every declared metric",
  "confidence": "high",
  "reason": "Already stored: … Only the new period from … to … will be imported."
}
```

Leave `start` and `end` out and the endpoint returns the automatically derived window, with its
reasoning in `window_reason`.

### Triggering an import

```http
POST /api/v1/data/sources/sync
Authorization: Bearer <jwt>

{ "source_type": "whoop", "mode": "smart" }
```

A response status of `skipped` means there was nothing to do.

### Querying coverage

```http
GET /api/v1/data/coverage?start=<iso>&end=<iso>&source_type=whoop
Authorization: Bearer <jwt>
```

### Import history

```http
GET /api/v1/data/sources/{source_type}/sync-runs?limit=20
Authorization: Bearer <jwt>
```

For a tenant-wide view across all connector instances, use:

```http
GET /api/v1/data/sync-runs?limit=50&status=loading
Authorization: Bearer <jwt>
```

Every run carries its window, mode, trigger, status and skipped ranges, plus the counters
`points_received`, `points_processed`, `points_accepted` and `points_duplicate`. The statuses are
`queued` (waiting for the importer), `running` (the importer is discovering and publishing),
`loading` (Core is consuming the published events), `success`, `error` or `skipped`. A run is not
successful merely because publishing finished: Core closes it only after `points_processed` reaches
the published/expected count.

The dashboard keeps each request row separate. A queued or failed request remains visible with its
own `request_id`, status and message code; it is not replaced by the latest successful run. This
avoids implying that a request worked when only a later retry produced data.

## How to read it, and its limits

- `confidence: "low"` means the data does not support a reliable statement about ranges. The full
  period is then imported deliberately.
- The expected data density is estimated from the data that is there. With very few data points that
  estimate is imprecise, and the planner behaves conservatively to match.
- The coverage analysis looks at data points, not at whether they are right. A range can be complete
  and still be wrong.
