# Quantified Self Platform: Importer Architecture Standard

This document defines the architectural standard and developer blueprint for building data importers in the Quantified Self Platform. All new and existing importers must adhere to these guidelines.

## 1. Core Architectural Mandate

**Request-Driven Execution:**
Importers MUST NOT use background interval timers (e.g., cron jobs, `apscheduler`) for polling data. All sync executions must be purely request/task-driven.

Tasks are triggered via NATS JetStream using the subject pattern:
`qs.task.sync.<source_type>`

Importers must listen to these subjects and execute sync tasks only when a message is explicitly received.

## 2. Dynamic Credentials & Configuration

**Stateless Importers:**
Importers MUST NEVER store API tokens, OAuth credentials, or configuration in `.env` files or local databases. Importers have **zero database access**.

Credentials and custom `config` dictionaries must be fetched dynamically over internal HTTP at the start of a sync task:
`GET /api/v1/internal/data/sources/<source_id>/token`
This request must include the `X-Tenant-ID` header.

The path segment is the **connector id** carried by the sync task, not the source type. A tenant may
hold several connectors of one type — three calendars, two weather locations — so the type alone no
longer says whose credential is wanted. A bare type still resolves, for older payloads, but it
returns whichever instance was created first.

For the same reason an importer must never invent a `source_id`. Three of them used to fall back to
`uuid5(NAMESPACE_DNS, f"{tenant_id}:{source_type}")` when Core returned none; that collapsed every
instance of a type onto one id, and since the id is the second component of every idempotency key,
two connectors would have written into a single indistinguishable series. An importer with no
`source_id` reports an error and stops.

**Security Constraints:**
- Zero plaintext secrets in `.env` files.
- Zero plaintext secrets published in NATS messages.
- All credentials are encrypted at rest by the Core Data Service.

## 3. In-Flight Concurrency Control

To prevent redundant and overlapping syncs for the same tenant, importers must implement an in-flight concurrency lock.

Importers must maintain an `active_syncs: set[str]` lock containing the `tenant_id` of actively syncing tenants. If a sync task arrives for a `tenant_id` currently in the `active_syncs` set, the task MUST be skipped to avoid duplicate work and API rate limits.

This lock is a second line of defence, not the primary guard. Core's scheduler already skips a
connector whose import is still running, so it does not queue the duplicate job at all — see
[Architecture](architecture.md#scheduled-imports). The lock still matters because it is
process-local and therefore also covers a task replayed by JetStream.

## 4. Standardization Contract

### Run History

Every import attempt must be attributable to the configured connector instance. Core owns the
tenant-scoped `SyncRun` record; importers never write a database. Scheduled and manual task
imports receive a `sync_run_id` in the NATS task, pass it through every `qs.ingest.<source_type>`
event, and report the importer outcome through the internal Core status endpoint. Core exposes the
phases `queued`, `running`, `loading`, `success`, `error` and `skipped`; an importer reporting that
it has published its events moves the run to `loading`, not directly to `success`. Push and file
importers open a run before parsing, report a known `points_expected` total after parsing,
and close the run even when the request is malformed, the broker is unavailable or publishing
fails. Core records the request id, trigger, timestamps, duration, counts and message. Runs that
stop reporting for six hours are marked `error` by Core so a crashed importer cannot block its
connector forever.

The dashboard exposes this history at `/connectors/<connector-id>` and as a tenant-wide **All import
runs** list on the Connectors page. The API is tenant-scoped and
uses the connector id rather than only the provider type, so two instances of one importer never
share a progress display or audit trail. Rejected API-key requests are attributed only when the
stored key hash identifies a connector; raw keys are never sent to Core or stored in a run.

### File Layout
All importers must follow a standard file layout:
- `main.py`: Application entry point, NATS JetStream subscription, task lifecycle, and lock management.
- `client.py`: API client for interacting with the external data source (fetching data).
- `transformer.py`: Data transformation logic mapping source payload data to internal metric formats.
- `config.py`: Environment variable definitions (excluding secrets).

### Metric Event Subject
Once data is transformed into internal metric formats, events MUST be published to NATS using the subject pattern:
`qs.ingest.<source_type>`

### Metric Names and Units
An importer does not choose its own metric names. Every `metric_type` MUST be a canonical
name from the shared registry in
`packages/shared-schemas/src/shared_schemas/metrics.py`, resolved through
`canonical_metric_type()`, and every value MUST be converted into the unit that registry
defines for it (`convert()`). Core rejects anything else on the way in.

Two consequences worth stating outright:

- Two sources reporting the same quantity write the **same** name. The name says what was
  measured — never who measured it, and never in which unit.
- Providers whose metric set depends on the user's own setup emit under a registered
  *dynamic namespace* (`home_assistant_`, `apple_health_`) rather than inventing bare
  names.

See [Metrics](metrics.md) for the rules, the full catalog and how to add an entry.

### Sessions

**An importer that emits any `workout_*` or `strength_*` metric MUST write a session block onto
every point of that session.** Without one, a workout is not an entity anywhere in the platform:
it arrives as a fan of unrelated rows — a duration, a distance, a dozen heart-rate figures, a GPS
trace, a set of squats — and the only thing joining them is a shared timestamp and a metadata
string. That join fails in both directions: two sessions a provider stamped alike merge into one,
and one session whose points differ by a second splits into two.

The block comes from **one helper and only that helper**:

```python
from shared_schemas.sessions import session_metadata

session = session_metadata(
    source_type="garmin",
    source_id=source_id,           # inside the digest: two watches are two sessions
    provider_session_id=activity.get("activityId"),
    start=activity["startTimeGMT"],
    end=activity.get("endTimeGMT"),  # omitted entirely when the provider states none
    label=activity.get("activityName"),
    derived_from=("startTimeGMT", "activityName"),
)
```

Merge `session` into the metadata of **every** point the session produces — its summary figures,
each set, each GPS fix, each sample. A point without it is a point the workout page cannot find.

Four things about that call are contract rather than style:

- **Never hand-roll the digest.** It is one function for the reason `events.py` documents about
  the idempotency hash: that one was copied nine times, all nine happened to agree, and nothing
  checked that they did. A session id derived two ways is a workout that appears twice.
- **`provider_session_id` when the provider states one**, and the block then declares
  `session_origin: "provider"`. The digest of a stated id depends only on the connector and the
  id, which is also what makes such a session recoverable later by
  [`core.session_backfill`](operations.md).
- **`derived_from` is mandatory when there is no stated id** — `session_metadata` raises without
  it. A derived value that does not say it was derived is a value nobody can audit (rule 19).
- **Never invent an end.** `session_end` is omitted when the provider gives none; the read path
  widens a window it can measure and clamps one it cannot, and it can only tell those apart if a
  missing end stays missing.

Adding a session-emitting importer also means adding it to the parametrised list in
`packages/shared-schemas/tests/test_importer_sessions.py`, which asserts that every importer
declaring a `workout_*` or `strength_*` metric calls `session_metadata` and does not compute a
digest of its own. That test fails for a new importer by design — a convention nothing checks is
a convention that lasts one importer.

Nothing in the read path is per-source: the workout list and the detail endpoint key on
`metadata->>'session_id'` and on the registry's categories, never on a `source_type`. A new
workout source needs the transformer call and one row in that test, and no change to
`core/workouts.py` at all.

See [Workout detail](features/workout-detail.md) for what the session block buys the reader.

## Contract-first importer definition

Every importer has a machine-readable `importer.contract.json` in its service root.
It is the source of truth for the importer's input formats, upstream schema references,
NATS subjects, service-boundary guarantees, capabilities and the registry metrics it may
emit. The contract is validated by `python tools/importer_contracts.py` and the human
catalog at [Importer contract catalog](importer-contracts.md) is generated with
`task importers:contracts`.

OpenAPI is an upstream reference when a provider exposes an API schema. It is not a
requirement for every importer: iCalendar is governed by RFC 5545, Apple Health's
official export is an XML archive, and WHOOP's account export is a ZIP of CSV files.
Those formats are represented explicitly in the same contract instead of being forced
into an API-only schema. A generated provider schema may be recorded with
`generated: true` and `generated_from` when an upstream schema is available locally;
the importer contract remains the repository-owned compatibility boundary.

When an input format changes, update the contract and its transformer tests together.
CI then catches a missing contract, an incorrect subject, a non-canonical metric, a
missing required module, a broken source reference or stale generated documentation.

### Idempotency
All ingestion events require a deterministic `idempotency_key` to ensure duplicate events are safely ignored downstream. The key must be generated as follows:
`idempotency_key = SHA256(tenant_id + source_id + metric_type + timestamp)`

Resolve the canonical metric name **before** deriving the key. Because the name is part of
the hash, canonicalising afterwards stores a point under a name its key does not describe,
and the same reading is imported again on the next run instead of deduplicating.

### Testing Requirements
- Unit tests must mock external API calls in `client.py`.
- Ensure deterministic output in `transformer.py` tests.
- Verify concurrency lock behavior (`active_syncs`) in `main.py`.
- Mock NATS JetStream publishing.
