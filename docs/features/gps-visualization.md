# GPS-Visualisierung

Die GPS-Karte zeigt Dawarich-Standortpunkte. Standardmäßig wird eine robuste SVG-Vector-Route genutzt, damit das Dashboard auch ohne extern ladbare Kartentiles funktioniert.

## Modi

- **Vector Route**: Offline-fähige Projektion der GPS-Punkte in eine SVG-Bounding-Box.
- **OpenStreetMap**: Optionale Leaflet-Karte, wenn externe Tiles erreichbar sind.

## Empfehlung

Wenn die Tile-Karte grau bleibt oder blockiert wird, bei **Vector Route** bleiben. Die Datenpunkte selbst kommen weiterhin tenant-scoped aus Core über `/api/v1/data/metrics`.
