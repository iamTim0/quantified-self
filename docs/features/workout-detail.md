# Workout detail

## Purpose

A workout is stored as a fan of unrelated rows. `workout_duration`,
`workout_distance`, a dozen heart-rate figures, a GPS trace and a set of squats all
land in `data_points`, and nothing in that table records that they are one thing.
The daily story reconstructed sessions from a shared timestamp plus a metadata
title, and [said so itself](daily-story.md): two sessions a provider stamped alike
merged into one, and one session whose points differed by a second split into two.

This feature makes a session a thing you can open. Every importer that emits a
workout now writes a **session identifier** at ingest, and two endpoints read it
back: a list of sessions, and one session in full — its route, its per-second
pulse, its sets grouped by muscle group, and **every reading any other connector
took while it was happening**.

That last part is the point. The weather connector and the sleep tracker know
nothing about a workout; they appear because their readings fall inside its span,
which is what "during my workout" means.

## Data flow

```text
Importer resolves the session (shared_schemas.sessions.session_metadata)
    -> session_id, session_start, session_end, session_origin in each point's metadata
    -> qs.ingest.<source> -> Core -> data_points

Browser
    -> GET /api/v1/data/workouts?start_date&end_date&offset_minutes&category
    -> GET /api/v1/data/workouts/{session_key}
    -> Gateway verifies the JWT, injects X-Tenant-ID and X-Request-ID
    -> Core resolves the session's window, then queries that window five ways
```

Nothing new crosses a service boundary: the Gateway already proxies
`/api/v1/data/*` generically, and Core remains the only service touching the
database (rule 1).

## The session identifier

`shared_schemas/sessions.py` is the only place a session id is minted — one
definition, for the reason `events.py` gives about the idempotency hash being
copied nine times with nothing checking that the nine agreed.

| Key | Meaning |
| --- | --- |
| `session_id` | `<source_type>:<16 hex>` — `sha256(source_id \| local key)`, truncated |
| `session_start` / `session_end` | The session's own bounds. `session_end` is **omitted** when the provider states none, never invented |
| `session_origin` | `provider` or `derived` — rule 19's declaration |
| `session_derived_from` | The fields the digest stands on, when derived |

`source_id` is inside the digest so two phones do not merge, for the same reason it
is inside the idempotency key. `source_type` stays outside it so a human reading a
row can tell where the session came from.

| Source | Derived from | Origin |
| --- | --- | --- |
| Streak | `workout.id` | provider |
| WHOOP (`kind == "workout"`) | `record.id` | provider |
| Apple Health, webhook | `workout.id`, else start + activity name | provider / derived |
| Apple Health, archive | `startDate` + `workoutActivityType` | derived |

!!! warning "A re-import does not retrofit this"
    Rule 4 keys a point on `(tenant, source, metric, timestamp)` and Core inserts
    `ON CONFLICT DO NOTHING`, so **a point already stored can never gain a session
    id by being imported again**. A workspace holds tagged and untagged rows side
    by side indefinitely.

    The read path handles both. A workout whose rows straddle the change appears as
    **two** sessions rather than one, marked `identity: "timestamp_title"` in the
    payload and annotated in the interface. What never happens is one row in both
    groups — its measures would then be counted twice, and a doubled number is
    indistinguishable from a right one (rule 19). `specs/workout_sessions.fizz`
    model-checks exactly that, and `test_tagged_and_untagged_points_never_share_a_session`
    pins it.

    To upgrade history deliberately, wipe and re-import (see
    [Operations](../operations.md)). One case is not recoverable at all: Apple
    Health's **webhook** route fixes carry only a workout name, and nothing ties a
    fix to a session start. They still appear on the detail page, because the
    detail resolves by *window* and never depends on the tag.

## Per-second heart rate

Two changes made a workout's pulse visible.

**The samples are kept.** A Health Auto Export workout carries `heartRateData`, an
array of per-interval samples. It used to be collapsed into a mean and a maximum
and then discarded — two numbers for ninety minutes. Those two aggregates are still
emitted, and the samples now become `workout_heart_rate` points as well.

That is a separate key from `heart_rate`, which is a rule 15 judgement worth
stating since both are bpm. Apple sends `metrics[].heart_rate` (interval summaries)
*and* `workouts[].heartRateData` (per sample) covering overlapping wall-clock time
in separate pushes. Under one name they interleave without aligning, so
`sample_count` and the min/max envelope would stop meaning anything, and the two
could not be retained differently.

**`heart_rate` moved from minute to second resolution.** A minute mean of an
interval session is a flat line. See
[Data resolution and rollups](data-resolution.md#the-second-tier) for why that costs
almost nothing.

### Two ways a pulse figure was wrong

Both were fixed together, because both produce a number that looks measured.

**An average weighted by nothing.** A stored `workout_heart_rate` point is a bucket
mean, and `bucket_samples` records how many readings it averages — a second can hold
one reading or sixty. `core.rollups` has always weighted by it; every read path took
a bare `avg()`. So one stray sample at 60 bpm counted for as much as a full minute at
160, the detail page and `metric_rollups` reported different averages for one
dataset, and the drawn line could sit outside the min/max band under it. The read
paths now use `daily_story.weighted_average()`, which weights by `bucket_samples` and
by nothing else — `sample_count` is rule 19 provenance that importers also set on
figures which are not means (WHOOP's zone shares carry the number of zone fields),
and weighting by that produces an average nobody can account for.

**A neighbour's pulse.** The window is the join, and for ambient readings it has to
be — weather and another device's continuous metrics carry no session id and never
will. But `workout_heart_rate` *does* carry one. With a 15-minute pad at each end,
two sessions half an hour apart overlap, and the second one's pulse was drawn as the
first one's. `_not_another_sessions_stream` drops a **stream** row that states an id
other than this session's, and only that: a stream row carrying no id keeps the
window as its only evidence, which is all a pre-`session_id` row has ever had, and
ambient series are untouched.

## Reading it through the API

### The list

```http
GET /api/v1/data/workouts?start_date=2026-07-17&end_date=2026-08-16&offset_minutes=120&category=all&limit=50
```

| Parameter | Range | Default |
| --- | --- | --- |
| `start_date` / `end_date` | The reader's calendar dates, at most 366 days apart | Last 30 days |
| `offset_minutes` | ±960, the reader's UTC offset | `0` |
| `category` | `all`, `workout`, `strength` | `all` |
| `limit` | 1–200 | 50 |

`offset_minutes` bounds the range through the same `day_window` the daily story
uses. A reader whose day starts at a different moment on two pages of one product
is being told two different things about one dataset.

`all` means every *session* — that is, `workout_*` and `strength_*` — and nothing
else. It is not "every entry that happened at a time".

!!! warning "A meal and a meeting are not workouts"
    This list once shared one "event metric" set with the day timeline, which also
    holds `nutrition_item_energy`, `nutrition_meal_energy` and
    `calendar_meeting_duration`. `category=all` applied no narrowing on top of it, so
    every logged food item and every calendar entry was grouped into a session and
    returned here — titled, because `sessions.TITLE_FIELDS` reads `food_name` and
    `summary` to name a card. A list of workouts that contains a banana and a
    stand-up cannot answer anything about training.

    The two definitions are now separate predicates in `core.daily_story`:
    `session_metric_predicate()` for this list, `timeline_metric_predicate()` for the
    timeline, `logged_metric_predicate()` for the day's log, and
    `entry_metric_predicate()` — the union — for what a lane total must exclude.
    A workout's *surroundings* excludes the union too: `nutrition_item_energy` is a
    `SUM`, so a session straddling lunch would otherwise report the meal's calories
    as a figure measured during it.

Each session carries `session_key` (the opaque handle for the detail), `identity`,
`start`, `end`, `title`, `category`, `measures`, `units`, `point_count`,
`exercise_count` and `muscle_groups`. `scan_limit_reached` says when the range held
more rows than one scan reads.

`has_route` and `has_streams` are deliberately absent: answering them would need a
second full scan to decorate a list, which is the expensive-derivation trap
[Precomputed reports](precomputed-reports.md) exists to avoid.

### One session

```http
GET /api/v1/data/workouts/{session_key}?pad_seconds=120&stream_points=500&route_points=1000
```

The response has five parts, each from one bounded query:

| Part | What it holds |
| --- | --- |
| `measures` | The session's own figures, each with `provider_value`, `units`, `derived_by`, `derived_from` and `sample_count`, so a number this platform worked out never passes for one the provider stated |
| `strength` | Sets grouped by exercise and muscle group, with `total_volume`, `total_reps` and `top_set_weight` per exercise |
| `streams` | Continuous series inside the window, decimated in SQL to a mean **plus a min/max envelope** |
| `route` | The GPS track as a simplified GeoJSON `LineString`, a **measured** length, and per-fix samples |
| `surroundings` | One aggregate per `(metric, connector)` for everything else in the window |

### The session key

```text
base64url("v1|s|<epoch ms>|<session_id>")
base64url("v1|t|<epoch ms>|<source_id>|<title>")
```

Both variants carry the start timestamp, and not for decoration: without it,
resolving `metadata->>'session_id'` has nothing to bound the hypertable's time
dimension and the query walks a whole history to find a 45-minute run.

**Unsigned, deliberately.** Every query behind it filters on the tenant the Gateway
injected (rule 2), so a forged key can only ever address the caller's own
workspace. `test_a_forged_session_key_returns_the_callers_own_empty_result` is the
demonstration, and `SessionDetailIsTenantScoped` is the model-checked version. A
malformed key is a `400` with `code: "invalid_session_key"`; a key this workspace
has no session for is a `404` with `code: "session_not_found"`.

## The route, and the column that was never read

`data_points.location_geom` — a PostGIS `geometry(Point, 4326)`, its GiST index,
and the trigger that fills it from the coordinates in metadata — has existed since
migration 005, and **nothing had ever queried it**.

The route is where it earns its place:

- `ST_Simplify` is Douglas–Peucker *inside Postgres*. A three-hour ride at one fix a
  second is 10,800 rows, and it comes back as a few hundred vertices in a single
  value — the same argument the daily story makes for aggregating server-side.
- `ST_Length(::geography)` gives a **measured** track length to sit beside the
  distance the provider stated. That is a genuinely different number, and exactly
  the kind of cross-check a detail page is for.

Metadata coordinates remain the fallback for rows written before migration 005, and
the response says which was used through `route.source` — a stable code, never
prose (rule 17).

## What is bounded, and what says so

The property to hold onto: **the response's size and its number of statements do not
grow with the session.** A three-hour ride and a twenty-minute run produce the same
shape.

| Bound | Value | Reported through |
| --- | --- | --- |
| Session span | 12 hours | `window.clamped` |
| Stream points | 500, max 2,000 | `streams[].truncated` |
| Route points | 1,000, max 5,000 | `route.truncated` |
| Set rows | 4,000 | `strength.set_rows_truncated` |
| Distinct series | 8 | — |
| List scan | 20,000 rows | `scan_limit_reached` |

Every one of them reports when it bites, because a quietly shortened answer is
indistinguishable from a short workout — the posture `event_limit_reached` already
takes on the daily story.

**Decimation keeps the extremes.** A bucketed mean alone hides them, and a point
that hides its extremes is a number that looks measured: a sprint peaking at 186
inside a bucket averaging 162 has to still show 186, or the chart is a different
workout from the one that happened. `test_decimation_preserves_the_peak` pins it.

## Am I getting stronger

Per-exercise progression — best set, estimated one-rep max, weekly volume and a
direction — is computed by the Analysis Service and shown under **Strength** on the
analysis page. It reads sets from Core over a purpose-built
`QueryStrengthSets` RPC, because the grouping key is a metadata field only Core can
read. See [Correlations and simple analyses](correlations.md#strength-progression).

The workout detail below shows the sets of *one* session; that page shows one
exercise across all of them.

## Muscle groups

Streak states a category per exercise, and that category *is* the muscle group. It
is **not** stored as the canonical value.

A provider's vocabulary is a provider's to change: Streak can rename `Legs` to
`Lower Body`, localise it to the phone's language, or split it in two, and a
dashboard grouping on that string would silently show two groups where there was
one. The same applies the moment a second strength source arrives.

So the provider's word is kept verbatim in `exercise_category`, and a canonical
`MuscleGroup` (`shared_schemas/muscles.py`) is stored beside it in `muscle_group`.
The values are stable lowercase English identifiers translated in the dashboard
through `muscle.<value>` keys (rule 17).

An unrecognised category becomes `other` **and** is named in the field report, so a
renamed vocabulary shows up in the [Data Quality Center](data-quality.md) instead of
collapsing into `other` forever. Two coarse labels map to `other` on purpose:
`Arms` covers two muscles that move in opposite directions, and `Upper Body` is half
a person.

## Adding a new workout importer

Garmin, Strava and Hevy are all named in the roadmap, and none of them should have
to rediscover any of this.

1. Call `session_metadata()` — it is the only way to mint a session block, and
   `packages/shared-schemas/tests/test_importer_sessions.py` fails an importer whose
   contract claims a `workout_*` or `strength_*` metric and whose source never calls
   it. A convention nothing checks is a convention that lasts one importer.
2. Map any exercise category through `resolve_muscle_group()`, and report what it
   does not recognise.
3. Nothing in `core/workouts.py` changes. The read path keys on
   `metadata->>'session_id'` and the registry's categories, never on a `source_type`.

See [the importer standard](../importer-standard.md).

## Interpretation and limitations

- **One run recorded by two devices is two sessions.** An Apple Watch and a WHOOP
  strap covering the same 45 minutes each state their own workout with their own
  identifier, and nothing on this side can prove they are the same event — so the
  list shows both. Neither is wrong and nothing is double-counted in a lane or a
  chart, but the reader sees the run twice. Each one's page shows the other's
  figures under **Recorded at the same time**, so no data is hidden by the split.
  Merging them would be cross-source session matching, which is the roadmap's
  "Smart duplicate and cross-source conflict resolution", not this feature.
- **A session that straddles the change appears twice.** Marked, never merged, and
  never double-counted.
- **`identity: "timestamp_title"` is approximate by construction.** Those rows carry
  no session of their own, so two sessions stamped alike are one group and one
  session stamped a second apart is two. Nothing at read time can recover the
  difference.
- **A derived measure says so.** `derived_by` and `derived_from` travel to the
  screen, so WHOOP's session duration — which is `end − start`, not a figure WHOOP
  sends — is visibly ours.
- **WHOOP has no heart-rate stream.** Its API v2 exposes zone durations and session
  aggregates, and nothing per second. The per-second trace comes from Apple Health.
- **`surroundings` is an aggregate, not a record.** One number per metric per
  connector for the window — which is what keeps "every point from every connector"
  from meaning "every point on the wire".
- **A metric becomes a chart only where it has a shape.** A metric needs at least
  three readings inside the window to be drawn as a series; below that it is a
  figure in `surroundings`. Weather is `continuous` in the registry and arrives
  hourly, so a 45-minute window holds one reading of it — and a one-point line is
  not a chart. Deciding this on the registry's cadence alone put it in neither
  place: classified as a stream, excluded from the figures for being one, and then
  dropped by the client for having too few points to draw.
- **The clamp is 12 hours.** A session stating a longer span is shown capped, with
  `window.clamped` set; an ultra-endurance event would need that constant raised.
- **`pad_seconds` widens the window but not the session.** A fix two minutes before
  the stated start appears on the route; the stated start does not move.
