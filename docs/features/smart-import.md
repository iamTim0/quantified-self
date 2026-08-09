# Smart and force import

## What the feature does

When a connector is imported, the platform first works out which parts of the requested period
are **already complete**, and imports only the rest. The period itself is adapted automatically to
how often the connector actually imports.

Before, every sync re-requested a fixed period (30 days by default) regardless of what was already
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
- If an older gap in the data is known, the window is extended back to it.
- The window is always capped at the configured lookback.
- Only a run with status `success` moves the resume point.

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

Every run carries its window, mode, trigger, status and skipped ranges, plus the counters
`points_received`, `points_accepted` and `points_duplicate`.

## How to read it, and its limits

- `confidence: "low"` means the data does not support a reliable statement about ranges. The full
  period is then imported deliberately.
- The expected data density is estimated from the data that is there. With very few data points that
  estimate is imprecise, and the planner behaves conservatively to match.
- The coverage analysis looks at data points, not at whether they are right. A range can be complete
  and still be wrong.
