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
task lint:all          # Ruff, ESLint, tsc
task docs:build        # MkDocs --strict
```

## Required configuration

| Variable | Purpose | Required in production |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection | yes |
| `NATS_URL` | Broker | yes |
| `JWT_SECRET` | Signature of the user tokens | **yes — the default is unsafe** |
| `INTERNAL_SERVICE_SECRET` | Secret for internal service calls | **yes** |
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

    `INTERNAL_SERVICE_SECRET` has to be identical on Core **and** on every importer.

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

`docker-compose.prod.yml` describes the production stack: Traefik, Gateway, Core, Analysis, dashboard,
documentation and the eight importers. It **builds nothing**; it pulls the images the release workflow
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
docker compose -f docker-compose.prod.yml run --rm core alembic upgrade head
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email you@example.com --workspace "My data"
```

Migrations run as a step of their own on purpose, rather than when a service starts: several replicas
coming up at once would otherwise migrate against each other. Self-registration is off, hence the last
command — see [Creating the first account](#creating-the-first-account).

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
| `/health` | `200` |
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

### Network boundaries (standalone Compose)

This section describes the standalone `docker-compose.prod.yml` topology. For Coolify, use the
[Coolify networking procedure](deployment.md#coolify-networking): Coolify's proxy and managed application
network replace the embedded Traefik and the custom Compose network.

Only Traefik belongs on the outside, and through it the Gateway, the dashboard and the docs. **Core must
not be publicly reachable** — it serves decrypted connector credentials over `/api/v1/internal/*`. Core
does authenticate those calls itself these days, but the published port remains needless attack surface.

Since `docker-compose.prod.yml` that is no longer a request but the state of things: **Core publishes no
host ports.** The old production compose file exposed `8001` and `50051`, although Traefik never routed
them. Inside the compose network Core is reachable at `core:8001` and `core:50051` as before.

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

- **Health checks**: every service offers `GET /health`; the docs additionally `/healthz`.
- **Correlation**: every line carries `[req_id=…]`. An import can be followed with it from the trigger to
  the data point that was written.
- **Import history**: open a configured connector's **Runs** detail page, or call
  `GET /api/v1/data/sources/{connector-id}/sync-runs`. It shows the trigger, status, duration,
  request id, expected/received/accepted/duplicate point counts and the final message per run —
  the most reliable answer to "why is data missing". The history includes failed planning,
  upload, webhook and importer runs; an unknown or missing API key cannot be assigned to a tenant
  safely and is therefore not shown in a tenant's connector history.

```bash
task logs -- --service qs-core --level ERROR
docker compose -f docker-compose.prod.yml logs -f core
```

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
- Duplicate runs are prevented by **Core**, not by the importer: a connector with a `SyncRun` already
  queued or running is not scheduled again. The `active_syncs` set in the importers is now only a local
  buffer against a redelivered message — it was never a distributed lock, and with several replicas it
  would have prevented nothing.
- The scheduler is single-flight through a transaction-scoped Postgres advisory lock. Several Core
  replicas are therefore unproblematic: exactly one of them plans per tick. If it dies, the connection
  releases the lock.
- The Analysis service is stateless and holds no database connection; it scales independently of Core.
