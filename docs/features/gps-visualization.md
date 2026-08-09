# GPS visualization

The GPS map shows Dawarich location points. It defaults to a self-contained SVG vector
route so that the dashboard still works when no map tiles can be loaded from outside.

## Modes

- **Vector route**: an offline-capable projection of the GPS points into an SVG bounding box.
- **OpenStreetMap**: an optional Leaflet map, for when external tiles are reachable.

## Recommendation

If the tile map stays grey or is blocked, stay on **Vector route**. The data points
themselves still come tenant-scoped from Core via `/api/v1/data/metrics`.
