# Data quality

The Data Quality Center shows whether the data is complete, free of contradictions and fit
for analysis.

## Indicators

| Indicator | Meaning | Recommendation |
| --- | --- | --- |
| Data gaps | Days without a value, for metrics that are expected daily (see below) | Check the connector, renew the token, or start the sync again. |
| Source conflicts | Values for the same metric differ noticeably between sources | Pick a primary source, or check the units. |
| Not yet supported | Fields a connector receives and this platform does not store | Nothing to fix on your side — copy the report and open an issue. |

## How to read it

- **0 gaps**: the data is fit for simple trends and correlations.
- **1–3 gaps**: the analysis is usually usable, but read outliers carefully.
- **Several gaps**: recommendations may be skewed; repair the data source first.

## What counts as a gap

A missing day is only a gap for a metric that is *supposed* to produce a value every day.
The metric registry records this as a **cadence**, and every metric has one:

| Cadence | Meaning | Gaps reported |
| --- | --- | --- |
| `daily` | One value per day is the expectation — steps, sleep duration, resting heart rate | A day without a value is a gap |
| `continuous` | Sampled far more often than daily, at a rate the device chooses — heart rate, weather | Judged against the cadence actually observed, not against calendar days |
| `event` | Happens when it happens — workouts, weigh-ins, calendar entries, GPS points | Never. Absence carries no information |

Before this distinction existed, every metric was judged against the calendar. A rest day was
therefore a "gap" in workout duration, a scale stepped on twice a month made body weight look
93 % broken, and the gap list was long enough to be worth ignoring — which is the worst thing
a warning can be.

The same cadence decides what "too thin" means in the analyses. Coverage used to be measured
against the calendar there too, so nothing event-driven could ever clear the 50 % threshold:
body weight, workouts and every calendar metric were permanently excluded from every analysis
for having exactly the density they are supposed to have. The minimum *sample size* still
applies to all of them — a correlation over five points is not worth showing however sparse
the metric legitimately is.

Days are bucketed in the reader's own time zone. Bucketed in UTC, a reading taken at 00:30 in
Berlin fell on the previous day, so the first and last day of every window were systematically
misreported.

## Fields that are not stored yet

Importers record which provider fields they read and which they saw and ignored, and the
Data Quality Center lists the second group under **Not yet supported**.

This answers a question that was previously unaskable: *is my device sending something that
never arrives?* It was not a hypothetical — Apple Health heart rate, blood pressure, workout
energy and workout distance were all being dropped without a word, under field names the
importer did not read. Nothing failed, so nothing said so.

**Only shapes are recorded, never values.** A row holds a field path, the *kind* of value that
sat there (`number`, `string`, `array`, …), how often it was seen and when it was last seen.
Keeping payloads instead would mean a second copy of the most sensitive data in the system,
with its own retention question, and would make the one-click account deletion incomplete
unless it hunted that copy down too.

The table is keyed per (workspace, connector, field path) and upserted, so it grows with the
*provider's schema* rather than with the amount of data — a few hundred rows however many
years pass through. It cascades from both the workspace and the connector, so deleting either
takes the observations with it.

**Copy report** produces a Markdown block of field names, types and counts — no values, no
identifiers — ready to paste into an issue.

### Roadmap

Filing that report automatically as a GitHub issue is the obvious next step and is deliberately
not built yet: it is an outward-facing action needing its own credential, and a report that
leaves the machine on its own should be a decision the user makes each time, not a setting.
