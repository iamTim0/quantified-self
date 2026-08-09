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

So there is no `stripprefix` middleware in the development stack. In production there is, and that is
right: there the documentation is an image built by `mkdocs build` that sits at the root.

When measuring this, `curl` **without** `-L` is worth it: with redirects followed it reports the 200 of
the sign-in page you end up on, and the loop looks like a success.

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

### Connector credentials can no longer be decrypted

`ENCRYPTION_KEY` differs from the one they were stored with. Re-encrypt with the old value rather than
guessing at it:

```bash
python -m core.rotate_encryption_key --old "$OLD" --new "$NEW" --dry-run
```

The dry run says which values are on which key, and writes nothing. The full procedure is under
[Rotating `ENCRYPTION_KEY`](operations.md#rotating-encryption_key).
