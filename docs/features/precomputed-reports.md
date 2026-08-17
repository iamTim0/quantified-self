# Precomputed reports

## Purpose

Three things the dashboard shows are derivations over a workspace's **whole history**: the
daily gap scan, the cross-source conflict scan, and the analysis insights bundle.

Each of them used to be recomputed by the request that displayed it. The Data Quality
Center additionally re-ran the first two every fifteen seconds for as long as it was open.
So opening a tab cost a full-history pass over `data_points` in order to redraw content
that was identical each time, the cost grew with the amount of data a workspace held, and
two readers opening the same tab paid it twice for one answer.

None of the three can answer differently until an import has changed the data underneath.
They are therefore computed **once per change**, stored in `report_runs`, and read from
there. A page load is one indexed row and no scan.

The stored result travels with the time it was computed and with an explicit staleness
flag, because a reader shown a precomputed number is entitled to know when it was true. A
number with no date on it is precisely what made recomputing on every request feel safer
than it was.

## What is a report, and what is not

Only the expensive derivations are precomputed. The distinction is deliberate:

| Read from a stored run | Read live on every request |
| --- | --- |
| Gap scan — `gaps` | Held metric values (quarantine) |
| Cross-source conflicts — `conflicts` | Metric mapping rules |
| Insights bundle — `insights` | The unsupported-field report |
| | Connector list, sync runs, quarantine capacity |

The right-hand column is *state*, not derivation. Those are small indexed selects, and they
have to be correct the instant a user saves a mapping rule rather than at the next
scheduled run. Putting them behind a job would make the page wrong for hours in order to
save nothing. See [Data quality](data-quality.md) for what each of them contains.

The [daily story](daily-story.md) is the one derivation deliberately left on the live side.
What makes the three above expensive is that they read a workspace's whole history; a day
story reads one tenant's rows inside one 24-hour window, on the indexed time dimension. It
also has to reflect an import that finished a minute ago, since *how much of today has
arrived* is the question it answers.

## Data flow

```text
An import finishes successfully
    -> sync_runs.finished_at moves the workspace's high-water mark
    -> Core's report tick (every 5 minutes, scheduler role) finds the stale kinds
    -> gaps, conflicts : Core computes them itself
       insights        : Core queues a run; the Analysis Service claims it over
                         gRPC, computes it, and hands the result back
    -> report_runs: payload + params + covers_data_through + finished_at
    -> GET /api/v1/data/reports/{kind}
```

Which service computes what is not a preference, it is what the service boundaries leave.
Core owns the database (rule 1), and the gap scan and the conflict scan are pure SQL plus
one pass in Python — so Core computes them. The insights bundle is data science, which
lives in the Analysis Service (rule 3), and that service holds no database connection and
may not store anything. Those two constraints leave exactly one shape:

- Core decides **when**, because it is the only service that can see that a workspace's
  data has moved on, and writes a `queued` run.
- Analysis **pulls** the work over the gRPC contract the two services already share
  (`ListDueAnalysisReports`), computes the bundle by reading tenant-scoped through Core,
  and pushes the result back the same way (`PutAnalysisReport`).
- Core stores it.

Nothing new was introduced to make this work: no HTTP between internal services, no second
broker connection, no database URL in the Analysis Service. Runs are handed out with
`SELECT … FOR UPDATE SKIP LOCKED` and moved to `running` in the same transaction, so two
Analysis replicas polling at the same moment cannot claim the same run.

Every claimed run names its own tenant, and everything the worker then reads is scoped to
that tenant (rule 2). `PutAnalysisReport` is scoped by tenant **and** run id, so a worker
cannot write a result into another workspace's report by presenting the wrong identifier.

## When a report is recomputed

| Trigger | Condition | Latency |
| --- | --- | --- |
| New data | A successful sync run finished later than the report's `covers_data_through` | Next tick, at most 5 minutes |
| Never computed | The workspace has no successful run of that kind, and has completed at least one import | Next tick |
| Maximum age | The last successful run finished more than 12 hours ago | Next tick |
| Source preference | A primary source was set or cleared — see [Metrics from several connectors](metric-source-selection.md) | Immediately, insights only |
| Manual | `POST /api/v1/data/reports/{kind}/refresh` | Immediately |

New data is the normal trigger. The twelve-hour maximum age is the backstop for the case a
data-driven trigger alone would miss: a report whose *inputs* changed without an import —
a mapping rule adopted, a connector deleted. A preference change is treated as more urgent
than that, because the stored insights bundle was computed against the previous choice and
is now wrong rather than merely old.

A workspace that has never completed an import is skipped entirely. Computing an empty gap
scan for it every twelve hours would be work that can only ever produce the same nothing.

### Single flight

Both levels of duplication are prevented in the database, not in a process:

- The tick itself takes a transaction-scoped Postgres advisory lock on a fixed key, so
  with several Core replicas exactly one of them plans per tick. This mirrors the sync
  scheduler; see [Scaling](../operations.md#scaling).
- Creating a run takes a second advisory lock keyed on `(tenant_id, kind)`, and the
  in-flight check is re-read under it. The lock **waits** rather than skipping, because a
  second refresh click has to see the first one's committed row — try-and-skip would let
  both pass the guard. A workspace's gap scan and conflict scan can still run at the same
  time, because the key includes the kind.

## Staleness is a comparison, not a computation

A run records `covers_data_through`: the newest finished import it could see, read from
`sync_runs` rather than from `data_points`. `sync_runs` is a small indexed table and an
import is the only thing that adds points, so asking the large table for its newest row
would reintroduce exactly the scan this design removes.

A report is stale when any of three things is true:

1. There is no successful run at all.
2. The workspace's newest successful import finished after `covers_data_through`.
3. The run finished more than 12 hours ago.

Answering that costs two timestamps. Nothing re-scans in order to discover whether it
should re-scan.

## Reading a report

All three kinds are read through one tenant-scoped endpoint. It **never computes** — it
returns the last good answer, or an explicit `never_computed`.

```http
GET /api/v1/data/reports/gaps
GET /api/v1/data/reports/conflicts
GET /api/v1/data/reports/insights
```

```json
{
  "kind": "gaps",
  "status": "ready",
  "stale": false,
  "running": false,
  "computed_at": "2026-08-15T04:12:38+00:00",
  "covers_data_through": "2026-08-15T04:05:02+00:00",
  "params": { "window_days": 30 },
  "result": { "gaps": [], "missing_count": 0, "cadence_gaps": [] }
}
```

| Field | Meaning |
| --- | --- |
| `status` | `ready` once a run has finished; `never_computed` before the first one |
| `stale` | Newer data exists than the run saw, or the run is older than the maximum age |
| `running` | A run for this kind is queued or running right now |
| `computed_at` | When the stored run finished. `null` when nothing has run |
| `covers_data_through` | The newest finished import the run could see |
| `params` | What the run was asked for — the window is part of the answer, not a filter over it |
| `result` | The stored payload, in the same shape the on-demand endpoints return |

An unknown kind is a `404` naming the three that exist.

The two Core-computed reports also still have **on-demand** endpoints, because their
parameters are genuinely free and a caller may ask for any of them:
`GET /api/v1/data/quality/gaps?start_date=…&end_date=…&offset_minutes=…` (at most 367
ordered days) and `GET /api/v1/data/quality/conflicts?tolerance=…`. These compute on the
spot and cost what the old page load cost. The dashboard does not use them; a script that
needs a one-off window can.

## Asking for a recomputation

```http
POST /api/v1/data/reports/insights/refresh
Content-Type: application/json

{ "days": 180, "source_id": "…" }
```

The response is `202 Accepted` and says what happened, not what the answer is:

```json
{ "kind": "insights", "status": "queued", "started": true, "run_id": "…" }
```

| `status` | Meaning |
| --- | --- |
| `running` | A Core-computed report (`gaps`, `conflicts`) started in the background |
| `queued` | An insights run was written for the Analysis worker to claim |
| `already_running` | A run for this kind was in flight; `started` is `false` and the caller waits for it |

`already_running` is the reason a row of impatient clicks does not become a row of
identical full-history scans.

A window is part of a report's identity rather than a filter over it — a 30-day gap scan
and a 365-day one are different answers — so asking for another window asks for another
run. The accepted parameters are bounded here rather than trusted, because this is the one
place a reader can size the work a background job will do:

| Parameter | Kind | Range | Default |
| --- | --- | --- | --- |
| `window_days` | `gaps` | 1–366 | 30 |
| `offset_minutes` | `gaps` | ±960, the reader's UTC offset | 0 |
| `tolerance` | `conflicts` | 0–1 | 0.05 |
| `days` | `insights` | 14–365 | 90 |
| `source_id` | `insights` | Restrict the bundle to one connector instance | all |

The conflict scan looks at the newest 5,000 points rather than the whole history. The whole
history is a different and much more expensive question, and a disagreement between two
connectors is worth knowing about while it is still happening.

## In the interface

Every derived view carries the same small status line: when the report was computed, a
**New data since** badge when it is stale, and a **Recompute** button.

- The **Data Quality Center** reads `gaps` and `conflicts` from their stored runs. The
  quarantine, the mapping rules and the unsupported-field list on the same page stay live.
- The **Analysis** page reads `insights`. Changing the window or the connector queues a new
  run, because both change what is computed; the minimum-strength slider does not, because
  every coefficient is already in the stored payload and it filters what is on screen.
- Before the first run has finished, the Analysis page says so and offers the button
  rather than showing an empty result.

The page polls every 2.5 seconds **only while a run is in flight**. With nothing running it
makes exactly one request when it opens and then goes quiet, because nothing it shows can
change until a run finishes.

## Failure, timeouts and what a reader sees

- A run that raises is stored as a **failed** run with a stable `message_code`. Failed runs
  are never served, so the reader keeps seeing the last good answer, correctly labelled
  with the time it was computed, instead of an empty page.
- A run still in flight after **30 minutes** is assumed dead and failed, so one lost run
  cannot block its kind forever. **Which** failure it was is now said explicitly, because
  the two have nothing in common but their timing:

  | Status when it expired | Code | What actually happened |
  | --- | --- | --- |
  | `queued` | `report_never_claimed` | Nothing ever picked it up. The Analysis Service is stopped, unreachable over gRPC, or has `REPORT_WORKER_ENABLED` off. Waiting longer would not have helped. |
  | `running` | `report_timeout` | It *was* claimed and did not finish. Either the window is genuinely too large, or the worker died mid-computation. |

    Both used to be `report_timeout`. `insights` is the only kind Core does not compute
    itself, so it is the only kind that can be queued and abandoned — which is why that one
    message was the one everybody saw, and why telling a reader their report "did not
    complete before the run timeout" sent them looking for a slow query that was not there.

    Both codes now have entries in both catalogues. Before, neither did: the dashboard fell
    through to the server's own English sentence and printed it verbatim to a German
    reader, which is the client half of rule 17 failing quietly.

!!! danger "The first real `report_timeout` was not a timeout at all"
    Found in a deployment's logs, not by reading the code. Every `insights` run was
    failing in Core's gRPC handler:

    ```
    File "core/grpc/server.py", line 590, in QueryMetricSeries
        *raw_filters,
    UnboundLocalError: cannot access local variable 'raw_filters'
    ```

    `raw_filters` was built inside `if not covered:`, while the `LAST`-metric
    refinement below read it unconditionally. A **day** series over a workspace proven
    to hold no point outside its day rollups therefore crashed — and that combination
    is the *normal* one for an established workspace.

    Nothing about the failure was visible where anybody would look. The call returned
    `INTERNAL`; the Analysis worker read that as "Core unavailable" and re-raised, by
    design, so the run was left in flight for Core's own sweep; thirty minutes later
    the sweep failed it as `report_timeout`. The reader was told their analysis was too
    slow. It had never run at all — and every retry took the same path, so the report
    could never succeed.

    Two lessons are worth keeping. A handler that reports one failure as another is
    worse than one that crashes loudly, and `report_never_claimed` above exists for the
    same reason. And a `LAST` metric on a fully rolled-up workspace is a case worth a
    test of its own, which
    `test_a_last_metric_on_a_fully_rolled_up_workspace_does_not_crash` now is.
- A late result arriving after Core has timed the run out is **refused**
  (`RUN_ALREADY_FINISHED`), because the timeout may already have queued a replacement and a
  stale result must not overwrite a newer one.
- One failing workspace does not stop a tick, and one failing report does not delay the
  next import: the report scheduler is a separate task from the sync scheduler.

## Operating it

| Setting | Where | Effect |
| --- | --- | --- |
| `SCHEDULER_ENABLED` | Core | `false` stops the sync scheduler **and** the report tick |
| `CORE_ROLE` | Core | The report tick runs in the `all` and `scheduler` roles only |
| `REPORT_WORKER_ENABLED` | Analysis | `false` stops this replica claiming insight runs. On by default and safe on every replica |

Fixed intervals, none of them configurable, and none of them the rate at which a report is
recomputed — that follows the data:

| Interval | Value | What it bounds |
| --- | --- | --- |
| Report tick | 5 minutes | How late a data-driven recomputation can be |
| Analysis idle poll | 15 seconds | How late a queued insights run is picked up |
| Analysis backoff after an unreachable Core | 60 seconds | Retry pressure during an outage |
| Runs claimed per poll | 3 | Each is a full bundle, computed sequentially |
| Run timeout | 30 minutes | How long a lost run blocks its kind |
| Maximum report age | 12 hours | How stale a report can get with no new data |

Turning the worker off everywhere leaves `gaps` and `conflicts` working and `insights`
permanently queued, then failed by the run timeout. There is no fallback path that computes
the bundle inside Core — that is the arrangement rule 3 requires, not an omission.

`report_runs` grows by one row per workspace, kind and recomputation, each holding one
stored payload. It cascades from `tenants`, so deleting a workspace takes its reports with
it.

## Interpretation and limitations

- **A report is only as fresh as its last run.** That is the trade this feature makes, and
  the staleness signal is how a reader tells: `computed_at` says when the number was true
  and `stale` says whether the data has moved on since. Neither is a guess — both come from
  comparing the stored run against the workspace's newest finished import.
- Between an import finishing and the next tick, a report can be stale for up to five
  minutes without anyone asking for it. **Recompute** is the way to skip that wait.
- A first run does not happen until the workspace has completed at least one import.
  `never_computed` means exactly that, and is not an error.
- The stored `gaps` report uses the window its run was asked for — 30 days unless someone
  asked for another. A question about a different window is a different run, or the
  on-demand endpoint.
- The conflict scan covers the newest 5,000 points, so an old disagreement between two
  connectors that has since stopped will not appear.
- A failed run is invisible to the reader by design: they see the previous good answer and
  its date. Operators find failures in `report_runs` by `status` and `message_code`.
