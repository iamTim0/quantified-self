# Metrics from several connectors

## Purpose

A canonical metric name says *what was measured*, never who measured it (rule 15). Two
connectors that both report `steps` therefore write the same name, and a workspace that
runs a phone and a watch, or two weather locations, ends up with more than one connector
answering for the same quantity.

Such a metric used to be **dropped from every analysis**. No correlation, no trend, no
anomaly, no weekday pattern — the metric simply was not there, and the interface said only
that some metrics were unavailable.

That was the safe half of a correct observation. It is now analysed: Core picks one
connector to answer for the metric, says which one it picked and why, and the Analysis
Service uses that connector's series.

## Values are never merged

This is the part that does not change, and the reason the old behaviour existed at all.

- **Adding two step counters double counts.** `steps` is a `SUM` metric and both connectors
  are describing the same walk, so summing them produces a plausible, wrong number — and a
  wrong number is worse than a missing one, because nothing distinguishes it from a right
  one (rule 19).
- **Averaging two overlapping sensors silently reweights the samples.** A watch sampling
  heart rate every five seconds and a chest strap sampling every second do not contribute
  equally to a mean over both, and the resulting figure belongs to neither device.

So the platform does not merge. It answers with one connector's series and names it. "Do
not merge" never implied "do not answer" — it implied "say which one".

## How the primary source is chosen

| Reason code | When it applies | Wins over |
| --- | --- | --- |
| `preference` | The workspace has stated a primary connector for this metric, and that connector still reports it | Everything |
| `coverage` | No preference is stated | — |

With no preference, the connector with the **most samples in the workspace's whole stored
history** answers — not the most in whatever window is being viewed. A primary source is a
property of the workspace, not of the current chart: resolving it per window made the
analysed series change identity between two views of the same data, and made the picker
card name a connector the bundle had not used. A tie is broken by the connector identifier,
so the choice is stable between calls rather than flickering with row order — an analysis
whose attribution changed each time it was recomputed would be worse than either candidate.

A stated preference wins **even when that connector covered less of the window**. It is a
statement about which device the reader trusts, not a guess, and quietly overruling it on
volume would make the setting a placebo. A preference naming a connector that contributed
nothing to the window being analysed is ignored rather than honoured into an empty series,
and coverage decides instead.

`preference` and `coverage` are stable English identifiers, not prose (rule 17). Clients
branch on them; the interface renders them as *your choice* and *chosen automatically —
most complete*.

The daily story applies the same rule through the same function, so the figure on the
landing page and the series in the analysis can never name different connectors for one
metric. It emits one further reason code the analysis path has no use for — `only_source`,
for a metric a single connector reported that day, where there is no decision to make. See
[The daily story](daily-story.md).

## Data flow

```text
Analysis asks Core for the daily series (QueryMetricSeries, gRPC)
    -> Core returns one series per (metric_type, source_id) - never a sum
    -> for each metric with more than one source, Core adds an issue:
         code               = AMBIGUOUS_METRIC_SOURCE
         metric_type        = the canonical name
         source_ids         = every connector reporting it
         primary_source_id  = the one that answers
         primary_reason     = preference | coverage
    -> Analysis keeps only the primary source's buckets for that metric
    -> the bundle reports metric_source_ids and source_issues
```

Core makes the choice rather than Analysis, because Core holds both inputs it needs: the
workspace's stated preference and the coverage figures. Analysis holds neither and must not
(rule 1). Analysis picking one itself would be a guess, and a guess about which of two step
counters is real is exactly the wrong thing to hide.

The preference lookup and the coverage pass only happen when something is actually
ambiguous. A workspace with one connector per metric pays nothing for this.

A metric stays excluded from the analysis in exactly one case: Core named no primary. In
practice that means an older Core during a rolling deployment. *Answered by one connector*
and *left out because no primary was named* are reported as two separate notices in the
interface, because conflating them is what made the single old notice misleading — only the
second is a gap the reader has to act on.

## Setting and clearing a preference

### In the interface

The **Metrics from several connectors** card appears on the Analysis page whenever the
current bundle contains at least one ambiguous metric. Each row shows the metric, why the
current connector answers for it, and a dropdown listing every connector that reports it
with its sample count. `Automatic (most complete)` is the absence of a stored preference,
not a third kind of choice — selecting it clears the preference.

Setting or clearing a preference **queues a fresh insights bundle immediately**, because
the stored one was computed against the previous choice and is now wrong rather than merely
old. See [Precomputed reports](precomputed-reports.md). If queueing fails the preference is
still saved, and the next scheduler tick recomputes.

### Through the API

All three are tenant-scoped and reachable through the Gateway.

```http
GET    /api/v1/data/metrics/source-preferences
PUT    /api/v1/data/metrics/source-preferences/{metric_type}
DELETE /api/v1/data/metrics/source-preferences/{metric_type}
```

`GET` lists **only the metrics more than one connector reports**:

```json
{
  "tenant_id": "…",
  "metrics": [
    {
      "metric_type": "steps",
      "definition": { "key": "steps", "unit": "count", "aggregation": "sum", "cadence": "daily" },
      "primary_source_id": "…",
      "primary_reason": "coverage",
      "sources": [
        { "source_id": "…", "source_type": "whoop",        "sample_count": 4210 },
        { "source_id": "…", "source_type": "apple_health", "sample_count": 1180 }
      ]
    }
  ]
}
```

`definition` is the metric's full registry entry, abbreviated above; see
[Metrics](../metrics.md) for the field set.

A metric with a single source needs no decision, and offering one would invite a reader to
state a preference that can never matter — so the list is empty for most workspaces, and
the card does not appear.

The sample counts are returned because they are what the automatic choice is made on: the
reader can see why the default is what it is. They come from the day rollups
(`metric_rollups`), not from a scan of `data_points` — the same grouping, one indexed
aggregate. See [Data resolution and rollups](data-resolution.md).

`PUT` names the connector:

```json
{ "primary_source_id": "…" }
```

and answers with `primary_reason: "preference"`. The metric name is canonicalised first, so
a registered alias is accepted and stored under its canonical key; an unrecognised name is
a `400`. A connector that does not belong to the authenticated workspace is a `404`.

`DELETE` removes the stated preference and answers with `primary_reason: "coverage"`,
meaning the choice is made by coverage again. Deleting the connector itself also clears any
preference naming it, through a composite foreign key that cannot cross workspaces
(rule 2).

One preference is stored per workspace and metric, in `metric_source_preferences`. A
missing row is not "no opinion recorded but needed" — it means the choice is made by
coverage, which is a defensible default and the common case. Only a deliberate override is
stored.

## What the analysis reports

The insights bundle carries the attribution rather than hiding it:

| Field | Contents |
| --- | --- |
| `metric_source_ids` | Per metric, the connector instances whose values were actually used |
| `source_issues` | One entry per ambiguous metric: `code`, `metric_type`, `source_ids`, `primary_source_id`, `primary_reason` |
| `metrics_excluded_for_quality` | Includes any metric for which no primary was named |

## Where this does not apply

- **Explorer** shows every connector's series separately and always has. Nothing is chosen
  or hidden there; a chart with two lines is the honest picture of two devices.
- **The Data Quality Center's conflict scan** is the opposite question. It reports where two
  connectors *disagree* on the same day beyond a tolerance, which is worth seeing whichever
  one answers for the metric. See [Data quality](data-quality.md).
- **The MCP tools** still refuse rather than choose. `query_metric_series` and
  `analyze_metrics` return the stable `AMBIGUOUS_METRIC_SOURCE` error unless the caller
  passes an explicit `source_id`; they do not fall back to the stored preference. See
  [Stateless MCP analytics](mcp.md).

## Interpretation and limitations

- A trend for an ambiguous metric describes **one connector's view** of it, not the
  workspace's. `metric_source_ids` in the bundle, and the card on the Analysis page, are
  where to check which one.
- The automatic choice is made on sample count, which is a proxy for coverage and not for
  accuracy. A cheap sensor that samples constantly will out-count an accurate one that
  reports daily. Where that matters, state a preference.
- **Coverage is counted over the whole history, so a replaced device keeps winning.** A
  connector retired a year ago can still hold the most samples and therefore still answer,
  even though the workspace has not heard from it since. That is the price of a choice that
  does not change between two views of the same data, and it is the case a stated preference
  exists for: after switching devices, name the new one. `metric_source_ids` in the analysis
  bundle always describes what that run actually used.
- Changing a preference changes what the analyses say. The bundle is recomputed rather than
  patched, so the numbers and the attribution always come from the same run.
- Two connectors that disagree are still two connectors that disagree. Choosing a primary
  answers "which value do we use", not "which value is right" — the conflict scan is the
  place that question is raised.
