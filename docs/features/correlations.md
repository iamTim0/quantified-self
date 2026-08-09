# Correlations and simple analyses

The correlations view assesses which metrics change together. The current approach is
deterministic and cheap to run.

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
