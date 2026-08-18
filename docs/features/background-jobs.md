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

## Related

- [Precomputed reports](precomputed-reports.md) — the report lifecycle these rows come
  from, including `report_timeout` versus `report_never_claimed`
- [Smart and force import](smart-import.md) — the import lifecycle and its counters
- [Data quality](data-quality.md) — what an import *found*, as opposed to whether it ran
