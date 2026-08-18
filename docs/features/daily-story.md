# The daily story

## Purpose

The landing page used to be a grid of cards holding whole-history statistics: the mean of
every step count ever recorded, beside the mean of every sleep score ever recorded, each
with its minimum and maximum. Every number on it was true, and none of them answered the
question somebody opens the page with, which is *what happened* — last night, yesterday,
and how much of today has arrived.

It also could not tell two different situations apart. An empty workout card meant either
**no workout** or **the workout connector last ran at 06:00**, and the page drew both as
the same blank. That turns an import schedule into a finding, which is the worst mistake a
summary can make: the reader acts on a gap that was never in their data.

The page is now one day at a time. **Today leads**, because it is the question most readers
ask first; **yesterday follows**, as far as the connectors have reported. The current day is
partial by construction, so every lane states when the connector feeding it last finished an
import. Each day is told in lanes — sleep, activity, workouts, heart, nutrition, … — with a
timeline of that day's discrete events underneath.

## Data flow

```text
Browser states its own UTC offset  (-new Date().getTimezoneOffset())
    -> GET /api/v1/data/day?day=<local date>&offset_minutes=<offset>   one call per day shown
    -> Gateway verifies the JWT, injects X-Tenant-ID and X-Request-ID
    -> Core turns the reader's calendar day into the UTC window it actually spans
    -> tenant-scoped queries, each aggregated in SQL:
         lane totals   sum/avg/max/count  GROUP BY metric_type, source_id
         events        the window's event-shaped points, in time order
         currency      max(sync_runs.finished_at) per connector, successful runs only
    -> one connector picked per metric several of them report
    -> lanes + timeline + per-lane completeness
```

One Core endpoint, aggregated server-side, reached over REST through the Gateway like every
other dashboard read. Nothing new crosses a service boundary and no service but Core touches
the database (rule 1).

The aggregation belongs on the server because the alternative was measured. The previous
page issued two queries — a whole-history metric summary and the newest thousand raw points
— and bucketed the points in the browser. A thousand points is simultaneously too much to
transfer and, for a workspace recording heart rate every minute, far too little to describe
a single day: 1,440 minute samples exhaust the budget before anything else is counted. The
day endpoint transfers one number per metric instead.

The lane totals are read from `data_points`, **not** from `metric_rollups`, and that is
deliberate rather than an oversight: the rollups are bucketed in UTC, which is the exact
problem this endpoint exists to solve (below). The scan is bounded by one day on the
hypertable's time dimension and by `tenant_id`, so it costs what a day holds rather than
what the workspace holds.

## Local days, not UTC days

This is the reason the feature is an endpoint at all rather than a client assembling
`/api/v1/data/metrics` calls.

Day rollups are bucketed with `date_trunc('day')` in UTC — see
[Data resolution and rollups](data-resolution.md) — and `GET /api/v1/data/metrics` takes no
timezone parameter of any kind. For a reader at UTC+2 that means a "day" running from 22:00
the previous evening to 22:00: a meal logged at 23:30 is filed under tomorrow, and the last
two hours of every evening are attributed to the wrong date. A page whose entire subject is
*one day* cannot be built on that.

`/api/v1/data/day` therefore takes `offset_minutes` — the reader's own UTC offset, which the
browser can state without being asked — and computes the UTC window that calendar day
actually spans:

| Reader | `day` | Window start (UTC) | Window end (UTC) |
| --- | --- | --- | --- |
| UTC+2 | `2026-08-16` | `2026-08-15T22:00:00Z` | `2026-08-16T22:00:00Z` |
| UTC | `2026-08-16` | `2026-08-16T00:00:00Z` | `2026-08-17T00:00:00Z` |
| UTC-5 | `2026-08-16` | `2026-08-16T05:00:00Z` | `2026-08-17T05:00:00Z` |

The window is exactly 24 hours whatever the offset, and points are selected on
`timestamp >= start AND timestamp < end`, so no point is counted in two days and none falls
between them. The window is echoed back in the response, so a caller can check what it was
answered about rather than reconstructing it.

The same parameter name, the same convention and the same ±960-minute bound are used by the
gap scan (see [Precomputed reports](precomputed-reports.md#asking-for-a-recomputation)),
because a reader whose day starts at a different moment on two pages of the same product is
being told two different things about the same data.

### A fixed offset is not a time zone

`-new Date().getTimezoneOffset()` states which offset the browser is in **right now**. It
does not say `Europe/Berlin`, which is UTC+1 for part of the year and UTC+2 for the rest.

The cost of that shortcut is exact and bounded: on the two days a year that contain a
daylight-saving transition, that day's window is an hour out at one end, and one hour of
points is attributed to the neighbouring day. Every other day of the year is exactly right,
and the error is one hour, on a day the reader knows is unusual.

Against that, UTC bucketing misfiles *offset-many hours of every day, every day of the
year*, and not by an hour — the point lands in the neighbouring day's bucket entirely, so
a 23:30 meal is simply not part of the evening it belonged to. Being wrong by an hour twice
a year in a way a reader can predict is a better failure than being wrong by a whole day
everywhere in a way nothing shows.

An IANA zone name would remove even the DST case; it would require the browser to send
`Intl.DateTimeFormat().resolvedOptions().timeZone` and the server to resolve it. That is not
what is implemented today.

## How complete a day is

Each lane carries two fields, and the day carries a third.

| Field | Where | Meaning |
| --- | --- | --- |
| `last_import_at` | lane | When the connectors feeding this lane last finished a successful import |
| `complete` | lane | That timestamp is at or after the end of the window |
| `complete` | day | Every lane is complete, at least one lane exists, and the day is not today |

`last_import_at` comes from `sync_runs`, not from `data_points`: an import is the only thing
that adds points, and `sync_runs` is a small indexed table. Where a lane is fed by more than
one connector it is the **oldest** of their newest successful runs, because a lane is only
as current as the least current connector behind it — a sleep lane fed by two devices is
stale the moment either of them is.

**Today is never reported complete.** The day-level flag is false whenever `is_today` is
true, whatever the import history says. `test_today_is_never_reported_complete` pins that
with a successful run whose `finished_at` is deliberately two days in the future: a day
still in progress cannot have had all of its events yet, and no amount of importing changes
that.

A day with no lanes at all is not complete either. `complete` requires at least one lane, so
*we hold nothing for this day* is never dressed up as *this day is fully accounted for*.

In the interface an incomplete lane states in plain text, next to its heading, when that
connector last imported or that it has never completed one. That is the whole point of the
field: **no workout** and **the workout connector last ran at 06:00** are two different
things on the screen.

The line is text rather than a tooltip on a glyph, and that is not cosmetic. `title`
attributes never fire on a touch device, so for the whole of this feature's first life the
distinction it exists to draw was invisible on exactly the device most readers open the page
on. The note stays legible while the lane is collapsed, for the same reason.

## One connector answers per metric

Two connectors both reporting `steps` are never added together. `steps` is a `SUM` metric
and both are describing the same walk, so summing them produces a plausible wrong number —
and a wrong number is worse than a missing one, because nothing distinguishes it from a
right one (rule 19).

The lane query therefore groups by `(metric_type, source_id)` and picks a winner afterwards,
through the same `resolve_primary_source` the gRPC series path and the preference card use.
The reuse is the point: the story and the analysis cannot name different connectors for the
same number. See [Metrics from several connectors](metric-source-selection.md) for how the
choice is made and how to state a preference.

Each lane metric reports the outcome rather than hiding it:

| Field | Contents |
| --- | --- |
| `source_id`, `source_type` | The connector that answered |
| `source_reason` | `only_source`, `preference` or `coverage` — stable English identifiers, not prose (rule 17) |
| `other_sources` | The connectors that also reported this metric that day and were not added to it |
| `sample_count` | How many points the answering connector contributed to the window |

`only_source` is the common case and the cheap one: a single connector reports the metric,
there is no decision to make, and no preference is looked up. The other two reason codes are
exactly those the analysis and the preference card use.

The single number a lane shows is chosen by the metric's registry aggregation: a `sum`
metric shows the day's sum, a `max` metric the day's maximum, and everything else the day's
average. See [Metrics](../metrics.md) for each metric's aggregation, and the limitations
below for what that does to `last` metrics.

## Sessions are regrouped

A workout is not stored as a workout. It arrives as a fan of metrics — `workout_duration`,
`workout_distance`, `workout_energy`, the heart-rate figures — that share one timestamp and
one `workout_name` in their metadata. Rendered individually, a 45-minute run is a dozen
unrelated numbers, which is a large part of what made the old page a card collection.

The endpoint groups them back into events. A point may be placed at an hour when its metric
name begins with `workout_`, `strength_set_` or `strength_session_`, or is
`calendar_meeting_duration`. Everything else either describes the day rather than a moment in
it — and belongs in a lane — or was *logged for* a day rather than *at* a time, and belongs
in the day's log below.

!!! warning "A stamp that means "some time that day" must not become an hour"
    `nutrition_item_energy` and `nutrition_meal_energy` used to be on this list. Yazio stamps
    every item of a day at that day's midnight UTC, so rendering those points on a timeline
    put a reader's entire food intake at **02:00** in CEST — every item at the same wrong
    hour, which reads as a fact about the day rather than as an artefact of how a diary is
    stamped.

    They are now told as [the day's log](#the-days-log), grouped by meal, with a clock time
    shown only where the provider stated one in `metadata.logged_time`. Re-stamping them in
    the importer would be the other fix and is the wrong one: the timestamp is part of the
    idempotency key (rule 4), so changing it does not correct the existing points, it
    duplicates every one of them.

| Field | Contents |
| --- | --- |
| `at` | The shared timestamp of the session's points |
| `until` | The first of `end`, `end_time`, `workout_end_time`, `sleep_end` found in the metadata, when present |
| `title` | The first of `workout_name`, `activity_name`, `summary`, `food_name`, `meal_category` found in the metadata |
| `category` | The registry category of the metrics, which is also the lane the event belongs to |
| `measures` | Every metric of that session, by canonical name |

`until` is the one metadata field that changes what the timeline draws — it is the
difference between a moment and a span.

!!! info "Points carry a session identifier now — but not all of them"
    Every importer that emits a workout writes a `session_id` at ingest
    (`shared_schemas.sessions`), and this endpoint groups on it through the shared
    `core.sessions.session_group_key`. Eighteen sets logged a minute apart are one
    event rather than eighteen.

    **Rows stored before that cannot gain one.** Rule 4 keys a point on
    `(tenant, source, metric, timestamp)` and Core inserts `ON CONFLICT DO NOTHING`,
    so a re-import does not touch an existing row's metadata. Those rows still group
    on the timestamp plus a metadata title, which fails in both directions: two
    sessions a provider stamped alike merge into one event, and one session whose
    points were stamped a second apart splits into two.

    A workout whose rows straddle the change therefore appears as **two** events.
    That is bounded and deliberate — what never happens is one row in both, because
    its measures would then be counted twice. See
    [Workout detail](workout-detail.md) and `specs/workout_sessions.fizz`.

## The day's log

Some things are recorded *for* a day rather than *at* a time. Food is the case that
matters: a diary app knows what was eaten on the 15th, and often knows nothing more precise
than that.

These arrive in `logged`, grouped by `meal_category`, ordered breakfast → lunch → dinner →
snack with anything else after them under its own name. Each group carries:

| Field | Contents |
| --- | --- |
| `group` | `breakfast`, `lunch`, `dinner`, `snack` or the provider's own name — a stable identifier, never prose (rule 17) |
| `energy` | The meal's total |
| `energy_derived` | `true` when that total is our sum of the items, `false` when the provider stated it outright |
| `entries` | The individual items, each with `title`, `value`, `unit`, `amount`, `serving_unit` |
| `logged_at` | The clock time the provider stated, where it stated one; `null` otherwise |

`energy_derived` is rule 19 in one field. A meal that arrives with both a stated total and
its individual items holds two different claims about one meal, and adding them together is
the double count the rule exists to prevent — so the stated figure wins and the derived one
is marked as derived rather than passed off as measured.

`logged_at` comes from `metadata.logged_time`, which the Yazio importer has always written
and which nothing read until now. Where it is present the interface shows it; where it is
absent no hour is invented.

## Reading it through the API

```http
GET /api/v1/data/day?day=2026-08-15&offset_minutes=120
```

| Parameter | Range | Default |
| --- | --- | --- |
| `day` | The reader's calendar date. Not in the future, and at most 366 days ago | The reader's today, derived from `offset_minutes` |
| `offset_minutes` | ±960 (16 hours), the reader's UTC offset | `0`, i.e. UTC |

A day that has not happened yet is a `400`, and so is one more than 366 days back — this is
a reading view of recent days, not an export surface. For arbitrary windows use
`GET /api/v1/data/metrics` ([Data resolution and rollups](data-resolution.md)), remembering
that it buckets in UTC.

```json
{
  "tenant_id": "…",
  "day": "2026-08-15",
  "window": { "start": "2026-08-14T22:00:00+00:00", "end": "2026-08-15T22:00:00+00:00" },
  "offset_minutes": 120,
  "is_today": false,
  "complete": true,
  "lanes": [
    {
      "category": "activity",
      "last_import_at": "2026-08-15T23:04:11+00:00",
      "complete": true,
      "metrics": [
        {
          "metric_type": "steps",
          "value": 8412.0,
          "unit": "count",
          "aggregation": "sum",
          "cadence": "daily",
          "sample_count": 1,
          "source_id": "…",
          "source_type": "apple_health",
          "source_reason": "coverage",
          "other_sources": ["…"],
          "last_at": "2026-08-15T21:00:00+00:00"
        }
      ]
    }
  ],
  "events": [
    {
      "at": "2026-08-15T16:00:00+00:00",
      "until": "2026-08-15T16:45:00+00:00",
      "title": "Running",
      "category": "workout",
      "source_id": "…",
      "measures": { "workout_duration": 2700.0, "workout_distance": 8200.0 }
    }
  ],
  "event_limit_reached": false,
  "logged": [
    {
      "group": "breakfast",
      "category": "nutrition",
      "energy": 412.0,
      "energy_derived": true,
      "unit": "kcal",
      "entry_count": 2,
      "logged_at": "2026-08-15T07:05:00",
      "entries": [
        {
          "title": "Porridge",
          "metric_type": "nutrition_item_energy",
          "value": 320.0,
          "unit": "kcal",
          "logged_at": "2026-08-15T07:05:00",
          "amount": 60.0,
          "serving_unit": "g"
        }
      ]
    }
  ],
  "logged_limit_reached": false
}
```

| Field | Meaning |
| --- | --- |
| `window` | The UTC span the answer covers, so a caller need not recompute it |
| `is_today` | The requested day is the reader's current day |
| `complete` | Every lane is current, at least one lane exists, and the day is finished |
| `lanes` | Non-empty categories only, in the order a day happens: sleep, activity, workout, strength, heart, nutrition, body, location, calendar, environment, home |
| `events` | The day's discrete moments in time order, at most 200 |
| `event_limit_reached` | The 200-event cap was hit and the timeline is truncated |
| `logged` | What was logged for the day, grouped by meal — see [The day's log](#the-days-log) |
| `logged_limit_reached` | The 200-entry cap was hit and the log is truncated |

Every query filters on the `tenant_id` the Gateway injected (rule 2).
`test_a_day_shows_only_the_authenticated_tenants_data` verifies the Fizzbee invariant
`StrictTenantIsolationOnRead`: asked for another workspace's day, the endpoint answers with
empty lanes and events rather than with somebody else's morning.

## In the interface

The landing page renders two of these — today, then yesterday — from the stored report. Today
leads because it is the first question the reader asks; its **Still arriving** badge and each
lane's last-import timestamp make its partial coverage explicit rather than presenting a gap
as a fact.

**Three numbers, then everything else on request.** The page opens with up to three headline
figures for the day — sleep duration, steps, energy intake, falling through a fixed priority
list of canonical registry keys to whatever the day actually holds. A day with fewer shows
fewer; no slot is ever filled with an invented figure, because a headline is precisely where
one would be believed. Each carries the previous day's difference beside it, which costs
nothing: the report already contains both days.

The difference is deliberately not coloured by direction. Whether more steps is good and
more body weight is bad is a judgement about a reader's goals that this platform does not
hold, and a green arrow would state one anyway.

Everything below the headline is a collapsed section — one per lane, one for the timeline,
one for the day's log, one for the map — each labelled with what it contains ("4 values",
"12 events", "1,830 kcal") so a closed section is still navigable. A single **Expand all**
switch per day covers the wide-screen case, where a column of closed rows would be a click
per fact. The default is the same on a phone and in a browser: a default that varies by
width makes "why is this one open" unanswerable.

- Today's heading carries a **Still arriving** badge, from `is_today`.
- An incomplete lane states its last import as a visible line, which survives collapsing.
- A metric more than one connector reports names the connector that answered, and the lane
  says once that the two are never added together.
- The timeline lists each event's clock time, its title and its first three measures, with a
  truncation note when `event_limit_reached` is set.
- The map is mounted only when its section is opened — required, not merely thrifty: Leaflet
  sizes itself from its container, and a container inside a closed `<details>` has no box.

All of these use the shared `Disclosure` component, which is a native `<details>`/`<summary>`
pair. Keyboard operation and the expanded state announced to assistive technology come from
the element rather than from hand-written ARIA, and each section title stays a real heading
so collapsing the page does not delete its outline.

Every string comes from the message catalogue under `day.*`, in both languages (rule 16);
dates, timestamps and lane values are formatted through `useI18n()` rather than against a
hardcoded locale. Category names are mapped from the server's stable identifiers to
catalogue keys in the component, so the server never sends prose (rule 17).

The page reads a **stored report**, not a fresh computation. Aggregating a day of points on
every visit was the same mistake as the whole-history summary it replaced, in a smaller
frame: for a workspace with per-minute sampling and a location trace that is six figures of
rows, twice, for an answer that cannot change until an import does. It is a report like the
gap and conflict scans — see [Precomputed reports](precomputed-reports.md) — so the reader
sees the last good answer with a note when newer data has arrived.

## Interpretation and limitations

- **The timeline is capped at 200 events** (`MAX_EVENTS`), and `event_limit_reached` says
  when the cap was reached. A day holding a GPS trace and per-minute samples can contain
  tens of thousands of rows, and a timeline that tried to draw them all would hang the
  browser in order to say nothing extra.
- **The scan behind that cap is bounded at 4,000 rows** (`MAX_EVENT_ROWS`). The query
  filters for event-shaped metrics in SQL, so lane data — per-minute heart rate, a location
  trace — cannot consume that budget before the evening is reached. `event_limit_reached`
  reports the row ceiling as well as the event one, so a shortened timeline says so.
- **A workout and a strength session appear on the timeline, not in a lane.** Every
  `workout_*` and `strength_*` key is event-shaped, so those categories are usually empty as
  lanes; summing three sessions' `workout_duration` into one daily figure would answer a
  question nobody asked. `whoop_workout_strain` is the exception and does appear as a lane.
- **`workout_heart_rate` is neither.** It is a series *inside* a session, not a figure
  about one, and at second resolution a 90-minute workout is 5,400 rows against a
  4,000-row scan budget — so the timeline would come back truncated for anyone who
  trains. It is excluded from both halves (`core.sessions.STREAM_METRICS`) and read
  through [Workout detail](workout-detail.md) instead.
- **A session's measures are collapsed by the registry's aggregation**, not summed.
  Grouping eighteen sets into one event and adding their `strength_set_weight` would
  report 1,850 kg as a set weight; `MAX` reports the heaviest set, which is what the
  registry says that metric means.
- **The primary source is resolved from whole-history coverage** (looked up only when a
  metric actually has more than one source that day), among the connectors that reported it. On a day where a new device recorded everything and an old one
  contributed a single stray reading, the old one can still answer if it has more history
  behind it. State a preference where that matters.
- **A lane's `complete` compares against the end of the window**, which for today is
  tomorrow's local midnight. A today lane is therefore effectively never complete — correct,
  but uninformative. `last_import_at` is the field to read for how current today's data is.
- **Completeness describes the connector, not the provider.** An import that finished after
  the day ended proves the platform asked; it does not prove the provider had already
  published everything for that day. A device that syncs to its vendor's cloud the next
  morning will still leave a hole in a lane marked complete.
- **`sample_count` is points, not coverage.** One daily total from a provider and 1,440
  minute samples both fill a lane entry; the count is how the difference shows.
