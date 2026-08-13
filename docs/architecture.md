# Architecture and data flow

## Overview

The platform is a set of independently deployable services with a strict division of
responsibility. The most important rule: **only `services/core/` owns the database.** No other
service imports a database driver.

```mermaid
flowchart TB
    browser["Browser"]
    traefik["Traefik&nbsp;&mdash; routes by role, one origin"]
    ui["Dashboard&nbsp;:3000&nbsp;&mdash; Next.js"]
    gateway["API Gateway&nbsp;:8000&nbsp;&mdash; verifies the JWT,<br/>injects X-Tenant-ID and X-Request-ID"]
    analysis["Analysis&nbsp;:8010&nbsp;&mdash; correlations, trends, anomalies,<br/>stateless MCP tools and AI chat"]
    bus{{"NATS JetStream"}}
    importers["Importers&nbsp;&mdash; 8 stateless services, one per provider"]
    providers[/"Provider APIs and devices"/]

    subgraph owner["The only service that may touch the database"]
        core["Core&nbsp;:8001, gRPC&nbsp;:50051&nbsp;&mdash; REST, ingest consumer,<br/>scheduler, import planning"]
        db[("PostgreSQL&nbsp;&mdash; TimescaleDB, pgvector, PostGIS")]
    end

    browser --> traefik
    traefik --> ui
    traefik --> gateway
    gateway --> core
    gateway --> analysis
    analysis -->|"gRPC, read only"| core
    core --- db

    core -->|"1. qs.task.sync.SOURCE&nbsp;&mdash; window, mode, request_id"| bus
    bus --> importers
    importers -->|"2. asks Core for the encrypted credential"| core
    importers -->|"3. fetches exactly that window"| providers
    importers -->|"4. qs.ingest.SOURCE&nbsp;&mdash; canonical name, converted unit,<br/>deterministic idempotency_key"| bus
    bus -->|"5. one consumer, queue group"| core
    core -->|"6. INSERT ... ON CONFLICT DO NOTHING"| db
```

## Services

| Service | Responsibility | Database access |
| --- | --- | --- |
| `services/api-gateway/` | Entry point, JWT verification, header injection, reverse proxy | no |
| `services/core/` | REST API, gRPC read interface, ingest consumer, import planning, scheduler | **yes, exclusively** |
| `services/importers/*` | Fetching or receiving external data | no |
| `services/analysis/` | Correlations, trends, anomalies, routines, read-only MCP tools, Codex chat adapter | no, reads from Core over gRPC |
| `apps/dashboard/` | Next.js interface | no |

## The data flow of an import

1. The user triggers an import, or a connector is configured.
2. **Core computes the window** from the poll interval and the import history (see
   [Smart and force import](features/smart-import.md)) and creates a `SyncRun`.
3. Core publishes `qs.task.sync.<source>` with `tenant_id`, `request_id`, `sync_run_id`, `mode`,
   `window_start` and `window_end`.
4. The importer fetches its credentials over
   `GET /api/v1/internal/data/sources/<source>/token` — it stores none itself.
5. The importer calls the provider API for exactly that window.
6. For every data point a deterministic `idempotency_key` is derived and an event is published on
   `qs.ingest.<source>`.
7. Core's consumer writes with `INSERT … ON CONFLICT DO NOTHING` and counts accepted and duplicate
   points onto the `SyncRun`.
8. The importer reports the outcome; only a successful run moves the resume point.

For push sources (Apple Health, Streak) steps 1–5 do not apply: the external service sends
straight to the importer, which resolves the tenant from the API key.

For an **uploaded export** (Apple Health's `export.zip`, WHOOP's emailed ZIP of CSVs) steps 1–5
do not apply either. The browser sends the file through the Gateway to the importer that can read
it; the importer opens a `SyncRun`, answers `202 Accepted`, and only then reads the archive and
publishes on `qs.ingest.<source>` — steps 6 to 8 as usual. The response comes first because
reading a whole history takes minutes, and the run is what the dashboard watches meanwhile. The
importer cannot validate a session itself: Core keeps the JWT signing key away from the importers,
so the importer asks Core whom the forwarded token belongs to. See
[Uploading an export file](features/file-import.md).

## Import history and progress

Every import belongs to one connector instance and has a tenant-scoped `SyncRun`. Core creates
runs for scheduled and manual imports; push and upload importers open their own run before they
start transforming data. This keeps rejected requests, malformed uploads and partial imports in
the same audit trail as successful work.

The tenant-protected endpoint
`GET /api/v1/data/sources/<connector-id>/sync-runs` returns the newest runs for that connector.
Each entry includes its status, trigger, request id, import window, accepted and duplicate point
counts, the importer publish count, the Core processing count, optional expected point count, message
and duration. The connector id is used deliberately:
two connectors of the same type must never share a history or progress display.

The Connectors page also reads `GET /api/v1/data/sync-runs` for a tenant-wide overview. It includes
the connector display name and supports pagination plus optional `status` and `source_type` filters.
The lifecycle is explicit: `queued` means Core has not handed the task to an importer yet, `running`
is the importer/discovery phase, `loading` means the importer has published its events and Core is
still consuming them, `success` means Core has processed the complete published count, and `error`
or `skipped` are terminal outcomes. `points_received` is the number published by the importer;
`points_processed` is the number Core has stored, deduplicated or quarantined.

An importer can report a known total while it is still running through Core's internal
`.../sync-runs/<sync-run-id>/progress` endpoint. `points_expected` may remain unknown for a
streaming API import and becomes known after a file importer has parsed its archive. Core remains
the only owner of the run record and the dashboard reads it through the tenant-scoped API. The
connector detail view at `/connectors/<connector-id>` shows the latest status, progress counts,
durations and history.

Core also expires a `queued`, `running` or `loading` run after six hours without completion. It records an
error and allows the next scheduled attempt to proceed, so a crashed importer cannot block a
connector forever. Rejected push API keys may be attributed to their connector using only the
stored key hash; the plaintext key is never sent to Core or written to the run history.

## Idempotency

```text
idempotency_key = SHA256(tenant_id + ":" + source_id + ":" + metric_type + ":" + timestamp)
```

The uniqueness constraint in the database is `UNIQUE (tenant_id, idempotency_key, timestamp)`. The
timestamp is part of it because TimescaleDB requires the partitioning column in every unique index.

!!! warning "What follows from that constraint"
    The same `idempotency_key` with a *different* timestamp creates a second row. Transformers must
    therefore normalize timestamps and must never fall back to `now()` — that exact mistake used to
    produce fresh duplicates on every sync.

## Tenant isolation

- Every query filters by `tenant_id`.
- The tenant is derived from the verified bearer token and from nothing else.
- An `X-Tenant-ID` header may agree with the claim but never override it; a contradiction is a `403`.
- Internal endpoints (`/api/v1/internal/*`) are not reachable from outside through the Gateway.

Details: [Authentication and sessions](features/authentication.md).

## Correlation

Every request carries an `X-Request-ID`. It is propagated across the Gateway, Core, the NATS event
and the importer, and appears in every log as `[req_id=…]`.

## Data model (excerpt)

| Table | Purpose |
| --- | --- |
| `tenants`, `users` | Workspace and identities kept separate. `users.sessions_valid_from` is the cut-off from which older access tokens are rejected |
| `data_sources` | One row per configured connector *instance*. A tenant may hold several of a type — three calendars, two weather locations — told apart by `display_name` and unique on `(tenant_id, source_type, display_name)` |
| `data_points` | The time series, a TimescaleDB hypertable |
| `sync_runs` | Import and audit log, the basis for adaptive windows |
| `api_keys` | Tenant-bound inbound keys, stored only as a hash |
| `refresh_tokens`, `revoked_access_tokens` | Sessions and revocation |
| `tenant_shares` | Cross-workspace grants. Nothing reads or writes it: sharing was withdrawn because the grant was only ever recorded, never honoured on a read. The table is kept so the account wipe can still clear rows an earlier version left behind |
| `explorer_views` | Saved queries |

Migrations run through Alembic in `services/core/alembic/` and nowhere else, and must contain a
working `downgrade()`. CI checks that by running a rollback and a second upgrade after the first
upgrade.

## Analyses: their own service, reading only over gRPC

The analyses used to run inside Core and read SQL directly in the request handler.
`services/analysis/` was a placeholder and Core's gRPC server was a stub — so there was no
transport a separate service could have read over at all.

Today:

- Core runs `CoreDataService` on port `50051` with `QueryDataPoints`, `GetDataPoint`,
  `ListMetricTypes`, `ListDataSources` and `ValidateUserSession`.
- Every call needs an internal service credential; every query filters by `tenant_id`, which is
  validated as a UUID first.
- `DataSourceSummary` carries only `id`, `source_type` and `display_name`. There is deliberately no
  field in which a connector credential could cross the service boundary, and a test pins the field
  set exactly so adding one is a decision somebody has to make on purpose.
- The Analysis service holds **no** database connection. A test reads the AST of every module and
  fails as soon as a database driver is imported there.

That last check used to exist for Analysis alone, which made rule 1 a property of one service out of
ten. `tools/tests/test_service_boundaries.py` now walks every service except Core and fails on an
imported driver, on a *declared* dependency on one, and on a migration directory outside Core — so a
new importer is covered the day it is added, rather than the day somebody writes it a test.

The interface calls `/api/v1/analysis/insights`; the Gateway proxies it through.
Analysis also owns the internal `POST /mcp` endpoint. It accepts only the sessionless
MCP `2026-07-28` revision, authenticates every request independently, and derives the
tenant from the user token rather than from tool arguments. Its four read-only tools
reuse the same gRPC client and metric registry as the HTTP analysis. Before dispatch,
Core's `ValidateUserSession` gRPC method checks the token `jti` and the user's
all-session cutoff, so revocation remains immediate without giving Analysis database
access. See
[Stateless MCP analytics](features/mcp.md).

The dashboard's `/chat` page reaches Analysis through the Gateway. Analysis drives the
official Codex app server over local JSONL stdio and exposes the MCP schemas as dynamic
tools. A callback becomes a fresh authenticated MCP `2026-07-28` request, so the model
cannot select a tenant and conversation state never becomes data-access authority.
ChatGPT device login is owned by Codex; the platform does not receive that credential.
See [AI chat](features/ai-chat.md).

## Scheduled imports

`poll_interval_hours` used to control only the window size — nothing was ever triggered. Core now
runs a scheduler, because Core is the only service that knows both of the things the decision needs:
the connector configuration and the import history.

- Every five minutes it checks which connectors are due.
- A tick takes a transaction-scoped Postgres advisory lock, so that with several Core instances only
  one of them plans.
- A connector with an import already running is skipped — keyed on the connector *instance*, so one
  of a tenant's two calendars importing does not hold up the other. After six hours a run counts as
  orphaned, since otherwise a crashed importer would block its connector forever.
- Push connectors are never scheduled. Nothing subscribes to `qs.task.sync.apple_health`, so a
  planned run there could only ever expire as stale while the connector showed as queued throughout.
- Turn it off with `SCHEDULER_ENABLED=false`.

That also means the importers' former process-local `active_syncs` lock no longer carries any weight:
Core never queues the duplicate job in the first place.

## Ending sessions: two mechanisms, because one is not enough

`revoked_access_tokens` is indexed on `jti` and ends **this one** session — which is all it can do,
because an access token is otherwise indistinguishable from any other.

`users.sessions_valid_from` ends **all of them**. The denylist cannot, because a `jti` only becomes
known when the token is presented; "every outstanding token of this account" is not an enumerable
set. The cut-off is checked against each token's `iat` and so covers all of them at once.

Both fail closed: if the database is unreachable the request is rejected rather than let through —
otherwise an outage would make every signed-out token valid again.

The cut-off is triggered by a password change, `logout all_sessions`, a detected refresh-token replay
and [back-channel logout](features/oidc.md#back-channel-logout).

## The Gateway passes the interface through without buffering it

The UI proxy used to read the complete response before forwarding the first byte. That defeats
streaming SSR and holds every response in memory in full, once. It streams now.

The `httpx.AsyncClient` deliberately outlives the handler that created it: the body is still being
read through it while Starlette is already sending. Closing it on the way out of the function — which
`async with` would do — would truncate every response to whatever had arrived by then.

!!! note "What that did not fix"
    The rework was meant to make `next dev` work behind the Gateway. It does not. Measured
    afterwards: the proxied document is byte-for-byte identical to the one fetched directly, so is
    every chunk, and the HMR socket connects — and the page still does not hydrate, with no error
    anywhere. So buffering was not the cause. The browser tests continue to run against a production
    build, which is what gets deployed anyway.

## Known limitations

- Analyses may be skipped when the data is very thin. That is deliberate: a weakly supported
  relationship is more misleading than none.
- `next dev` does not work behind the Gateway (see above). Straight on port 3000 it does: the dev
  server rewrites `/api/*` to the Gateway, so the API calls still arrive. That rewrite is
  development-only — in production the browser talks to one origin and Traefik does the routing.
