# Operations, deployment and monitoring

## Local development

```bash
task dev:up            # Postgres, NATS, Traefik, dashboard, docs
task dev:docker        # the same stack, but with the checkout mounted
task db:migrate        # Alembic to head
task dev:local         # backends locally instead of in containers
task docs:serve        # documentation on :8003
```

Without Postgres on `:5433` the integration tests fail — that is expected, not a defect.

### Which address to open

The UI always calls its **own** origin. So there is exactly one address per mode of operation at
which both the page and `/api` are answered:

| Mode | Address | Who routes |
| --- | --- | --- |
| `task dev:up` (everything in containers) | `http://localhost:8080` | Traefik: `/` → dashboard, `/api` → Gateway |
| `task dev:docker` (containers + checkout mounted) | `http://localhost:8080` | the same Traefik routing |
| `task dev:local` (backends locally) | `http://localhost:3000` | the dev server: `/api` is rewritten to the Gateway |

Only `:8080` also answers `/docs` — the documentation is a container of its own behind the same
Traefik. In `dev:local` it is not running, so every `/docs/…` link in the interface (sidebar,
connector dialogs, API keys) leads nowhere. If you are working on the documentation, use
`dev:docker`.

The individual services' published ports (`:3000` in the container stack, `:8000` on the Gateway)
are there for debugging, not for using. Open container port 3000 directly and you bypass Traefik —
then nobody answers `/api`, and the sign-in screen cannot even establish whether registration is
allowed.

The Gateway also serves the UI on its own port by proxying it through. That is meant for
production-like checks — the browser tests run over exactly that, because a single origin makes the
session cookies behave the way they do in operation. For day-to-day development `:3000` is the right
address: hot reload works there.

### Developing inside containers (`task dev:docker`)

The same stack as `dev:up`, but every service reads its code from the checkout rather than from the
image (`infra/docker-compose.dev.yml`). A change then needs no rebuild, and there is still a single
address for the interface, `/api` and `/docs`.

What a change costs depends on the service:

| Service | Takes effect |
| --- | --- |
| Core, Gateway, Analysis | immediately — `uvicorn --reload` |
| Importers | after `docker compose … restart <service>` (seconds, no rebuild) |
| Dashboard | after `… restart dashboard` (~10 s) |
| Documentation | immediately — `mkdocs serve` watches `docs/` itself |

The dashboard is the one case without hot reload, and that is a property of the platform rather than
a misconfiguration: Turbopack detects changes through inotify, and a bind mount of a Windows or macOS
directory does not deliver those events into the container. The container *reads* the changed file
correctly as soon as it is asked — the watcher simply never hears about it, so the dev server keeps
serving its cached state. If you are working on the interface for a while, run `next dev` natively on
the host; for everything else the restart is cheaper than switching modes.

After a change to `package.json` or `bun.lock` a rebuild is not enough: `node_modules` lives in a
named volume that is only populated from the image once. `task dev:docker:reset` is there for that.

## Tests

```bash
task test:all          # packages, specs, Core, Gateway, Analysis, e2e, importers
task test:core         # Core only (needs Postgres)
task test:analysis     # the statistics and the service boundary
task test:packages     # the metric registry and catalog drift
task test:importers    # every importer with a pyproject.toml
task lint:all          # Ruff, oxlint, tsc
task docs:build        # MkDocs --strict
```

## Required configuration

| Variable | Purpose | Required in production |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection | yes |
| `NATS_URL` | Broker | yes |
| `CORE_ROLE` | Core runtime role: `all`, `api`, `ingest` or `scheduler` | no (`all` locally) |
| `JWT_SECRET` | Signature of the user tokens | **yes — the default is unsafe** |
| `INTERNAL_SERVICE_SECRET` | Secret for internal service calls | **yes** |
| `INTERNAL_SERVICE_SECRETS` | Optional JSON map of distinct service credentials, keyed by service name | no during rollout |
| `ENCRYPTION_KEY` | Fernet key for connector credentials | **yes** |
| `ACCESS_TOKEN_TTL_MINUTES` | Access token lifetime (720 by default) | no |
| `REFRESH_TOKEN_TTL_DAYS` | Refresh token lifetime (30 by default) | no |
| `ALLOW_REGISTRATION` | Allow self-registration. **`false` by default** — the first account is created by `python -m core.create_owner` | no |
| `PUBLIC_HOST` | The hostname Traefik serves under. Deliberately nowhere in the repository | yes |
| `ALLOWED_ORIGINS` | The Gateway's CORS origins | yes |
| `MAP_TILE_HOSTS` | Tile hosts allowed by the CSP | no |

!!! danger "Without these three values the production stack no longer starts"
    `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` and `ENCRYPTION_KEY` have development defaults that are
    printed in this repository. Anyone who knows them can forge tokens and decrypt stored
    credentials.

    Until recently this was a request: the production compose file contained
    `${JWT_SECRET:-dev-secret-key-quantified-self-2026}`, so a deployment without the variable set
    ran on the public value — and said nothing about it. `docker-compose.prod.yml` uses
    `${VAR:?…}`; if a variable is missing, `docker compose` aborts before a container starts. On top
    of that, Core and the Gateway refuse to start when `ENVIRONMENT` is production-like and a value
    matches a published default.

    ```bash
    python -c "import secrets; print(secrets.token_urlsafe(48))"
    ```

    `INTERNAL_SERVICE_SECRET` has to be identical on Core **and** on every importer while the
    legacy shared-credential mode is used. For separated credentials, set
    `INTERNAL_SERVICE_SECRETS` to a deployment secret store value such as
    `{"analysis":"…","apple_health":"…","whoop":"…"}` and set the matching secret in each
    service. Importers send their stable service identity with the request; Core rejects a token
    minted for another identity. The shared value remains a deliberate migration fallback until
    every service has a dedicated credential.

### Rotating `ENCRYPTION_KEY`

This key is the one that cannot simply be replaced: it decrypts connector credentials and OIDC client
secrets that are already stored. Change it without preparation and every stored token is permanently
unreadable — the importers run empty and there is nothing to fall back to.

So re-encrypt first, then switch:

```bash
# 1. Dry run. Shows what would happen and writes nothing.
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.rotate_encryption_key --old "$OLD" --new "$NEW" --dry-run

# 2. Re-encrypt. One transaction; an abort leaves everything on the old key.
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.rotate_encryption_key --old "$OLD" --new "$NEW"

# 3. Only now set ENCRYPTION_KEY to the new value and restart Core.
```

The tool aborts as soon as a value decrypts with **neither** key, and then writes nothing at all. A
database sitting half on the old key and half on the new one would be the expensive mistake, because
nothing would record which row is on which. Values that are already on the new key are left
untouched — so a second run after an abort is safe.

!!! tip "If the dry run reports »UNREADABLE«"
    Then at least one value is on a third key. That happens when the same database was run with a
    different configuration at some point in between. Those credentials cannot be recovered; they have
    to be entered again in the dashboard. After that the re-encryption completes.

### Creating the first account

`ALLOW_REGISTRATION` is `false` by default. A personal analytics platform that is open to everyone
should be a decision, not what happens when nothing is configured. That does leave no way in to begin
with — which is what this command is for:

```bash
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email you@example.com --workspace "My data"
```

The password is prompted for rather than passed as an argument: command lines end up in the shell
history, in `ps` and in CI logs. For automated setup, `QS_OWNER_PASSWORD` works as an environment
variable. The minimum length is 12 characters — this account is the entire way in, and whoever creates
it is free to choose.

A second call with the same address **overwrites nothing**; it aborts. Resetting a password is
`--reset-password` and therefore a deliberate instruction; it also ends every existing session of that
account.

Deliberately a command and not a startup step: rule 9 forbids services to create data while coming up,
and this repository's own history says why — `infra/db/init.sql` used to create an account with a
shipped password hash, so that every clone contained the same credentials for the same address.

If you actually want self-registration, set `ALLOW_REGISTRATION=true` — and know that the application
is then open to anyone who knows the address.

## Deployment

`docker-compose.prod.yml` describes the production stack: Traefik, Gateway, the Core API, ingest and
scheduler roles, Analysis, dashboard, documentation and the eight importers. It **builds nothing**;
it pulls the images the release workflow
published — a deployment is a download and a restart.

The full walkthrough — cutting a release, first install, updating, rolling back, this stack's variables
— is under [Release and deployment](deployment.md). In short:

```bash
export PUBLIC_HOST=your-domain.example
export JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export INTERNAL_SERVICE_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
export ENCRYPTION_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
export ALLOWED_ORIGINS=https://$PUBLIC_HOST
export QS_VERSION=1.0.0        # which release should run

docker compose -f docker-compose.prod.yml config >/dev/null   # names any missing variables
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email you@example.com --workspace "My data"
```

`up` migrates before Core serves: the `core-migrate` service runs `alembic upgrade head` and exits, and
the API, ingest and scheduler roles start only once that has succeeded. A container of its own rather than Core's entrypoint, so that
several replicas coming up at once cannot migrate against each other — and not a step in these
instructions, because a deploy that only starts the stack has nowhere to type one. Self-registration is
off, hence the last command — see [Creating the first account](#creating-the-first-account).

If there is already real data in the database, `ENCRYPTION_KEY` is **not** free to choose — then
[re-encrypt](#rotating-encryption_key) first.

### Testing it

`tools/smoke_deployment.sh` checks a deployment from outside — reachable, closed, and what it says about
its own configuration:

```bash
bash tools/smoke_deployment.sh https://$PUBLIC_HOST

# With credentials it also checks sign-in, a tenant-scoped read,
# and the self-report:
OWNER_EMAIL=you@example.com OWNER_PASSWORD='…' \
  bash tools/smoke_deployment.sh https://$PUBLIC_HOST
```

What it checks:

| Check | Expectation |
| --- | --- |
| `/health` | `200` when all services are ready; `503` with per-service status while degraded |
| `/` | `200` — the dashboard |
| `/docs/` | the documentation, recognized by the page content and not only by the status code |
| `POST /api/v1/auth/signup` | **`403`** — otherwise the application is open to anyone who knows the address |
| `/api/v1/data/metrics` without a session | `401` |
| `/api/v1/internal/…` | **not** `200` — decrypted connector credentials live there |
| Sign-in + read | `200` |
| `/api/v1/data/system/warnings` | empty |

The last one is the most informative: it asks the application what it has to say against its own
configuration. A correctly set up production deployment reports nothing there.

!!! note "Over `http://`, two results are to be expected"
    Secure cookies cannot be transmitted over unencrypted HTTP. A deployment that is only reachable
    over `http` therefore needs `COOKIE_SECURE=false` — and then reports `cookies_not_secure`. So the
    script only judges the self-report for `https` addresses, and otherwise just prints it.

    `/docs/` also fails when Traefik and the docs container are not running: the dashboard answers
    there instead.

### Network boundaries (production Compose)

This section describes the `docker-compose.prod.yml` topology, which is also the topology used when Coolify
starts the stack. The application network contains its own cloudflared-to-Traefik ingress. Coolify's global
proxy can continue serving unrelated applications but is not in this stack's request path. See the
[Cloudflare networking procedure](deployment.md#cloudflare-networking-in-coolify).

Only Traefik belongs on the outside, and through it the Gateway, the dashboard and the docs. **Core must
not be publicly reachable** — it serves decrypted connector credentials over `/api/v1/internal/*`. Core
does authenticate those calls itself these days, but the published port remains needless attack surface.

Since `docker-compose.prod.yml` that is no longer a request but the state of things: **Core publishes no
host ports.** The old production compose file exposed `8001` and `50051`, although Traefik never routed
them. Inside the compose network the API role is reachable at `core:8001` and `core:50051` as before.
The `core-ingest` and `core-scheduler` services expose no host ports and are not request targets.
Use `/health` for process liveness and `/readyz` to verify the database, NATS and gRPC dependencies
of the relevant role before routing traffic or declaring ingestion ready.

The Traefik dashboard likewise now listens on `127.0.0.1` instead of on every interface — it runs with
`--api.insecure=true`, which on a public host made it an unauthenticated admin UI. Reach it through an
SSH tunnel: `ssh -L 8081:127.0.0.1:8081 user@host`.

The importers for Apple Health (`:8005`) and Streak (`:8006`) do have to be reachable, because external
devices send to them.

## What the dashboard says about itself

You do not have to read this chapter to notice the points in it: Core reports them over
`GET /api/v1/data/system/warnings`, and the dashboard shows them to owners and administrators as a banner
above the content — on every tab, with the relevant command to copy.

Reported are published default values for `JWT_SECRET`, `ENCRYPTION_KEY` and `INTERNAL_SERVICE_SECRET`,
open self-registration, a missing `Secure` flag on the cookies, and a password whose hash was in a
published source. The details, and the reasoning about who may see what, are under
[Warnings in the dashboard](features/authentication.md#warnings-in-the-dashboard).

A production deployment should show nothing here. If it does, at least one of the values from
[Required configuration](#required-configuration) is not set.

## Monitoring

- **Health checks**: the production Compose file is the source of truth. Every
  long-running image has a Docker healthcheck, and every HTTP service returns
  `status`, `service`, `version` and `commit` from its unauthenticated health
  endpoint with `Cache-Control: no-store`. The docs image uses `/healthz` because
  its route is served by nginx; NATS-only workers expose `/health` through a
  dependency-free internal server.
- **Public release check**: open `GET /health` on the public host in a browser.
  The Gateway concurrently observes every long-running first-party service and
  includes a `services` array with the observed status, version and commit for
  `core`, its two worker roles, Analysis, Gateway, dashboard, docs and all
  importers. `core-migrate` is included as `status: "expected"` because it is a
  successful one-shot job, not a live process. A missing or degraded service
  makes the aggregate return HTTP 503; `healthz` remains a local Gateway
  liveness check for Compose startup ordering. These entries are build and
  process metadata, not tenant data. Infrastructure images such as PostgreSQL,
  NATS and Traefik have independent upstream versions and are checked by Docker
  Compose.
- **Build traceability**: `version` is the release passed to the image build and
  `commit` is the source revision passed to the same build. Local images use
  `dev` and `unknown`; a production image that reports those values was not built
  by the release workflow.
- **Correlation**: every line carries `[req_id=…]`. An import can be followed with it from the trigger to
  the data point that was written.
- **Import history**: open the **Import runs** button on the Connectors page for a tenant-wide
  view, open a configured connector's **Runs** detail page for its complete history, or call
  `GET /api/v1/data/sync-runs` and `GET /api/v1/data/sources/{connector-id}/sync-runs`. It shows the
  trigger, lifecycle status, duration, request id, expected/received/processed/accepted/duplicate
  point counts and the final message per run — the most reliable answer to "why is data missing".
  The history includes failed planning,
  upload, webhook and importer runs; an unknown or missing API key cannot be assigned to a tenant
  safely and is therefore not shown in a tenant's connector history.
- **Completeness**: inspect `points_rejected`, `unsupported_fields`, `backlog_at_start`,
  `backlog_at_end`, `provider_window_start`, `provider_window_end` and `provider_exported_at` on
  the run. A successful importer request means that the importer finished publishing; it does not
  mean that the provider export covered every requested timestamp.
- **Workspace data wipe**: the owner/admin endpoint `DELETE /api/v1/data/wipe` removes the tenant's
  raw points, quarantined values and derived metric rollups in one transaction. The response keeps
  `deleted_count` for point values and reports `deleted_rollup_count` separately; no stale chart
  aggregate survives to be combined with a later re-import.
- **Resolution**: `GET /api/v1/data/metrics?resolution=auto` selects minute, hour or day buckets from
  the requested window. The Explorer shows the returned resolution and sample count. A mixed
  historical/new result reports `contains_legacy_raw=true` and marks compatibility points in their
  metadata; `rollup_available` still says whether any requested rollup rows were available.
- **Broker pressure**: the ingestion stream has bounded age and size. When it is full, new
  publishes are rejected and importers pause/retry; old unacknowledged events are not silently
  discarded. Investigate the Core consumer and database before increasing the stream limit.

```bash
task logs -- --service qs-core --level ERROR
docker compose -f docker-compose.prod.yml logs -f core
```

### Rollup backfill and nightly maintenance

Database schema migrations are automatic: `core-migrate` runs `alembic upgrade head` during
`docker compose up`, and Core starts only after it succeeds. You do not need to run Alembic by hand
after a normal deployment. The commands below are data-maintenance jobs, not schema migrations.

Run the historical backfill once after deploying the rollup code if the existing database should have
minute/hour/day rollups immediately. Then run the retention job nightly from the operator's scheduler,
not from a web request or service startup:

```bash
# One-time migration step: rebuild rollups for data imported before incremental rollups existed.
python -m core.rollup_backfill --tenant-id <tenant-id>

# Nightly: review and then enforce the configured raw-point retention.
python -m core.retention --tenant-id <tenant-id> --dry-run
python -m core.retention --tenant-id <tenant-id>
```

Rollups are retained when raw points are purged. Keep the dry-run output with the maintenance
record so a user can distinguish intentional retention from an incomplete provider export.

### Tagging workouts imported before sessions existed

Points stored before session ids were introduced do not gain one by being re-imported, and that
is deliberate rather than a gap: the idempotency key hashes the tenant, source, metric and
timestamp — not the metadata — so Core's `ON CONFLICT DO NOTHING` leaves the existing row exactly
as it was. Making it `DO UPDATE` instead would let an out-of-order NATS redelivery overwrite newer
metadata with older, which would quietly make the exact-once guarantee untrue.

So it is an explicit, tenant-scoped command, and like every job here it never runs on startup:

```bash
python -m core.session_backfill --tenant-id <tenant-id> --dry-run
python -m core.session_backfill --tenant-id <tenant-id>
```

**It only writes an id it can prove a real import would write.** Where the provider stated its own
identifier and that identifier survived in the metadata — Streak's `workout_id`, WHOOP's
`whoop_id`, Health Auto Export's `workout_id` — the digest depends on nothing but the connector
and that id, so it is reproducible exactly.

Everything else is **counted and named, not guessed**. An Apple Health *archive* workout carries
no provider id at all (Apple's export has none), and a push route fix carries only the workout
name; deriving an id for either means guessing which timestamp was the session's start. A wrong
guess is worse than leaving the row alone, because it writes an id the next real import would not
match and one workout becomes two. Untagged points still group by timestamp and title on the
workout list, and the interface marks that grouping as approximate.

Read the dry run before the real one: it prints how many points would be tagged and how many are
being left, with the reason for each source.

If the workspace can simply be re-imported, prefer that — see
[Rebuilding a workspace from scratch](#rebuilding-a-workspace-from-scratch). Everything then
arrives tagged from the start and this command has nothing to do.

## Backup

PostgreSQL is the only thing that has to be backed up — every other service is stateless.

```bash
docker compose exec postgres pg_dump -U qs_dev quantified_self | gzip > backup.sql.gz
```

`ENCRYPTION_KEY` and `JWT_SECRET` have to be backed up as well: without the encryption key, a backup of
the connector credentials is worthless.

## Scaling

- Importers are stateless and run in NATS queue groups; several replicas share the load automatically.
- Core's ingest consumer uses a queue group too.
- Core's sync-run ledger counts each broker event once, including after JetStream redelivery; it
  stores only the broker identity, not the imported value.
- Duplicate runs are prevented by **Core**, not by the importer: a connector with a `SyncRun` already
  queued, running or loading is not scheduled again. The `active_syncs` set in the importers is now only a local
  buffer against a redelivered message — it was never a distributed lock, and with several replicas it
  would have prevented nothing.
- The scheduler is single-flight through a transaction-scoped Postgres advisory lock. Several Core
  replicas are therefore unproblematic: exactly one of them plans per tick. If it dies, the connection
  releases the lock.
- Manual and scheduled planning also take a connector-scoped transaction lock around the in-flight
  check and `SyncRun` insert. Two simultaneous **Sync now** requests therefore produce one queued
  run and one transparent `sync_in_flight` history entry instead of two provider calls.
- The report tick that keeps the derived reports current is single-flight the same way, on its
  own advisory-lock key, and runs in the `all` and `scheduler` roles only. Insight runs are handed
  to the Analysis workers with `SKIP LOCKED`, so every Analysis replica may keep
  `REPORT_WORKER_ENABLED` on without two of them computing the same bundle. See
  [Precomputed reports](features/precomputed-reports.md).
- Analysis holds no database connection. Deterministic analysis and the MCP endpoint
  scale independently of Core without sticky routing. Codex chat threads are ephemeral
  process state, so `/api/v1/chat/turn` needs sticky routing when Analysis has multiple
  replicas; see [AI chat](features/ai-chat.md#known-limitations).


## Rebuilding a workspace from scratch

Session identifiers, and the resolution a point was stored at, are written at ingest
and are **not** retrofitted by re-importing: rule 4 keys a point on `(tenant, source,
metric, timestamp)` and Core inserts `ON CONFLICT DO NOTHING`, so sending the same
reading again never rewrites the row that is already there.

Two ways out of that, and they suit different situations:

- **Where the history matters**, [`python -m core.session_backfill`](#tagging-workouts-imported-before-sessions-existed)
  adds session ids to the points whose provider identifier survived in their metadata,
  and names the ones it will not guess at. It cannot restore the *resolution* a point
  was stored at — that is what the reading was, not a label on it.
- **Where it does not**, a wipe and a re-import is cleaner, faster and complete: it
  fixes the resolution too, which no backfill can.

The rest of this section is the second route.

1. **Drain the broker first.** The JetStream `ingestion` stream must be running
   `WORK_QUEUE` retention; under the old `limits` policy an acked message still
   occupied bytes until `max_age`, which is what filled 4 GiB and made every publish
   fail. Retention **cannot be changed in place** — the broker rejects it on a live
   stream — so the stream is deleted and Core recreates it correctly on the next start.

    Neither the `nats:2.10-alpine` image nor any service here ships the `nats` CLI. Core does
    ship `nats-py`, so run it from the container that already has it — no extra image, no
    network flags, nothing to pull:

    ```bash
    CORE=$(sudo docker ps -qf name=core-ingest)
    sudo docker exec $CORE python -c "
    import asyncio, nats
    async def m():
        nc = await nats.connect('nats://nats:4222'); js = nc.jetstream()
        ci = await js.consumer_info('ingestion', 'core_data_service_group')
        assert ci.num_pending == 0 and ci.num_ack_pending == 0, 'unacked data present'
        await js.delete_stream('ingestion'); print('deleted')
        await nc.close()
    asyncio.run(m())"
    sudo docker restart $CORE
    ```

    **The assertion is the safety check, not a formality.** Anything unacknowledged is an event
    Core has not written to Postgres yet, and deleting the stream would lose it. Zero on both
    counters means everything in the stream is already stored, so the delete costs nothing. If it
    trips, wait for the consumer to drain and run it again rather than removing the assertion.

    The restart is what makes Core recreate the stream: `core-ingest` holds the subscription, and
    after the delete it is subscribed to something that no longer exists. On startup it recreates
    the stream with `WORK_QUEUE` retention.

    Check it took — this should print nothing:

    ```bash
    sudo docker logs $CORE 2>&1 | grep -i retention
    ```

    Core logs a precise error naming the mismatch when the stream is still on `limits`, and it
    deliberately does not repair it for you: a stream may hold events nobody has stored yet, and
    destroying those to fix a configuration problem trades an outage that stops when someone acts
    for data loss that does not.

    Skipping this step is what reproduces the original incident, and second-resolution heart
    rate now pushes two to four times the events through that stream.
2. **Wipe the workspace.** `POST /api/v1/data/wipe` removes `data_points`, the
   rollups, the quarantine and the field reports together. `DELETE
   /api/v1/data/account` goes further and removes the account.
3. **Migrate.** `uv run --directory services/core alembic upgrade head`.
4. **Re-import.** Upload the Apple Health `export.zip`, run **Sync now** on each
   connector, and re-post the Streak history. Everything then arrives with a session
   block and at the current resolution from the start.
5. **Adjust policies if you want to.** For example
   `PUT /api/v1/data/metrics/ingest-policy/heart_rate` with
   `{"resolution": "second", "raw_retention_days": null}`. `second` is already the
   registry default for heart rate, and `null` means never purge — see
   [Data resolution and rollups](features/data-resolution.md#some-metrics-are-never-purged).

The retention command reports what it will not touch, so a dry run is worth reading
before the real one:

```bash
uv run --directory services/core python -m core.retention --tenant-id <uuid> --dry-run
```
