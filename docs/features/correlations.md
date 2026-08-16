# Correlations and simple analyses

The correlations view assesses which metrics change together. The current approach is
deterministic and cheap to run.

The whole bundle — correlations, lagged correlations, trends, anomalies, weekday patterns
and period comparisons — is computed once per data change rather than on every page load,
and read from the stored run together with the time it was computed. Changing the window or
the connector asks for a new run; the minimum-strength filter does not, because the
coefficients are already in the payload. See [Precomputed reports](precomputed-reports.md).

Where several connectors report the same metric, one of them answers for it and the bundle
says which — values from two connectors are never added or averaged. See
[Metrics from several connectors](metric-source-selection.md).

## Reading the Pearson coefficient

| Absolute value | Strength | Interpretation |
| --- | --- | --- |
| `0.00–0.19` | very weak | Practically no linear relationship. |
| `0.20–0.39` | weak | A thin pattern; collect more data. |
| `0.40–0.59` | moderate | An observable relationship — treat it as a hypothesis. |
| `0.60–0.79` | strong | A relevant pattern, but not causation. |
| `0.80–1.00` | very strong | A very clear shared course; check the data quality. |

## Sensible next algorithms

- Spearman correlation for monotonic, non-linear relationships.
- Rolling correlation for time-dependent patterns.
- Isolation Forest, or robust z-score scoring, for outliers.
- Small random-forest regressors per target metric, to estimate feature importance.

All of them must read tenant-scoped through Core over gRPC. The Analysis service never
opens a database connection of its own.

## Strength progression

"Am I getting stronger" is neither a correlation nor a trend over a daily series.
It is a question about **one exercise**, and the thing that identifies an exercise
— `exercise_title` — lives in a JSONB metadata field.

That shapes where the code lives. Core owns the database (rule 1) and is the only
service that can read that field; the Analysis Service holds no connection
(rule 3) and reads over gRPC. So Core gained one purpose-built call,
`QueryStrengthSets`, which reassembles the four `strength_set_*` metrics sharing a
`set_id` back into one row per set — a weight, its repetitions, the volume they
make and the peak pulse during it. No consumer wants those apart.

It is a dedicated RPC rather than a `group_by_metadata_key` dimension on
`QueryMetricSeries`. That message is the interface every analysis depends on, and
an almost-always-empty grouping field there would be a case every future reader had
to reason about, for one caller.

### What "stronger" is measured as

The basis is chosen per exercise, and reported, because it is not the same
question for every movement:

| Basis | When | Why |
| --- | --- | --- |
| `estimated_1rm` | A loaded lift at ten repetitions or fewer | Epley, `w × (1 + reps/30)`, over the heaviest set of each session |
| `volume` | A loaded lift trained above ten reps | Epley drifts high there and is not computed at all, so the load still has to count |
| `reps` | A bodyweight exercise | Its volume is zero at every session; reporting "flat" for somebody who went from eight pull-ups to fifteen would be a wrong answer, not a missing one |

An estimated one-rep max is a formula applied to a set, not a measurement, and the
payload says so in its own `disclaimer`. Above ten repetitions it is **not
computed** rather than computed and quietly high — a number wrong in a known
direction is worse than no number, because nothing downstream can tell it from a
good one.

### Sessions, not days

Progression is grouped by `session_id`, falling back to the calendar date for sets
stored before sessions existed (see [Workout detail](workout-detail.md)). Two
sessions in one day are two data points, which is what they are.

Fewer than four sessions reports no direction at all. Two points make a line
through any two numbers, and a line through two numbers is not a trend.
`direction` is `rising`, `falling` or `flat` — the same vocabulary
`trend_for_metric` already uses, and stable lowercase identifiers the dashboard
translates (rule 17).

### Muscle balance

Sets and volume per muscle group, as a **share**. The useful question is balance:
a thousand kilos of pulling means nothing without knowing what was pushed.
Bodyweight sets are counted even though they carry no volume — leaving them out
would make a calisthenics programme look like no training at all, so a workspace
with no loaded lifts reports set shares and a null volume share rather than
nothing.

### Limitations

- **Only Streak reports sets today.** A second strength source maps its exercise
  categories through the same `MuscleGroup` vocabulary; nothing here is
  source-specific.
- **Twenty exercises, ordered by total volume.** The cap keeps what somebody
  actually trains rather than what sorts first.
- **A shortened read says so.** `truncated` is set when the window held more sets
  than the pages read, so a partial history is not mistaken for a quiet block.
- **A failure to fetch sets does not empty the bundle.** The correlations and
  trends still compute; only `strength` comes back empty. A Core outage still
  propagates, because the worker has to tell "Core is restarting" from "this run
  failed".
