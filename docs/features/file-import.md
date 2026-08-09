# Uploading an export file

Two of the providers here will hand you your own history as a file: Apple Health exports
`export.zip` from the Health app, and WHOOP emails a ZIP of CSVs on request. Neither needs a
developer account, an OAuth application or an API key — which, for somebody who wants their data
once rather than continuously, is the difference between having it and not.

## Connect, or import a file

When you add a WHOOP or Apple Health connector the dialog offers two kinds:

| Kind | What it does |
| --- | --- |
| **Connect now** | The ordinary connector. It holds a credential and is polled on a schedule, or receives pushes from your phone. |
| **Import a file** | No credential and no schedule. Data arrives when you upload an export. |

Both create a connector. They have to: the connector's id is the second component of every
[idempotency key](../architecture.md#idempotency) derived from the file, and that is what makes
uploading the same export twice a no-op instead of a second copy of a year of your life.

The choice is not permanent. A file connector can be given credentials later, and an existing
connected one accepts uploads too — which is the useful case for a backfill, because the archive
reaches back further than any API window. Upload into the **same** connector and the readings it
already has stay one reading each; upload into a second connector and you deliberately get two
series.

## Uploading

Open **Upload** on the connector (it is the same dialog as **Import**), choose the file, and send
it. The response arrives before the archive has been read: a whole Apple Health history is
minutes of work, which is longer than a browser should hold a connection open. What you watch
instead is the progress panel in the same dialog — it counts the data points as they are actually
stored, and the connector's history keeps the outcome.

The file itself is written to the importer's disk while it is being read and deleted afterwards,
whether the import succeeded or failed. Nothing is kept.

## What each export contains

### Apple Health — `export.zip`

Health app → your profile → **Export All Health Data**. The archive holds `export.xml` with every
recorded measurement, and `workout-routes/*.gpx` with the GPS track of every outdoor workout.

Imported: the metrics in the [registry](../metrics.md) — steps, distance, energy, heart rate,
blood pressure, sleep and its stages, body weight and the rest — plus workouts (duration,
distance, energy, average and maximum heart rate) and every GPS point of their routes as
`location_point`.

**Not** imported, deliberately: anything the registry does not catalogue, and with it the special
categories an archive contains whether or not you ever chose to share them — symptoms, cycle
tracking, medications, State of Mind, ECG traces, clinical records. The push path is opt-in per
category in the export app, so what arrives there is what you picked; an archive carries no such
choice, so the conservative rule applies to it. Everything skipped is listed by name under
**Not yet supported** in the [Data Quality Center](data-quality.md) — never with a value, only
with a field name, a type and a count.

### WHOOP — the emailed export

WHOOP app → Account → request your data export. The ZIP holds `physiological_cycles.csv`,
`sleeps.csv` and `workouts.csv`.

Imported: day strain, energy, average heart rate, recovery score, resting heart rate, HRV, blood
oxygen, skin temperature, sleep performance and efficiency, respiratory rate, and per workout its
strain, energy, average heart rate and distance.

The export states energy in kilocalories where the API states it in kilojoules. Both arrive under
the same metric name in the registry's unit, so an export and a polled sync produce one series
rather than two — which is the whole reason the export has its own unit table.

## Limits

| Limit | Apple Health | WHOOP |
| --- | --- | --- |
| Upload size | 2 GB | 200 MB |
| Extracted bytes | 16 GB | 2 GB |
| Records / rows | 10 000 000 | 2 000 000 |

An archive is untrusted input, so what comes *out* of it is counted while it is read rather than
believed from its header — the ratio between the two figures is what a zip bomb exploits. The XML
is parsed with `defusedxml`, and nothing in the archive is executed or written anywhere except
the temporary file the upload itself created.

## Troubleshooting

**"No export.xml was found in the archive."** The file uploaded was not an Apple Health export —
check that it is the ZIP the Health app produced, not a folder re-zipped afterwards.

**"No recognisable Whoop CSV was found."** The WHOOP export sometimes changes its file names; the
importer looks for `physiological_cycles`, `sleeps` and `workouts`. Send the archive as it
arrived, without renaming.

**The progress panel shows nothing.** An upload only starts a run once the file has arrived in
full. On a slow connection a large archive takes a while before anything appears.

**Numbers look duplicated.** They are not: check the connector. Two connectors of the same type
are two series on purpose, so an export uploaded into a second Apple Health connector sits beside
the first rather than merging with it.
