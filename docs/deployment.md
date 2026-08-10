# Release and deployment

This page describes both halves of a deployment: how a commit on `main` becomes a published
release with container images, and how that release runs on a server. For running it afterwards
— required variables, key rotation, backup, monitoring — see [Operations](operations.md).

## Why images at all

An earlier Coolify Compose file described the production stack and built all thirteen images **on the
target server**. That had three consequences that hurt in practice:

- A deployment needed the repository, a toolchain and several minutes of CPU on a machine that is
  only supposed to run things.
- What ran in production had been built exactly once, by nobody, with no record of which commit it
  came from.
- A rollback meant "let's hope the old state still builds the same way".

Now `.github/workflows/release.yml` builds the images once, signs their provenance and uploads them
to the GitHub Container Registry (GHCR). A deployment is a download and a restart, and
`docker-compose.prod.yml` no longer contains a single `build:` entry.

## Cutting a release

The workflow starts **manually only**. Alongside `workflow_dispatch` there is no `push:` and no
`schedule:` trigger — so a merge to `main` publishes nothing. That is deliberate: publishing an image
that a deployment will pull, and moving `latest` while doing so, is a decision.

The intended sequence:

1. Merge the change to `main`.
2. Wait for CI to be green for that commit.
3. **Actions → Release → Run workflow**, branch `main`, enter the version.

You do not have to check step 2 yourself. The `guard` job queries the CI runs for **exactly that
commit SHA** — not "the last run on main", which differs as soon as two commits land close together —
and aborts if there is no successful run for it.

### Inputs

| Input | Meaning |
| --- | --- |
| `version` | Semantic version without a leading `v`, e.g. `1.0.0` or `1.1.0-rc.1`. An existing `v<version>` tag aborts the run. |
| `platforms` | `linux/amd64` (the default) or `linux/amd64,linux/arm64`. arm64 is emulated and roughly triples the runtime — the Next.js build under QEMU is why. |
| `tag_latest` | Also moves `:latest`. Ignored for a pre-release. |
| `prerelease` | Marks the GitHub release as a pre-release. A version with a suffix (`-rc.1`) sets that by itself anyway. |
| `dry_run` | Builds every image, pushes nothing and creates no release. The way to test a release run. |
| `allow_failed_ci` | Publishes despite red or missing CI. A deliberate exception, not a shortcut. |

### What a run produces

Up to four tags per image:

```text
ghcr.io/iamtim0/quantified-self/core:1.0.0        # the version
ghcr.io/iamtim0/quantified-self/core:sha-a1b2c3d  # the commit
ghcr.io/iamtim0/quantified-self/core:1.0          # moving minor tag
ghcr.io/iamtim0/quantified-self/core:latest       # moving, never for pre-releases
```

`sha-…` is the tag that traces a published image back to a source state without trusting a name that
can move.

The two **moving** tags are set by a job of their own (`promote`), only after all thirteen images are
built. The reason is `fail-fast: false`: if the twelfth image fails, the other twelve have long since
been pushed. If they moved `latest` along with them, `latest` would point at the new version for
twelve images and at the old one for the thirteenth — a stack nobody assembled and nobody tested. On
top of that they only move on a run from the default branch: a run from an unmerged branch publishes
`1.0.0` and `sha-…`, but moves nothing a deployment points at.

For every image the workflow also writes a signed build provenance into the registry
(`actions/attest-build-provenance`), verifiable with:

```bash
gh attestation verify --owner iamTim0 \
  oci://ghcr.io/iamtim0/quantified-self/core:1.0.0
```

Along with that, a GitHub release is created with the tag `v<version>`, the changelog and an attached
`quantified-self-<version>-deploy.tar.gz`. That bundle contains exactly what a server needs —
`docker-compose.prod.yml`, `docker-compose.coolify.yml`, `infra/db/init.sql`, a prepared `.env` with the
version pinned, and a short README. No source code, no Git, no toolchain.

The release notes also list the digest of every image. Where it has to be reproducible, pin the digest
rather than the tag.

### One-off: package visibility

**GHCR packages are private after the first push, even in a public repository.** Visibility is not
inherited. While they are private, `docker compose pull` fails with `denied` for everyone but the
owner.

Once per package, under `github.com/users/<owner>/packages` → *Package settings* → *Change visibility*
→ *Public*. Never again after that.

The workflow needs no further secrets: the automatic `GITHUB_TOKEN` may write packages and releases in
this repository.

### Checking locally before a release

The thirteen images are not built together anywhere else, and a Dockerfile can rot without a test
noticing — which is exactly what had happened to the dashboard: it had two lockfiles, CI installed from
`package-lock.json` and the Dockerfile from a stale `pnpm-lock.yaml`. There is only `bun.lock` now, and
one tool that reads it everywhere. Even so:

```bash
task images:build                    # all thirteen, as in the release workflow
task images:build -- core dashboard  # only certain ones
```

The list of images lives once, in `tools/build_images.py`; the workflow reads its build matrix from it.
A new importer missing from it makes CI fail rather than simply never being published.

## Deployment

### Prerequisites

- A host with Docker and Docker Compose v2. Nothing else — no Python, no Node, no checkout.
- A DNS name pointing at the host, in `PUBLIC_HOST`.
- TLS in front: a reverse proxy, Coolify's ingress, or this stack's `cloudflared` profile.

### First install

```bash
# 1. Fetch and unpack the release bundle. Use the versioned URL, not
#    /releases/latest/download/ — that alias points at the newest release and
#    looks for exactly this filename there, so it 404s as soon as something
#    newer appears.
curl -fsSL https://github.com/iamTim0/quantified-self/releases/download/v1.0.0/quantified-self-1.0.0-deploy.tar.gz | tar -xz
cd quantified-self-1.0.0

# 2. Fill in the configuration: PUBLIC_HOST, the three secrets and
#    POSTGRES_PASSWORD. That last one can only be chosen now — PostgreSQL sets it
#    while initializing the empty volume in step 4.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # once per secret
$EDITOR .env

# 3. Check before anything starts. Names every missing variable.
docker compose -f docker-compose.prod.yml config >/dev/null

# 4. Pull the images and start. `up` migrates before Core serves: the
#    `core-migrate` service runs `alembic upgrade head` and exits, and Core waits
#    for it to succeed.
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

# 5. Create the first account — there is none, and self-registration is closed.
docker compose -f docker-compose.prod.yml run --rm core \
  python -m core.create_owner --email you@example.com --workspace "My data"
```

From a checkout the same thing is shorter:

```bash
task prod:config    # step 3
task prod:up        # step 4
task prod:owner -- --email you@example.com --workspace "My data"
```

Migrations run in a container of their own (`core-migrate`) rather than in Core's entrypoint, and that
is what keeps replicas safe: however many Core containers start, exactly one process runs
`alembic upgrade head` and the others wait for it to exit successfully. `task prod:migrate` still runs
it by hand — the command is idempotent — but no deployment depends on anyone remembering to.

This used to be a step in these instructions, and an instruction is not a mechanism: a Coolify deploy
starts the stack and has nowhere to type one, so a release whose schema had moved ran against the old
one until somebody noticed a 500.

!!! danger "Without the three secrets nothing starts"
    `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` and `ENCRYPTION_KEY` have development defaults that are
    printed in this repository. `docker-compose.prod.yml` uses `${VAR:?…}`, so it aborts before a
    container starts. The details, and the ordering trap around `ENCRYPTION_KEY`, are under
    [Required configuration](operations.md#required-configuration).

### This stack's variables

Beyond the required variables from [Operations](operations.md#required-configuration), these control the
deployment itself:

| Variable | Default | Purpose |
| --- | --- | --- |
| `QS_VERSION` | `latest` | Which release images are pulled. For anything that should be rollback-capable, enter a real version. |
| `QS_IMAGE_PREFIX` | `ghcr.io/iamtim0/quantified-self` | The registry path. Adjust it for a fork or a mirror. |
| `QS_HTTP_PORT` | `80` | The host port for Traefik — the only one that has to be public. |
| `QS_GATEWAY_PORT` | `8000` | Direct access to the Gateway, bypassing Traefik. Can be dropped. |
| `QS_APPLE_HEALTH_PORT` | `8005` | The target of the iPhone automation. |
| `QS_STREAK_PORT` | `8006` | Inbound Streak data (also routed as `/ingest` through Traefik). |
| `QS_TRAEFIK_DASHBOARD_PORT` | `8081` | The Traefik dashboard, bound **to loopback only**. |
| `POSTGRES_PASSWORD` | `qs_dev_password` | Reachable only inside the compose network. See the note below. |
| `ALLOWED_ORIGINS` | `https://${PUBLIC_HOST},http://${PUBLIC_HOST}` | The Gateway's CORS origins. The default is its own origin under both schemes — **not** `*`: the Gateway runs with `allow_credentials=True`, and a wildcard makes Starlette reflect back whichever origin asks. Both schemes, because a proxy or tunnel in front of the stack may terminate TLS and `QS_HTTP_PORT` is deliberately http. |
| `TUNNEL_TOKEN` | empty | Only with `--profile tunnel`. Leave it empty if no Cloudflare tunnel is used — without the profile the container does not start at all. |

`POSTGRES_PASSWORD` is deliberately not a `:?` required value like the three secrets: PostgreSQL sets the
password **once**, while initializing an empty volume. A new value against an existing volume changes
nothing about the password in the database — it only stops Core from connecting. To change it, do it with
`ALTER USER` in `psql` first, and then here.

### Routing: four roles

Traefik routes by role, not by enumerated paths. Four rules, each making exactly one statement:

| Priority | Route | Rule | Service |
| --- | --- | --- | --- |
| 30 | `ingest` | ``PathPrefix(`/ingest`)`` | Streak importer |
| 20 | `docs` | ``PathPrefix(`/docs`)`` | Documentation |
| 10 | `api` | ``PathPrefix(`/api`) \|\| Path(`/health`)`` | API Gateway |
| 1 | `workspace` | ``PathPrefix(`/`)`` | Dashboard |

Higher priority wins. Each route describes only what belongs to it; the **workspace takes everything
else** — because that is precisely what a UI is: the default case.

Before, every rule carried the same host expression followed by an enumeration of paths. The dashboard's
read ``Path(`/`) || PathPrefix(`/_next`)`` and so matched 2 of the 12 routes the app actually builds:
`/explorer`, `/connectors`, `/auth/callback` and every reload ran into Traefik's 404, while navigating in
the browser worked. Enumerating a single-page app's pages in the proxy is a list that goes stale at the
next feature — a catch-all does not.

**No more `Host()`.** The expression was the same deployment fact four times over, and the appended
``|| Host(`localhost`)`` decided almost nothing anyway. Enforcing hostnames belongs where TLS ends: the
tunnel, Coolify's ingress or a reverse proxy. `PUBLIC_HOST` keeps its job (Traefik delivery, the CORS
default) — it just no longer has to be copied into proxy rules.

``PathPrefix(`/api/v1/ingest/streak`)`` is gone from the ingest rule too: at priority 100 that path
shadowed the API route, and the Gateway forwards it to the importer itself — where it also picks up its
`X-Request-ID`. In both cases the API key is authenticated by the importer.

### Network boundaries

Only **Traefik** belongs in public (`QS_HTTP_PORT`), and through it the Gateway, the dashboard and the
documentation; the two importers that external devices send to also stay reachable. Two things are
deliberately different from the old production compose file: Core no longer publishes host ports, and the
Traefik dashboard listens on loopback. The reasoning and the way in are under
[Network boundaries](operations.md#network-boundaries-standalone-compose).

### Where the dashboard looks for its API

Next.js substitutes `NEXT_PUBLIC_*` into the client bundle at **build** time. In a published image
`NEXT_PUBLIC_API_URL` therefore cannot be set at run time — the variable on the container has no effect,
and `docker-compose.prod.yml` duly does not set it.

The release image is deliberately built **without** that variable. Without it the UI falls back to
`window.location.origin`, that is, to Traefik, which routes `/api` to the Gateway. One image then fits
every host.

Anyone who has to run the UI on a different origin from the API builds the image themselves:

```bash
docker build --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
  -t my-registry/dashboard:1.0.0 apps/dashboard
```

### Updating

```bash
$EDITOR .env    # QS_VERSION to the new version
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

The importers are stateless and may be replaced at any time. The ordering that matters — the new
images first, then the migration, never the other way round — is now in the Compose file rather than in
this paragraph: `core-migrate` runs the new image's `alembic upgrade head` and Core starts only once it
has exited successfully.

### Rolling back

`QS_VERSION` to the previous version, `pull`, `up -d`. That works because the images stay unchanged under
their version tag.

**Only the database does not roll back with it.** If the release in between contained a migration, it has
to be reversed before rolling back, otherwise old code meets a newer schema:

```bash
docker compose -f docker-compose.prod.yml run --rm core alembic downgrade -1
```

Every migration in this repository has a working `downgrade()` — rule 7 requires it, and CI checks it on
every run. Which migration a release brought with it is in that release's changelog.

### Checking that it really works

From outside, not from the machine itself:

```bash
OWNER_EMAIL=you@example.com OWNER_PASSWORD='…' \
  bash tools/smoke_deployment.sh https://your-host.example
```

Without credentials the unauthenticated checks run. With them the script also reports what the deployment
thinks of its own configuration — that is the part that distinguishes "it answers" from "it is set up
correctly". The dashboard shows the same findings to owners as a banner, see
[What the dashboard says about itself](operations.md#what-the-dashboard-says-about-itself).

## Coolify networking

The current `docker-compose.prod.yml` is the **standalone Compose topology**. It contains its own Traefik
container, binds host port 80, and declares a custom `qs-network`. Do not deploy that file unchanged as a
standard Coolify Docker Compose application. Coolify supplies the reverse proxy and a network of its own;
adding a second proxy and a second application network makes routing ambiguous.

Coolify's documented network-safe topology is:

```text
Internet
   │
Coolify Proxy ── Coolify-managed application network
   ├── /                  → dashboard:3000
   ├── /api and /health   → api-gateway:8000
   ├── /docs              → docs:8003  (strip /docs)
   └── /ingest            → streak-importer:8006  (if enabled)

api-gateway ──→ core:8001 ──→ postgres:5432
analysis     ──→ core:50051
importers    ──→ nats:4222 and core:8001
```

### Required Coolify setup

Use the committed `docker-compose.coolify.yml` as the Coolify Compose file. It is the network-safe
counterpart to `docker-compose.prod.yml` and must be updated in the same
change whenever a service, image, internal port, or public route changes.

1. Choose the **Docker Compose** build pack, use repository root `/` as the base directory, and set the
   Compose file location to `docker-compose.coolify.yml`.
2. Set `QS_VERSION`, `PUBLIC_HOST`, `ALLOWED_ORIGINS`, `POSTGRES_PASSWORD`, `JWT_SECRET`,
   `INTERNAL_SERVICE_SECRET`, and `ENCRYPTION_KEY` in Coolify. Use `ALLOWED_ORIGINS=https://<host>` for
   the normal single-origin deployment.
3. Do not add the `traefik` or `cloudflared` services, a custom network, or host `ports:` mappings to the
   Coolify file. Coolify's managed network and proxy must remain the only network and public entrypoint.
4. Keep the service names unchanged. Internal URLs such as `http://core:8001`, `core:50051`,
   `postgres:5432`, `nats:4222`, and `http://analysis:8010` then continue to resolve through Coolify's
   internal Docker DNS.
5. Use the HTTPS proxy routes defined by the file. The Gateway already provides
   `/api/v1/ingest/apple-health` and `/api/v1/ingest/streak`; use `/ingest` for the short Streak route
   only when that route is deliberately configured.
6. Keep the proxy entrypoint aligned with the Coolify instance. The committed file uses `http`, as required
   by the standard Coolify Traefik setup; do not copy the standalone stack's `web` entrypoint label into it.

The dashboard, Gateway, and docs may share one public hostname because the proxy routes by path. Core,
Analysis, PostgreSQL, NATS, and all polling importers remain private services with no public domain.

### Network verification

Before putting the hostname into service, verify both the public routes and the private DNS path:

```bash
# From the Coolify host, using the stack's Compose project.
docker compose ps
docker compose exec api-gateway python -c \
  "import urllib.request; urllib.request.urlopen('http://core:8001/health', timeout=5)"
docker compose exec analysis python -c \
  "import socket; socket.getaddrinfo('core', 50051)"

# From outside the server.
curl -fsS https://your-host.example/health
curl -fsS https://your-host.example/
curl -fsS https://your-host.example/docs/
```

If an internal hostname resolves to `127.0.0.1`, a service name does not resolve, or a public request
returns a Coolify 404/504, inspect the stack for a leftover custom network or an embedded Traefik service
before changing application URLs. The service-to-service names above are the contract; `localhost` is the
container itself, not another service.

For a standalone host, continue using `docker-compose.prod.yml` behind its embedded Traefik or another
external reverse proxy. The standalone file and the Coolify-managed network must not be mixed.

## When it goes wrong

| Symptom | Cause |
| --- | --- |
| `denied` on `pull` | The packages are still private. See [package visibility](#one-off-package-visibility). |
| `required variable JWT_SECRET is missing` | Exactly as intended. Set the three secrets. |
| `manifest unknown` | `QS_VERSION` points at a version for which there is no release. |
| Importers run but import nothing | `INTERNAL_SERVICE_SECRET` has to be identical on Core **and on all eight importers** — in the old production compose file it was missing from the importers, so every credential fetch was rejected. |
| The dashboard loads, API calls fail | The UI calls its own origin. Check that Traefik routes `/api` to the Gateway and that `PUBLIC_HOST` is right. |
| The release workflow aborts immediately | Either the tag already exists, or CI is not green for that commit. The error text says which. |

More failure modes under [Troubleshooting](troubleshooting.md).
