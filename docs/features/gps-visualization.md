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
- **A period of Dawarich history** — the map fetches `location_point` over a chosen
  day range itself.

The difference is one prop. With `points`, the component is controlled and its date
filter is hidden; without, it fetches.

## Modes

- **Vector route**: an offline-capable projection of the fixes into an SVG bounding
  box. The default, always available.
- **OpenStreetMap**: an optional Leaflet layer, for when external tiles are
  reachable. Configurable between two providers, and it falls back to the vector
  view with a visible message when tiles fail.

Large tracks are simplified before rendering (perpendicular distance, endpoints
always kept) rather than drawing every point. A workout's route arrives already
simplified — by `ST_Simplify` in Postgres, which is where the platform's one PostGIS
read lives.

## Recommendation

If the tile map stays grey or is blocked, stay on **Vector route**. The points
themselves come tenant-scoped from Core either way.
