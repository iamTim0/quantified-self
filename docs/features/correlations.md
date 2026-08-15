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
