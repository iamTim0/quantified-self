# Data quality

The Data Quality Center shows whether the data is complete, free of contradictions and fit
for analysis.

## Indicators

| Indicator | Meaning | Recommendation |
| --- | --- | --- |
| Data gaps | Days without a value, for metrics that are expected daily (see below) | Check the connector, renew the token, or start the sync again. |
| Source conflicts | Values for the same metric differ noticeably between sources | [Pick a primary source](metric-source-selection.md), or check the units. |
| Not yet supported | Fields a connector receives and this platform does not store | Copy the shape-only report, or resolve a held metric below. |
| Now supported | Fields that used to arrive unstored and are stored now | Re-import that period if the connector can be asked for it again. |
| Held for decision | Point values whose metric name is not yet recognised | Map, adopt, discard or keep the connector-specific name. |

The gap scan and the conflict scan walk the workspace's history, so they are not computed
when the page opens: the Data Quality Center reads the last scheduled run and shows when it
was computed, whether newer data has arrived since, and a **Recompute** button. The other
three lists on the page are small indexed reads and stay live, because a mapping rule has to
take effect the instant it is saved. See [Precomputed reports](precomputed-reports.md).

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

### Is it supported *now*?

A field leaving the unsupported list is not, by itself, an answer. It is
indistinguishable from a field that simply stopped arriving — and the question a user
comes back with is the other one: *the thing I reported as missing, does it work now?*

`supported_since` records the transition. It is set once, by the same upsert, at the
moment a row's `metric_type` goes from `NULL` to a name, and never cleared. The
**Now supported** panel lists those transitions from the last 90 days.

!!! info "Re-checking is a property of importing, not of a sweep"
    Whether a provider field maps to a metric is decided by that provider's
    transformer, which lives in the importer. Core holds no such table and could not
    evaluate it, so there is no server-side job that could re-check support on a
    timer.

    It does not need one. Every scheduled import re-reports the field it saw, and the
    upsert records the transition for free. The list fills itself in as connectors
    run, which is as often as the data itself is re-checked.

**Earlier data** says whether the gap is recoverable, and it is a real distinction
rather than a hedge. A pull connector can be asked for the same period again, so a
force import over `unstored_from … unstored_until` recovers what was never kept. A
**push** connector's history exists only on the device that sent it — Apple Health
pushes what the phone decides to push — and nothing here can ask for it again. Saying
so is better than offering a button that silently does nothing.

!!! warning "A field could previously be un-supported by one odd payload"
    The upsert overwrote `metric_type` unconditionally. One import that saw a path in
    a shape its transformer had no rule for — a provider omitting the field it usually
    nests under, an entry of an unfamiliar kind — flipped an established mapping back
    to `NULL`, and the field reappeared under **Not yet supported** while being stored
    perfectly well. It now uses `coalesce`, so support is only ever gained.

The report is collapsed by default so it does not compete with the active quality indicators.
It is a live schema report, not a deletion queue: a field leaves the list after an importer
starts storing it, while historical shape observations remain available for audit. Nothing is
automatically deleted when support is added, and no provider payload is retained to make this
report.

### Roadmap

Filing that report automatically as a GitHub issue is the obvious next step and is deliberately
not built yet: it is an outward-facing action needing its own credential, and a report that
leaves the machine on its own should be a decision the user makes each time, not a setting.

## Resolve held metric values

An importer event whose `metric_type` is neither a canonical registry key nor an allowed
dynamic namespace is not written to `data_points` and is not silently dropped. Core stores one
tenant- and connector-scoped quarantine row for the point, including its value, timestamp,
provider provenance metadata and original idempotency key. The row is not returned by metric
queries, analyses or exports while it is held. Whole provider payloads are never stored.
When a provider has several child records at the same timestamp, Core also retains their
connector-scoped logical source identity so replay cannot merge those records.

The Data Quality Center groups held rows by connector and unresolved name. Each name has a
per-connector rule with one of four outcomes:

- **Map** selects an existing canonical registry metric and the unit the source stated. Core
  converts the value to the registry unit and replays it with a newly derived canonical
  idempotency key.
- **Adopt** creates a tenant-local `custom_` metric name with an explicitly declared unit,
  aggregation and cadence. This does not extend the shared registry or create a bare metric.
- **Discard** marks every matching held row discarded and records the decision, so future
  arrivals are acknowledged without filling the queue again.
- **Keep** stores the rule but leaves the rows held for a later decision.

Replay is a normal tenant-scoped Core transaction and creates a `mapping_replay` entry in the
connector's sync history. `ON CONFLICT DO NOTHING` makes a repeated replay safe; each held row
ends in exactly one terminal state, promoted or discarded, never both. The quarantine is
bounded per connector by distinct unresolved names and point rows. Refusals are counted in a
separate shape-only audit table rather than being silently lost; that audit is bounded too, with
additional refused names aggregated into an overflow bucket.

Held rows expire after 30 days by default when they have not been seen again. The Data Quality
Center exposes an explicit **keep indefinitely** choice for a name when that is appropriate;
there is no accidental unbounded retention.

### Quarantine capacity warnings

The quarantine is bounded per connector so one provider export cannot turn unresolved metric
names into unbounded database growth. Core reports both dimensions to the Data Quality Center:

- **100 distinct unresolved names** per connector.
- **100,000 active point rows** per connector.

The interface shows a notice as soon as a connector has held values, a clear warning at 50% of
either limit, and an urgent warning at 75%. At 100%, new unknown values are refused rather than
held for a later mapping decision. A refusal audit records the connector, reason and count, but
not the refused value; those values must be re-imported after the mapping is resolved. Existing
held rows are not deleted when a threshold is crossed.

The warning is evaluated against whichever dimension is closer to its limit. If a connector has
already produced refusals, that state remains the highest-priority warning even if mapping rules
later free some quarantine space. The dashboard refreshes this status while the Data Quality
Center is open, so a large import does not need a manual page reload to surface the escalation.

Rules are connector-specific: the same provider name can mean different things in two feeds.
They are intentionally not aliases in the shared registry. If the same resolution appears
across connectors, that is evidence for a reviewed registry alias or importer fix; a tenant
rule never redefines a catalogued name and nothing is exported automatically.
