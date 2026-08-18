# GPS visualization

The map renders a GPS track as a self-contained SVG vector route by default, so the
dashboard still works when no map tiles can be loaded from outside. Raster tiles are
strictly opt-in: Leaflet is imported on demand and no tile host is contacted until
the reader asks for one.

## Two callers

- **A workout's route** — [Workout detail](workout-detail.md) passes the fixes the
  endpoint already resolved and simplified for that session. The map draws them and
  fetches nothing: re-deriving the track from a calendar filter would show a
  different route from the one the session actually covers.
- **A period of Dawarich history** — the map fetches the track over a chosen day
  range itself, from `GET /api/v1/data/day/track`. On the daily story it receives the
  exact local calendar day and the reader's UTC offset, so today and yesterday never
  bleed into adjacent UTC days.

The difference is one prop. With `points`, the component is controlled and its date
filter is hidden; without, it fetches. The daily story lazy-loads the map only for a
day whose report contains a location lane, and passes `day` plus `offsetMinutes` to
bound the request to that one tenant-scoped window.

## Modes

- **Vector route**: an offline-capable projection of the fixes into an SVG bounding
  box. The default, always available.
- **OpenStreetMap**: an optional Leaflet layer, for when external tiles are
  reachable. Configurable between two providers, and it falls back to the vector
  view with a visible message when tiles fail.

## The whole span, never its beginning

A day of movement is more fixes than a map should draw, so it is reduced twice — and
both reductions are of the *whole* span.

1. **In the database.** `GET /api/v1/data/day/track` counts every fix in the window,
   derives a stride from that true total, and returns every *n*-th row via
   `row_number()`. Reading all of them and discarding most in Python would transfer
   twelve hours of one-second fixes to produce four thousand points.
2. **In the browser.** `simplifyTrack` reduces what is left to at most 2,000 vertices
   by perpendicular distance, so straight stretches collapse and corners survive.
   Endpoints are always kept, so the route still starts and ends where it did.

The response separates the two numbers that matter: `fix_count` is how many fixes the
span actually holds and `sample_count` is how many came back, with `truncated` set
when they differ. The interface reports `fix_count`, because reporting the drawn
count as the total is how a decimated track passes for a complete one.

!!! warning "Why this is not a `limit` on `/api/v1/data/metrics`"
    It was, at `limit=1000`. That endpoint sorts ascending and reports no truncation,
    so a day with more fixes than the limit returned the **earliest** thousand: the
    map drew a track that stopped mid-morning, and labelled the count of what it drew
    as the day's own. Nothing on the page distinguished that from a day that genuinely
    ended at 11:00 — a wrong answer that looks exactly like a right one, which is the
    failure mode rule 19 is about.

A workout's route takes the same path — it is the same function over the session's
window, and `ST_Length` beside it gives a measured track length to sit against the
distance the provider stated.

## Recommendation

If the tile map stays grey or is blocked, stay on **Vector route**. The points
themselves come tenant-scoped from Core either way.
