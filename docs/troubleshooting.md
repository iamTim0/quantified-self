# Troubleshooting

## Import

### An import reports "skipped" although data is missing

Smart mode only skips ranges it recognizes as complete. Check the coverage first:

```http
GET /api/v1/data/coverage?start=<iso>&end=<iso>&source_type=whoop
Authorization: Bearer <jwt>
```

If that assessment is wrong, import the period again with **Force everything**. Idempotency
prevents duplicate rows. See [Smart and force import](features/smart-import.md).

### A sync stays on "queued"

The task was published, but no importer completed it.

1. Is the importer running? `docker compose ps`
2. Does it reach NATS? The log says `Subscribed to NATS subject 'qs.task.sync.…'`.
3. Did the importer get the credentials? Without a configuration it logs "staying idle" and
   deliberately does nothing.
4. Check the run: `GET /api/v1/data/sources/{type}/sync-runs`.

### Data arrives, but nothing new

Normal when the period had already been imported: the idempotency check discards duplicates.
Compare `points_accepted` against `points_duplicate` in the import history. If every point is a
duplicate, nothing is broken.

### Uploading an export file stops at a few per cent

A body-size limit in front of the platform, in almost every case. Cloudflare refuses a request body
over 100 MB on every plan below Enterprise and refuses it **at the edge**, after a couple of
megabytes have been pushed — which on a 200 MB Apple Health export reads as "it dies at 2 %". No
setting in this repository can raise it, and neither the Gateway nor the importer ever sees the
request.

The dashboard therefore sends an archive in parts of 8 MB and the importer reassembles them, so an
upload started from the interface is not subject to that limit at all. If one still stops this way:

1. Reproduce it in the interface rather than with `curl`. A single-request `POST …/upload` carries
   the whole file and is subject to the full limit; the interface is not.
2. Look for a proxy limit below 8 MB (`client_max_body_size` in nginx, a `buffering` middleware in
   Traefik).
3. Check the importer's log for the part it refused, and the connector's history for the run.

Details and the resume behaviour are under [Uploading an export file](features/file-import.md).

### A connector keeps reporting "auth error (401)"

The stored token has expired or was revoked. Enter the credentials again in the connector dialog.
For WHOOP, Core renews the token itself before it expires — a persistent `401` there means the
refresh token was rejected too, and the connector has to be connected again.

## Calendar

| Message | Cause | Fix |
| --- | --- | --- |
| "returned an HTML page instead of a calendar" | A login wall, or a withdrawn secret address | Create the feed URL again in the calendar product |
| "not found (404)" | The address was revoked | Create the link again |
| "not iCalendar data" | The URL points at the web view | Use the ICS link, not the calendar's web link |
| No events | Every event is outside the window | Widen the period |

An `.ics` link needs **no** API key. If one is demanded anyway, the URL is probably not a feed URL.
See [Calendar](importers/calendar.md).

## Signing in

### After signing out I am signed in again

That was a bug and it is fixed. If it happened again, a stale dashboard version in the browser cache
would be the most likely cause — do a hard reload.

### Every request returns 401

- Is the access token older than its lifetime (12 hours by default)? The dashboard renews
  automatically as long as a refresh token is present.
- Was the password changed? That ends **every** session.
- Was a spent refresh token presented again? That counts as possible theft and likewise ends every
  session. Sign in again.
- Did the sign-in provider end the session? A
  [back-channel logout](features/oidc.md#back-channel-logout) ends every session of the account. The
  log then says `Back-Channel logout from … ended every session for user=…`.

### Opening a sub-page lands me on the sign-in page

That is the [route guard](features/authentication.md#the-server-side-route-guard). It checks whether
a `qs_csrf` cookie is present and otherwise redirects to `/?next=<target>`; after signing in you
carry on there. Anyone who cleared their cookie store, or blocks cookies for this site, sees it on
every visit.

### 403 instead of 401

Authentication succeeded, the permission is missing. The most common cases: an `X-Tenant-ID` header
contradicts the token, or the role may not manage API keys (only `owner` and `admin` may).

## Inbound data (Apple Health, Streak)

| Response | Meaning |
| --- | --- |
| `401` | No key, an unknown key, or one that was revoked or has expired |
| `403` | The key belongs to a different connector, or the tenant header contradicts it |
| `503` | Core unreachable — deliberately not a "wave it through"; the device should send again |

The full key cannot be retrieved after it is created. If it is lost, rotate it and enter the new one
in the app.

## Map

By default the map shows a pure vector route and **deliberately** loads no tiles. "Load map" requests
tiles. If the map stays empty after that, the CSP is probably blocking the tile hosts — check
`MAP_TILE_HOSTS`.

## Analyses

### A metric does not appear

Analyses only run on a sufficient basis: at least ten days and more than 50 % coverage in the chosen
window. The **Data quality** tab shows per metric what is missing. That is deliberate — a correlation
over four days is noise with a number attached.

### A relationship looks implausible

Every result is a relationship, not a cause. Check the sample size, the p-value and the caveats in the
detail view. When Pearson and Spearman diverge strongly, an outlier is usually behind it.

## Database

### Tests fail with "Connect call failed … 5433"

Postgres is not running: `task dev:up`.

### A migration fails with "value too long for type character varying(32)"

The Alembic revision ID is too long. `alembic_version.version_num` holds 32 characters; revision IDs
have to stay below that.

## Local development

### Every API call to the dev server answers 404

`GET /api/v1/auth/config 404`, `/api/v1/auth/me 404` in the `next dev` log: that 404 comes from Next
itself, not from the Gateway. The UI calls its own origin, and here that is the dev server.
`next.config.ts` therefore rewrites `/api/*` to the Gateway in development mode (`DEV_GATEWAY_URL`,
`http://127.0.0.1:8000` by default).

If the 404 persists: is the Gateway running? The dev server only re-reads `next.config.ts` on start —
it restarts itself after a change to that file, but not after a change to `DEV_GATEWAY_URL`.

### Every page takes about 13 seconds

Measured and fixed: the Gateway looked for the UI at three addresses and started with the wrong one.
`dashboard` does not resolve outside Docker (~2.7 s of DNS failure), `host.docker.internal` does
resolve but nothing listens there — so the 10 s connect timeout ran out in full before
`127.0.0.1:3000` answered in ~50 ms. Together 12.7 s, and that **per request**, because the result was
not remembered anywhere.

The default is loopback now, the order puts loopback before `host.docker.internal`, and the address
that answered is remembered. In containers, both compose files set `DASHBOARD_URL` explicitly to the
container name.

If it happens again, `DASHBOARD_URL` is set wrongly: a name that does not resolve costs the same delay
all over again.

### The analysis tab reports 503

The Gateway proxies `/api/v1/analysis/*` to the Analysis service. Is it running? `task dev:local`
starts it along with the rest; on its own there is `task run:analysis` (port 8010).
`ANALYSIS_SERVICE_URL` has to point at the same port.

### `http://localhost:8080` answers 404

Traefik is running but has nothing to route. It finds its routes exclusively through Docker labels, and
those only exist on containers — in `dev:local` mode the services run as processes on the host and are
invisible to Traefik. Then `:3000` is the right address, not `:8080`.

You can check that without guessing: `curl -s http://localhost:8081/api/http/routers` lists what Traefik
actually knows. If it holds only `api@internal` and `dashboard@internal`, not one application route is
loaded.

### The interface stays blank on `:8000`

Expected. The Gateway can proxy `next dev` through, but the page does not hydrate behind it —
investigated and recorded in the source (`proxy_dashboard_ui` in
`services/api-gateway/src/gateway/main.py`): the proxied document is byte-for-byte identical, the HMR
socket connects, and the page still never becomes interactive. The Gateway's port is meant for
production-like checks against a built state, not for development.

Behind **Traefik**, by contrast, the same dev server hydrates perfectly; that was measured with a
browser test against `:8080`. So it is the proxying in the Gateway, not `next dev`.

### A UI change does not become visible in the container stack

Not a misconfiguration but a limit of the platform. Turbopack detects changes through inotify, and a
Docker bind mount of a Windows or macOS directory does not deliver those events into the container. The
container reads the file correctly — a `tail` inside it shows the change immediately — the watcher just
never hears about it. A newly created route answers 404 forever, a changed one keeps serving the old
markup, and neither says anything about it.

`watchOptions.pollIntervalMs` from `next.config.ts` is the documented answer to exactly this case and was
tried first. It demonstrably reaches the Turbopack watcher, but did not help: at a 1 s interval a changed
route had still not been picked up after 45 s. The setting was therefore removed again rather than left
standing as an apparent fix — anyone considering it again has hereby already tried it.

What does help: `docker compose … restart dashboard` (about ten seconds, no rebuild, because the code is
mounted), or, for longer work on the interface, `next dev` natively on the host.

The Python services are unaffected: uvicorn starts with `StatReload`, which polls the files instead of
waiting for events, and picks up changes reliably over the same mount.

### `/docs` runs into a redirect loop

Fixed; the reasoning is here. `mkdocs serve` reads `site_url` from `mkdocs.yml`, which ends in `/docs/`,
and serves the site under exactly that prefix — visible in its own log as
`Serving on http://0.0.0.0:8003/docs/`. Traefik stripped the prefix on top of that, MkDocs received
`GET /` and answered `302 → /docs/`, which was stripped again.

So there is no `stripprefix` middleware in the development stack — and, since the fix below, none in
production either.

When measuring this, `curl` **without** `-L` is worth it: with redirects followed it reports the 200 of
the sign-in page you end up on, and the loop looks like a success.

### A link inside `/docs` jumps to `<host>:8003` and does not load

Fixed; the reasoning is here, because the shape of it recurs. MkDocs writes **directory URLs**:
`docs/metrics.md` is published as `/docs/metrics/`, and a request for `/docs/metrics` without the
trailing slash is answered with a redirect to the slashed form. That redirect is composed by the static
file server, which knows two things: the port it listens on (8003) and the path it was handed. Traefik
stripped `/docs` before handing it over, so what came back was

```text
Location: http://<host>:8003/metrics/
```

— a port that is not published, plain `http` behind a TLS front, and no `/docs` at all. The browser
followed it and reached nothing. Only the slashed links worked, which is why the site looked mostly
fine: every failure needed a link, a bookmark or a typed address without the final slash.

Nothing downstream could repair it. Traefik's `StripPrefix` rewrites the request, not the `Location`
header of the response, so the prefix it removed is gone by the time the redirect is written. Serving
the page at the unslashed URL instead is not a fix either: every relative link on it would then resolve
one level too high, because MkDocs wrote them against the slashed URL.

So the prefix is no longer taken away. The image serves the site under `/docs` itself and sets
`absolute_redirect off`, which makes the redirect a bare path — `Location: /docs/metrics/` — that the
browser resolves against the origin it is already on. Scheme, host and port come from the address bar,
where they are correct by definition, and development and production now route identically.

To check it on a deployment, ask for the unslashed path and read the header rather than the page:

```bash
curl -sI https://<host>/docs/metrics | grep -i location
# Location: /docs/metrics/
```

### A diagram in `/docs` renders as an empty block

Material fetches the mermaid renderer from `https://unpkg.com/mermaid@11/…` when the page
loads — it does not bundle it. On a host with no outbound internet, or behind something that
blocks unpkg, the diagram area stays blank rather than falling back to its source.

Two ways out. Read the same diagram on GitHub, where it is rendered server-side; or vendor
the renderer into the site and stop depending on a third party:

```yaml
# mkdocs.yml
extra_javascript:
  - assets/mermaid.min.js   # 3.4 MB, committed
```

The second is also the privacy-preserving option: as it stands, every reader of `/docs`
makes a request to unpkg.

## Configuration

### Core or the Gateway will not start: "refuses to start with published secrets"

That is exactly the intent. `ENVIRONMENT` is set to something production-like and at least one of
`JWT_SECRET`, `INTERNAL_SERVICE_SECRET`, `ENCRYPTION_KEY` is missing or matches a default that is
printed in this repository. The message names every affected variable at once. See
[Operations](operations.md#required-configuration).

For local development set `ENVIRONMENT=dev` — then it only warns.

### `docker compose` aborts with "set JWT_SECRET"

`docker-compose.prod.yml` uses `${VAR:?…}`. A missing variable stops the deploy before a container
starts. Before, the same deploy would have carried on with the public default without saying anything.

### PostgreSQL is unhealthy during a production or Coolify deploy

The `timescale/timescaledb-ha` image uses a container-local data directory by default and runs as UID 1000.
The deployment Compose files explicitly set `PGDATA=/var/lib/postgresql/data` and initialize the named
volume's ownership before starting PostgreSQL. If a custom Compose override omits either setting, the healthcheck
can fail during initialization and data can remain in the disposable container layer.

Inspect the actual healthcheck output on the Coolify host before changing or removing a volume:

```bash
docker logs --tail=200 <postgres-container>
docker inspect <postgres-container> \
  --format '{{range .State.Health.Log}}{{println .Output}}{{end}}'
```

Do not delete `pgdata` until its contents have been confirmed disposable. The `postgres-volume-init` service
only changes ownership; it does not remove database files.

### Connector credentials can no longer be decrypted

`ENCRYPTION_KEY` differs from the one they were stored with. Re-encrypt with the old value rather than
guessing at it:

```bash
python -m core.rotate_encryption_key --old "$OLD" --new "$NEW" --dry-run
```

The dry run says which values are on which key, and writes nothing. The full procedure is under
[Rotating `ENCRYPTION_KEY`](operations.md#rotating-encryption_key).
