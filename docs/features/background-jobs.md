# Background activity and notifications

Everything the platform does on its own — imports, gap and conflict scans, the daily
story, the insights analysis — now appears in one list behind the bell in the top
right of the dashboard.

## Why one list

The work was already recorded. `sync_runs` holds every import attempt and
`report_runs` holds every derivation, and both have held a full lifecycle, timings
and a stable `message_code` for some time. What was missing was a way to see either
without already knowing where to look: an import was visible on the connectors page,
a report was a line above the chart it fed, and a nightly analysis that failed at
03:00 was visible nowhere at all until somebody opened the analysis tab and read a
sentence about a run timeout.

## It is a read model, deliberately

`GET /api/v1/data/jobs` is the union of those two tables and **nothing else**. No new
table, no second lifecycle, no job that exists in the notification list but not in
the table it came from.

That is worth more than the code it saves. A notification that can disagree with the
thing it notifies about is worse than no notification: the reader then has two
sources and no way to tell which one is lying. Because there is only ever one record
of a run, "the bell says it failed but the connector page says it worked" is not a
state this can reach.

```http
GET /api/v1/data/jobs?limit=30&since=2026-08-17T09:12:00Z
```

| Parameter | Range | Default |
| --- | --- | --- |
| `limit` | 1–100 | 50 |
| `since` | An ISO timestamp — when this reader last opened the panel | none |

| Field | Meaning |
| --- | --- |
| `jobs[].key` | `import:<uuid>` or `report:<uuid>`. Prefixed because the two tables have independent id spaces |
| `jobs[].kind` | `import` or `report` |
| `jobs[].subject` | The connector type, or the report kind — an identifier, never prose (rule 17) |
| `jobs[].status` | `queued`, `running`, `success`, `error`, `failed` |
| `jobs[].progress` | `0.0`–`1.0`, or `null` where no fraction can honestly be claimed |
| `jobs[].message_code` / `message_params` | What happened, for the client to translate |
| `jobs[].message` | The server's own English sentence, for a client that does not know the code |
| `active_count` | How many are still in flight |
| `unseen_count` | How many finished after `since`; `null` when the caller stated none |
| `poll_recommended` | Whether anything is in flight, so the client polls fast or slow |

Only the last **14 days** are read. A job nobody looked at for a fortnight is not a
notification any more, and an unbounded scan of `sync_runs` is the one query here
that would otherwise grow with a workspace's entire lifetime.

## Progress is reported only where it exists

An import that stated `points_expected` has a real denominator, so it gets a bar. A
**push** connector — Apple Health, Streak — cannot say in advance how much is coming,
and a derivation has no interior to report on at all.

For those, `progress` is `null` and the interface shows a spinner. This is the whole
reason the field is nullable rather than defaulting to something: a bar computed from
processed-over-received sits at 100% from the first event to the last, which reads as
*finished* for the entire duration of the run. A spinner claims nothing, and claiming
nothing is better than claiming something false.

## "Seen" belongs to the reader, not to the workspace

The badge counts what finished since this reader last opened the panel, and that
moment is kept in the browser under `qs-jobs-seen-at` — sent to the server as `since`,
never stored by it.

Whether *you* have seen a notification is not a property of the workspace. Stored
server-side, two people sharing a workspace would clear each other's badges, and the
second person would never learn that last night's import failed because the first
person had already glanced at it.

While something is running the badge shows the number of running jobs instead, so
opening the panel does not clear a badge for work that has not finished yet.

## Polling

The client polls every 4 seconds while `poll_recommended` is true and every 60
seconds when it is not. The server decides which, so the two ends cannot hold
different opinions about what "still running" means — and the bell still notices a
scheduled run that starts while nobody is watching.

## When scheduling itself stops

Every scheduled import stopped for a day and nothing said so. It is written down here
because the shape is general and the silence was the expensive part.

A scheduler tick takes a Postgres advisory lock so that one replica owns it. That tick
also calls `expire_stale_runs`, which writes `data_sources.config` when it retires a
dead run — so the transaction held a row lock on that connector. It then called the
enqueue path, which opens **its own** session (deliberately: one connector's failure
must not roll back another's `SyncRun`) and updates the same row. The inner session
blocked on the outer's row lock while the outer waited, in Python, for the inner to
return.

Postgres cannot break that. The outer connection is not waiting on a database lock, so
there is no cycle for the deadlock detector to see. It hung, holding the lock, and every
later tick failed `pg_try_advisory_xact_lock` and returned — at `debug`. It was also
self-perpetuating: the expiry never committed, so the dead run that triggered it was
still there for the next tick, which is why restarting did not help.

Four things changed, and only the first is the fix:

1. **The tick decides under the lock and commits before it acts.** `run_once` now
   collects the due connectors, commits — releasing the advisory lock *and* the row
   locks — and enqueues afterwards. Nothing is held while it calls out.
2. **A denied lock becomes audible.** After twelve consecutive denials (about an hour)
   the scheduler logs a warning. A permanently held lock and an idle scheduler produce
   identical silence, which is the only reason this lasted a day.
3. **The repair no longer shares a fate with its subject.** Retiring dead runs happens
   inside the tick *and* in `run_stale_run_sweep`, on its own timer under its own lock
   key. A heal job that lives inside the thing it heals heals nothing — a weather run
   sat in `loading` for twenty-seven hours while the mechanism meant to retire it was
   queued behind the failure it would have fixed.
4. **The operator is told.** `connectors_overdue` is a deployment warning like any
   other, raised when a connector is past three times its interval, and it names the
   worst one and how long it has been. Every connector card kept showing its last
   successful run throughout the outage — which is also what a healthy connector looks
   like.

Underneath all of it, `docker-compose.prod.yml` sets
`idle_in_transaction_session_timeout=5min` and `lock_timeout=30s` on Postgres. That is
deliberately a server setting rather than a watchdog job: a timeout in the database
cannot be blocked by the thing it is watching, which is precisely how the in-process
repair failed. There is no `statement_timeout`, because legitimate work here is long —
a year-long report recompute and an Apple Health import of millions of points both
belong to queries that must be allowed to finish.

## Related

- [Precomputed reports](precomputed-reports.md) — the report lifecycle these rows come
  from, including `report_timeout` versus `report_never_claimed`
- [Smart and force import](smart-import.md) — the import lifecycle and its counters
- [Data quality](data-quality.md) — what an import *found*, as opposed to whether it ran
