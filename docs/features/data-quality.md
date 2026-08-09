# Data quality

The Data Quality Center shows whether the data is complete, free of contradictions and fit
for analysis.

## Indicators

| Indicator | Meaning | Recommendation |
| --- | --- | --- |
| Data gaps | Days without a value for a metric, within the 30-day window | Check the connector, renew the token, or start the sync again. |
| Source conflicts | Values for the same metric differ noticeably between sources | Pick a primary source, or check the units. |

## How to read it

- **0 gaps**: the data is fit for simple trends and correlations.
- **1–3 gaps**: the analysis is usually usable, but read outliers carefully.
- **Several gaps**: recommendations may be skewed; repair the data source first.
