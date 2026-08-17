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

## Reading the correlation coefficient

| Absolute value | Strength | Interpretation |
| --- | --- | --- |
| `0.00–0.19` | very weak | Practically no linear relationship. |
| `0.20–0.39` | weak | A thin pattern; collect more data. |
| `0.40–0.59` | moderate | An observable relationship — treat it as a hypothesis. |
| `0.60–0.79` | strong | A relevant pattern, but not causation. |
| `0.80–1.00` | very strong | A very clear shared course; check the data quality. |

## What the calculations mean

The bundle is descriptive and exploratory. It is not a clinical instrument, an
experiment, or a causal model. Every pair is aligned on shared UTC calendar days;
days with a missing value are not imputed. The minimum overlap is ten days, and
metrics with insufficient coverage are left out rather than presented as weak
evidence.

For each eligible pair the service calculates Pearson's product-moment correlation
for a linear relationship and Spearman's rank correlation for a monotonic
relationship. The displayed coefficient is the one with the smaller absolute
magnitude, a conservative choice when outliers or non-linearity make the two
statistics disagree. The two-sided p-value uses the correlation t statistic with
`n - 2` degrees of freedom. This test assumes independent paired observations,
approximately linear residual behaviour for Pearson, and does not repair
autocorrelation, confounding, measurement error, or missing-not-at-random data.
See the [NIST Engineering Statistics Handbook](https://www.itl.nist.gov/div898/handbook/)
for the assumptions and interpretation of correlation statistics.
The original methods are described by
[Pearson](https://doi.org/10.1098/rspl.1895.0041) and
[Spearman](https://doi.org/10.2307/1412159). For why serial correlation reduces
effective information in time-series inference, see
[Pyper and Peterman](https://doi.org/10.1139/f98-104).

The matrix tests many pairs at once. Its `q_value` is the Benjamini–Hochberg
false-discovery-rate adjustment over all eligible pairs in that report; the
`significant` flag uses `q ≤ 0.05`, not the raw p-value. The unadjusted p-value is
still shown for auditability. Benjamini and Hochberg's original paper describes
the procedure and its independence/positive-dependence assumptions:
[Controlling the False Discovery Rate](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x).
Pairs are a hypothesis-generating view, so even an adjusted result needs a
pre-specified follow-up or experiment before it can support a claim.

### Other panels

- **Time-shifted relationships** search lags from one to seven days and retain the
  strongest absolute Spearman association for each ordered pair. This selection
  is explicitly exploratory and its p-values are unadjusted across the tested
  lags and pairs; a time order is not evidence of causation.
- **Trends** fit an ordinary least-squares line to the daily series and report its
  slope, `R²`, and a trailing seven-day mean. A low `R²` or a slope smaller than
  one tenth of the observed spread is labelled flat/uncertain. Seasonality,
  autocorrelation, and a short window can make a line look more certain than it
  is.
- **Outliers** use the personal median and median absolute deviation (MAD). MAD
  is multiplied by `1.4826` to be comparable with standard deviation under a
  normal distribution; the normal band is the median ± two scaled MADs and a
  robust z-score of `2.5` marks an unusual day. MAD is preferable to a mean and
  standard deviation when long tails are present; see [NIST on robust scale
  measures](https://itl.nist.gov/div898/handbook/eda/section3/eda356.htm).
- **Weekday patterns** report the arithmetic mean for each weekday and compare
  weekday with weekend means only when both groups have enough observations.
  This is a descriptive comparison, not a test that a weekday causes a value.
- **Period comparisons** use two windows and a Welch two-sample t-test, allowing
  unequal variance and sample size. They are still observational comparisons and
  do not identify why the means differ.

## Weekday patterns

`routines` holds the mean per weekday and how far the weekend departs from the working week.
Each entry names its day with a **stable lowercase identifier** — `monday` through `sunday`,
in `date.weekday()` order, so the nth entry is the nth day and a chart can draw them as they
arrive.

It is an identifier and not a word on purpose. The field held German day names, which put the
reader's language in the service's hands: an English reader was shown `Montag`, and the
interface had no way to say otherwise. Naming the day and saying it are two jobs, and only
the second one knows what language the reader chose (rule 17). The dashboard renders these
through `weekday.<id>` in both catalogues, and falls back to whatever the server sent for a
value it does not recognise — which is what keeps a report stored before this change readable
until it is recomputed.

All analysis inputs are read tenant-scoped through Core over gRPC. The Analysis
service never opens a database connection of its own. Whole raw provider payloads
are not retained; the report carries the selected source, window and analysis
version so a result can be reproduced after the next import.

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
