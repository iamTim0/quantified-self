# Dashboard appearance and responsive controls

The dashboard offers light, dark and system colour themes. The preference is
stored in the browser under `qs-theme`; `system` follows the operating system's
colour-scheme setting and updates when that setting changes. A small bootstrap
in the document head applies the saved palette before the application hydrates,
so a dark preference does not flash a light shell on reload. The preference is
presentation-only and never crosses the Gateway or Core service boundary.

The shell keeps its navigation and header controls usable at phone widths. The
workout tab has its own `/workouts` route, while the Data Explorer changes its
period segmented control into a native select on narrow screens and stacks custom
start/end dates instead of allowing them to widen the page.

The daily story places the current day first and yesterday below it. When a day
has a location lane, the map is loaded on demand and asks Core for only that
tenant's `location_point` values in the reader's local day window. The browser
sends the calendar day and its UTC offset so the window remains correct around
UTC boundaries. Raster map tiles remain opt-in; the default vector route does not
send location data to a tile provider.

Theme, navigation and responsive controls do not change the meaning or units of
imported metrics. Data remains retrievable through the same tenant-scoped
Gateway APIs documented for the [daily story](daily-story.md), [GPS
visualization](gps-visualization.md), and [workout detail](workout-detail.md).
