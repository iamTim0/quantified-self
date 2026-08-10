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
it. The dialog shows a transfer progress bar while the archive is travelling to the importer.
The response arrives before the archive has been read: a whole Apple Health history is minutes of
work, which is longer than a browser should hold a connection open. What you watch afterwards is
the progress panel in the same dialog — it counts the data points as they are actually stored, and
the connector's history keeps the outcome.

You do not have to sit and watch it. **Minimise** closes the dialog and leaves the upload running,
and a card in the bottom-right corner keeps showing which connector, which file and how far it has
got, on whichever screen you happen to be. Cancelling there stops the transfer and deletes the
parts that had already arrived. Closing the *tab* does end an upload — the browser asks first.

### Why the file arrives in parts

A large archive is sent in parts rather than as one request, and this is not a detail of taste: the
hops between a browser and an importer each cap how large a request body may be, and the smallest
cap wins. Cloudflare refuses a body over **100 MB** on every plan below Enterprise, and refuses it
at the edge — a 200 MB Apple Health export was rejected after roughly 3 MB had been sent, which the
progress bar showed as "2 %". Coolify's ingress and a stock nginx have limits of their own. None of
them can be raised from this repository.

So the dashboard asks the importer for a session, sends parts of a size the importer names (8 MB),
and then says the archive is complete; the importer reassembles them into one file and reads it
exactly as if it had arrived in one request. The importer owns the byte offsets, which is what makes
the retries safe:

| Situation | What happens |
| --- | --- |
| A part's response is lost and the part is sent again | Refused with the offset the importer wants, so it is never appended twice |
| The connection drops mid-part | That part is retried; the spool is truncated back to the last complete offset |
| The upload fails after 80 % | **Continue** resumes from 80 %, for up to an hour |
| The upload is abandoned | The parts are deleted — after an hour of silence, at the next sweep, or immediately when the importer restarts |

A single-request upload (`POST /api/v1/import/<provider>/upload` with the file as the body) still
works and is the simpler choice for a script or a small export. It is subject to whatever body
limit sits in front of the deployment.

### The upload session, endpoint by endpoint

Every step goes through the Gateway, needs the same session and CSRF proof as any other write, and
reaches the importer for that provider (`apple-health`, `whoop`).

| Step | Request | Answers |
| --- | --- | --- |
| Open | `POST /api/v1/import/<provider>/upload/begin?source_id=<id>&total_bytes=<n>` | `upload_id`, `chunk_bytes` (the part size to use), `max_bytes`, `received` |
| Send a part | `POST /api/v1/import/<provider>/upload/chunk?upload_id=<id>&offset=<n>` with the bytes as the body | `received` — how much the importer now holds |
| Finish | `POST /api/v1/import/<provider>/upload/complete?upload_id=<id>` | `202` with the `sync_run_id` of the import it started |
| Give up | `POST /api/v1/import/<provider>/upload/abort?upload_id=<id>` | `200`, and the parts are deleted |

`begin` refuses a `total_bytes` larger than the importer's limit with `413` before anything is sent.
A `chunk` at the wrong offset is `409` and carries `expected_offset`; so is `complete` on a session
that is still short of the size it announced. An `upload_id` belonging to another workspace is
`404`, not `403` — whether an id exists is not another tenant's business.

The run is opened by `complete`, not by `begin`: a run held open for the minutes a browser spends
uploading would show an import that is importing nothing, and Core's scheduler treats a connector
with an open run as busy, so an abandoned upload would have suppressed that connector's scheduled
imports until the run went stale.

The response contains a `sync_run_id` and the connector detail page at
`/connectors/<connector-id>` shows the same run in its history. The importer reports the expected
point count after parsing the file, then Core counts accepted and duplicate events as they arrive.
The progress total is therefore unknown briefly for a large archive and becomes exact once parsing
has finished. A failed upload is still recorded against the connector, including failures before
the archive could be parsed.

The history is connector-specific and tenant-protected. It includes the trigger (`upload`), status,
request id, start and finish times, duration, expected points, accepted points, duplicates and the
last message. An importer crash is eventually marked as an error by Core after the six-hour stale
run timeout; it does not leave the connector permanently busy.

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
`sleeps.csv` and `workouts.csv` — **in the language of your WHOOP account**. A German account
receives `physiologische_zyklen.csv`, `Schlaf.csv` and `Trainings.csv`, with German column headers
to match, and both vocabularies are read. You do not have to change your account language to
import your own data.

Imported: day strain, energy, average and maximum heart rate, recovery score, resting heart rate,
HRV, blood oxygen, skin temperature, sleep performance and efficiency, respiratory rate, the
night's duration, time in bed and all four sleep stages, and per workout its strain, energy,
duration, average and maximum heart rate and distance.

Each row also carries the *cycle* it belongs to, next to its own start time, and a record is
timestamped from its own — a workout from the workout's start, a night from sleep onset. Keyed on
the shared cycle instead, every session in a day would produce one `idempotency_key` and only the
first would be stored.

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

**"That file is not a ZIP archive."** Either it genuinely is not one, or — more often for a file
this size — it is an Apple Health export that never finished arriving on the machine it was
uploaded from. A ZIP keeps its index at the *end*, so an archive whose last bytes are missing is
unreadable as a whole even though most of its content is intact and its size looks plausible. A
cloud-storage folder that stopped syncing mid-file produces exactly this. Copy the export off the
phone again, and check that the file on disk has the size the phone reported before uploading it.

**"No export.xml was found in the archive."** The file uploaded was not an Apple Health export —
check that it is the ZIP the Health app produced, not a folder re-zipped afterwards. The member is
found whatever its case, so iOS naming it `Export.xml` is not the cause.

**"No recognisable Whoop CSV was found."** The WHOOP export sometimes changes its file names; the
importer looks for `physiological_cycles`, `sleeps` and `workouts`. Send the archive as it
arrived, without renaming.

**The processing progress panel shows nothing.** An upload only starts a run once the file has
arrived in full. The transfer bar covers the upload itself; on a slow connection the processing
panel therefore appears only after a large archive has finished uploading.

**The upload stops after a few per cent.** That is a body limit in front of the platform, not the
importer: Cloudflare's `413` arrives at the edge after a couple of megabytes, so the percentage it
dies at says more about the file's size than about the cause. The dashboard sends parts of 8 MB
precisely to stay under such limits — if an upload started from the dashboard still stops this way,
check the reverse proxy for a limit *below* 8 MB and the importer's log for the part it refused.
A `curl` of the whole file in one request is subject to the full limit and will fail this way.

**A large upload failed near the end.** Press **Continue** on the card: the importer still holds
what arrived, for an hour after the last part, and the transfer resumes from there rather than from
the beginning.

**Numbers look duplicated.** They are not: check the connector. Two connectors of the same type
are two series on purpose, so an export uploaded into a second Apple Health connector sits beside
the first rather than merging with it.
