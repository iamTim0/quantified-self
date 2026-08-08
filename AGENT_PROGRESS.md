# Agent Progress Roadmap

Tracks the multi-phase hardening and feature work described in the original task brief.
Status values: `todo` · `in_progress` · `completed` · `blocked` · `deferred`.
An item may only be marked `completed` after it is implemented **and** verified.

> **Session note (2026-08-06).** The first agent run (Codex Cloud) produced only the roadmap
> skeleton below and then hit a sandbox/usage blocker before any implementation landed.
> This run restarted from a full repository inventory. Everything above the "Inventory"
> heading was rewritten to reflect verified facts rather than assumptions.

---

## 1. Goal and Scope

Harden authentication and tenant isolation, make ingestion window-aware and duplicate-aware,
repair the calendar connector, and bring documentation and legal pages in line with the
actual architecture — without violating any rule in `AGENTS.md`.

**Agreed scope for this run (depth-first, security and ingestion first):**

| Priority | Items | Rationale |
|---|---|---|
| P0 | #10 logout/session, #12 bearer-token tenant mapping, #13 tenant-bound API keys | These are live vulnerabilities, not missing features (see Findings). |
| P1 | #2 adaptive import windows, #3 gap detection/backfill, #4 smart/force duplicate detection | The ingestion correctness core of the brief. |
| P2 | #8 calendar ICS | Broken connector with a concrete user-visible bug. |
| P3 | #5/#6 analysis dashboard, #14 vector-first maps, #15 docs site, #16 contextual links, #17 legal pages | Explicitly deferred this run; recorded as open below. |

---

## 2. Inventory (verified 2026-08-06)

### Services

| Service | Path | State |
|---|---|---|
| API Gateway | `services/api-gateway/` | 5 modules, 367-line `main.py`. Validates JWT for `/api/v1/data/*` only. |
| Core Data Service | `services/core/` | 1043-line `main.py`, 26 routes, sole DB owner. gRPC server is an 11-line `pass` stub. |
| Analysis Service | `services/analysis/` | 22-line placeholder. No gRPC client, no analyses, **not in either compose file**. |
| Importers | `services/importers/*` | 8 live + 1 empty (`oura/` has no `.py` source; CSV upload in Core replaced it). |

### Importers

Two architectures, no shared base package (`packages/shared-schemas/` exists but **nothing imports it**;
`generate_idempotency_key` is duplicated verbatim in 5+ files).

| Importer | Type | Window source | Notes |
|---|---|---|---|
| `whoop` | NATS task consumer (full) | `config.lookback_days`, default 30 | Paginated; no token refresh. |
| `yazio` | NATS task consumer (full) | day-by-day loop over lookback | ~62 HTTP calls/sync; hardcoded mobile OAuth client creds in `client.py:14-15`. |
| `dawarich` | NATS task consumer (full) | explicit start/end from lookback | `per_page=500`, **no pagination loop** — page 2+ silently dropped. |
| `calendar` | NATS task consumer (stub) | **none** | No ICS support at all. See Findings F5. |
| `home_assistant` | NATS task consumer (stub) | **none** | Template clone of `calendar`. |
| `weather` | NATS task consumer (stub) | **none** | Template clone of `calendar`. |
| `apple_health` | FastAPI webhook `:8005` | n/a (push) | Fail-open auth. See Findings F3. |
| `streak` | FastAPI webhook `:8006` | n/a (push) | Fail-open auth. See Findings F3. |

**There is no scheduler anywhere in the repository.** Syncs fire only from connector-configure
and the manual "Sync Now" button. `poll_interval_hours` is stored, echoed to the UI, and read by
nothing.

### Authentication (as found)

- HS256, one shared symmetric `JWT_SECRET` with an identical committed default in Gateway and Core.
- Claims: `sub`, `tenant_id`, `email`, `role`, `exp`, `iat`. No `jti`, no `iss`, no `aud`, no `token_type`.
- Access token lifetime **30 days**; dev token **365 days**.
- No logout endpoint, no refresh tokens, no revocation table, no session store.
- Frontend stores `qs_token` in `localStorage`; no route guards, no `middleware.ts`.

### UI

Next.js 16.2 / React 19, app router, but all six routes are 7-line re-exports of one 443-line
client component. Chart.js 4 via react-chartjs-2. Leaflet 1.9.4 injected from the unpkg CDN.
One legal page (`/privacy`, 193 lines); no imprint, no footer in the app shell.

### Docs

MkDocs Material configured (`mkdocs.yml`, German). 22 pages, of which **74% of all lines are
internal AI planning artifacts under `docs/superpowers/`, published in the public nav**.
No architecture, operations, security, API-reference or troubleshooting page. No CI (`.github/`
does not exist). No link checking.

### Tests (baseline, before this run)

| Suite | Result |
|---|---|
| `services/core/tests` | 19 passed (requires Postgres on `:5433`) |
| importer unit tests | 873 lines total; calendar/HA/weather have **one 6-line test each** |
| `specs/tests/*` | 9 files; `test_webhook_ingestion_invariants.py` and `test_request_driven_importer_invariants.py` are `pass`-only stubs |
| `tests/e2e/test_ui_flow_integration.py` | Asserts on dicts it writes itself — would pass with `apps/` deleted |
| frontend | No test infrastructure at all |

---

## 3. Findings that changed the plan

These were discovered during inventory and are **security defects, not roadmap gaps**.

- **F1 — Core trusts `X-Tenant-ID` unconditionally.** `services/core/src/core/db/tenant.py:43-48`
  binds whatever tenant the header names; Core never verifies a signature. Core is host-published
  on `:8001` in both compose files, so anyone who can reach it reads/writes any tenant and can
  pull **decrypted** connector secrets via `GET /api/v1/internal/data/sources/{type}/token`.
- **F2 — Logout is client-only and self-reversing.** `apps/dashboard/src/app/page.tsx:141-150`
  clears `localStorage`; the bootstrap at `page.tsx:91-121` then auto-fetches
  `/api/v1/auth/dev-token` when no token is present. In dev mode a page refresh silently
  re-authenticates as `owner` of the hardcoded seed tenant. **This is the reported logout bug.**
- **F3 — Webhook ingest fails open.** `apple_health/main.py:82` and `streak/main.py:95` only
  compare the API key `if expected_key` is truthy. If the tenant has no connector configured, or
  Core is unreachable, the comparison is skipped and unauthenticated ingest is accepted for any
  attacker-chosen `X-Tenant-ID`. Both ports are published directly, bypassing the Gateway.
- **F4 — API keys are not keys.** The "API key" is the connector `access_token`, compared with a
  non-constant-time `!=`, with the tenant taken from a client header rather than from the key.
- **F5 — The calendar importer cannot read a calendar.** No `icalendar`/`ics`/`recurring_ical_events`
  dependency exists; `client.py:9` GETs `{base_url}/events` and calls `.json()`. The dashboard
  hard-requires an API key for calendar (`ConnectorModal.tsx:225-236`). `docs/importers/calendar.md`
  documents ICS parsing and metric names that the code never emits.
- **F6 — CSP blocks the map.** `apps/dashboard/next.config.ts:47-51` forbids `unpkg.com` scripts and
  non-self images, while `LocationMap.tsx` depends on both. `script.onload` has no `onerror`, so the
  failure mode is a silent grey box.
- **F7 — Docs are unreachable in production.** `docker-compose.coolify.yml` has no `docs` service,
  but 7+ UI locations link to `/docs/...`. The dev `docs` container also mounts the whole repo
  read-only, including the committed `.env`.

---

## 4. Architecture decisions

- **AD-1 — Core authenticates independently; the Gateway is no longer the only guard.** Core gains
  its own bearer verification. The Gateway keeps injecting `X-Tenant-ID` (defence in depth), but
  Core derives tenant identity from the validated token and rejects a mismatching header.
- **AD-2 — Two disjoint token audiences.** User tokens are signed with `JWT_SECRET`
  (`aud=qs-api`, `token_type=access`). Internal service tokens are signed with a **separate**
  `INTERNAL_SERVICE_SECRET` (`aud=qs-internal`, `token_type=service`). A compromised importer
  therefore cannot mint user tokens. Service tokens are accepted only on `/api/v1/internal/*`,
  where `X-Tenant-ID` is honoured as explicit service-to-service delegation.
- **AD-3 — No bearer credential is ever placed in a NATS event.** Rules out putting a short-lived
  service token in the sync task payload (would violate `AGENTS.md` rule 12).
- **AD-4 — Core computes the import window, not the importer.** Core owns sync history, so Core
  derives `window_start`/`window_end` and ships them in the `qs.task.sync.*` payload. Importers
  become window-consumers. This keeps DB ownership intact and makes the logic testable in one place.
- **AD-5 — API keys are resolved by hash, never transmitted in full to Core.** The importer hashes
  the presented key locally (SHA-256) and asks Core to resolve the hash to a tenant. The raw key
  never leaves the edge service and is never logged; only `key_prefix` is loggable.
- **AD-6 — Coverage analysis is coarse-to-fine, not per-point.** One bucketed aggregate query
  establishes block coverage; boundaries are then refined by interval subdivision on finer buckets.
  Irregular or non-contiguous data falls back to a fine-grained scan rather than assuming a single
  contiguous duplicate range.

---

## 5. Roadmap

| # | Item | Priority | Status |
|---|---|---|---|
| 1 | Inventory and detailed design | P0 | `completed` |
| 10 | Logout, session invalidation, refresh tokens | P0 | `completed` |
| 12 | Bearer-token tenant mapping (Core-side verification) | P0 | `completed` |
| 13 | Tenant-bound hashed API keys (create/rotate/revoke) | P0 | `completed` |
| 2 | Adaptive import windows | P1 | `completed` |
| 3 | Data gap detection and backfill recommendation | P1 | `completed` (API + UI; gaps become contiguous ranges with a per-connector backfill action) |
| 4 | Smart/Force duplicate detection | P1 | `completed` (API + UI; smart/force choice with a live preview of what is skipped) |
| 8 | Calendar ICS integration | P2 | `completed` |
| 9 | Importer and end-to-end tests | P1 | `completed` for changed paths |
| 18 | Final verification (lint, types, tests, docs build) | P1 | `completed` |
| 5 | Analysis dashboard restructure | P3 | `completed` |
| 6 | Additional analyses (Spearman, lagged, baselines) | P3 | `completed` |
| 7 | Full importer audit (all 8) | P3 | `completed` |
| 11 | OIDC providers (Google + generic) | P3 | `completed` |
| 14 | Vector-first geodata | P3 | `completed` |
| 15 | Hosted documentation site | P3 | `completed` |
| 16 | Contextual UI links to docs | P3 | `completed` |
| 17 | Privacy policy and imprint | P3 | `completed` |
| 19 | Continuous integration | P1 | `completed` (green as of `7e6f0d0`) |
| 20 | Session credentials in `httpOnly` cookies + CSRF | P0 | `completed` |
| 21 | Fizzbee CLI installed and specs model-checked | P1 | `completed` — all 12 verified in 33 s; see §10 |
| 22 | Server-side route guard (Next 16 `proxy.ts`) | P2 | `open` |
| 24 | Analysis as a separate service reading via Core gRPC | P1 | `completed` |
| 25 | Sync scheduler driven by `poll_interval_hours` | P1 | `completed` |
| 26 | Core-side sync authority (replaces process-local `active_syncs`) | P1 | `completed` |
| 27 | WHOOP OAuth token refresh | P2 | `completed` |
| 28 | OIDC provider admin UI + RP-initiated logout | P2 | `completed` |
| 29 | Browser-level tests (Playwright) | P1 | `completed` |
| 23 | Rotate committed default secrets | P0 (deploy) | `open` — deployment action, see §10 |

---

## 6. Verification Requirements

- Tests are self-contained and never assume pre-existing rows.
- Every query filters by `tenant_id`; every event carries `tenant_id`, a deterministic
  `idempotency_key` and `X-Request-ID`.
- No secret appears in logs, NATS payloads, API responses or unencrypted files.
- New tests reference the Fizzbee invariant they exercise in their docstring.
- Every migration has a working `upgrade()` **and** `downgrade()`.

---

## 7. Progress Log

### Decisions

See §4. Recorded as they were taken.

### Blockers and Missing Prerequisites

- Previous run: Codex sandbox helper `codex-windows-sandbox-setup.exe` missing plus usage-limit
  denial; no implementation landed. Resolved by continuing in a different environment.
- **No external provider credentials** are available here, so no importer was exercised against
  a live upstream API. All importer tests are fixture-driven. The WHOOP, Yazio, Dawarich and
  Calendar changes are verified against recorded/synthetic payloads only.
- **The Fizzbee CLI is not installed**, so `task fizz:check` could not be run. Each new spec has
  a companion Python model in `specs/tests/` that simulates the state machine and asserts the
  invariants over exhaustive short traces. That is a weaker guarantee than model checking.
- **No browser-level verification.** The dashboard has no test infrastructure at all (no jest,
  vitest or playwright). Frontend changes are covered only by `tsc --noEmit` and ESLint; the
  logout flow was not clicked through in a real browser.

### Test Results

All runs below with Postgres + NATS up via `infra/docker-compose.yml`.

| Suite | Before | After |
|---|---|---|
| `services/core/tests` | 19 passed | **83 passed** |
| `services/api-gateway/tests` | 6 passed (3 failing after auth change) | **10 passed** |
| `specs/tests` | could not collect (missing `cryptography`) | **36 passed** |
| `tests/e2e` | could not collect (ModuleNotFoundError) | **19 passed** |
| importers (8 services) | 47 passed | **106 passed** |
| **Total** | — | **254 passed, 0 failed** |

Per importer: apple_health 15, calendar 42, dawarich 10, home_assistant 1, streak 13,
weather 1, whoop 13, yazio 11.

| Gate | Result |
|---|---|
| `ruff check services/ specs/` | 81 pre-existing findings (was 83 before this work; net −2 despite ~3,000 added lines). None in newly added modules except deliberate broad `except` clauses matching existing style. |
| `tsc --noEmit` (dashboard) | clean |
| `eslint src` (dashboard) | 32 pre-existing problems; **0 in the files rewritten here** |
| `mkdocs build --strict` | passes |
| Alembic `006` upgrade → downgrade → upgrade | verified against Postgres |

---

## 8. Final Summary

### What changed

**Security (P0).**

- Core authenticates every request itself instead of trusting `X-Tenant-ID`
  (`core/security/auth.py`, `core/security/tokens.py`). Two disjoint credential families —
  user tokens (`aud=qs-api`) and internal service credentials (`aud=qs-internal`, separate
  secret) — so a compromised importer cannot mint user tokens. Service credentials work only
  on `/api/v1/internal/*`, which the Gateway no longer proxies publicly.
- Logout works end to end: `/auth/logout` (idempotent, revokes `jti` + refresh token),
  `/auth/refresh` (single-use rotation; replay revokes the whole chain), `/auth/me`. Access
  tokens 30 days → 12 hours with a rotating 30-day refresh token.
- The dashboard no longer re-authenticates itself. The `/auth/dev-token` endpoint — 365-day
  `owner` tokens for any tenant named in a query parameter, auto-fetched whenever local storage
  was empty — is gone. That was the reported "refresh after logout logs me back in" bug.
- Inbound API keys are hashed, tenant-bound, scoped to one connector, rotatable and revocable.
  The webhook importers resolve the tenant from the key hash and fail closed on every path,
  closing the fail-open ingest.

**Ingestion correctness (P1).**

- `core/ingest_planning.py`: adaptive windows derived from poll interval and sync history,
  coarse-to-fine coverage analysis with binary boundary refinement, and gap detection against
  observed cadence. New `sync_runs` table is the import/audit log.
- New endpoints: `/data/coverage`, `/data/sources/{type}/import-plan`,
  `/data/sources/{type}/sync-runs`. Smart mode narrows the window; force mode is recorded.
- All eight importers honour the window Core sends and report their run back.

**Calendar (P2).** Real ICS parsing with recurrence expansion and timezone resolution; a valid
`.ics` URL now works without an API key, in both the importer and the dashboard.

### Bugs found and fixed along the way

Beyond the roadmap items, the work surfaced these, each fixed with a regression test:

1. `change-password` picked the *first user in the tenant*, not the caller — in a multi-member
   workspace it changed the wrong person's password.
2. The calendar transformer stamped records lacking a timestamp with `datetime.now()`, producing
   a fresh `idempotency_key` — and therefore a duplicate row — on every single sync.
3. The e2e calendar fixture used `start_time`, a key the transformer never read, so that test
   passed *because of* bug 2.
4. `e2e_helpers.cleanup_test_tenant` was a `pass` stub; every e2e run leaked rows into the dev
   database (violates rule 10).
5. `specs/tests/test_webhook_ingestion_invariants.py` was three `pass`-only stubs, so the
   webhook invariants were declared but never checked — while the code was failing open.
6. Streak read connector config from a mistyped `"get"` key.
7. `yazio` and `dawarich` both defined a function *above* their module docstring and imports.
8. `data_sources` had no `UNIQUE (tenant_id, source_type)` although every lookup assumed one.
9. `task test:specs` and `task test:e2e` could not collect at all; `test:core`/`test:gateway`
   had no task entry.
10. Two of my own Fizzbee assertions were wrong rather than the system — `RevokedTokenNeverAccepted`
    and `CompromiseRevokesEveryLiveSession` were stated as global properties when both are
    point-in-time. Caught by the exhaustive trace models.

### Deliberate deviations

- **Internal service auth uses a shared secret, not a per-tenant token.** Putting a bearer
  credential in a NATS event would violate rule 12, and a tenant-scoped token is impractical for
  an importer serving many tenants. Internal peers authenticate as *services* and pass the tenant
  by explicit delegation on `/api/v1/internal/*` only. Recorded as AD-2.
- **`plan_import` skips only what is positively complete.** Partial, irregular or fragmented
  coverage all fall back to a full import. Re-importing is idempotent; wrongly skipping loses
  data permanently.
- **`recurring_ical_events` repairs backwards `DTEND` by swapping** rather than dropping the
  event. Verified and documented in the test rather than worked around.

### Open items and risks

| Item | Risk | Note |
|---|---|---|
| Tokens live in `localStorage`, not `httpOnly` cookies | XSS can steal a session | Server-side route guards need cookies plus a Next 16 `proxy.ts` (`middleware` is deprecated). Access-token TTL is now 12 h, which limits the window. |
| #5/#6 Analysis dashboard | — | `AnalysisTab.tsx` is still 49 lines with one unparameterised fetch. `services/analysis/` remains a 22-line placeholder, absent from both compose files, with no gRPC client and no server behind `CoreDataService`. |
| #11 OIDC providers | — | Not started. No OIDC code exists anywhere. |
| #14 Vector-first maps | Map is currently broken in production | `next.config.ts` CSP forbids `unpkg.com` scripts and non-self images while `LocationMap.tsx` needs both, and `script.onload` has no `onerror` — the failure mode is a silent grey box. |
| #17 Privacy policy / imprint | Legal exposure | Only `/privacy` exists, with no operator details and no imprint. Content also predates this run's auth changes. |
| #15 Docs hosting | In-app doc links 404 in production | `docker-compose.coolify.yml` has no `docs` service though 7+ UI locations link to `/docs/...`. The dev docs container also mounts the whole repo read-only, including the committed `.env`. |
| Smart/Force UI | Feature is API-only today | `import-plan` is implemented and documented but the import dialog has no date-range picker or force toggle yet. |
| API-key UI | Feature is API-only today | `ConnectorModal` still shows the old token-as-key flow for Apple Health and Streak. |
| Committed secrets | Shared `JWT_SECRET` default in Gateway and Core; `.env` is committed; Yazio OAuth client credentials hardcoded in `client.py:14-15`; `infra/db/init.sql` seeds an owner account with a committed bcrypt hash | Not addressed this run. Rotate before any real deployment. |
| Dawarich pagination | Silent data loss | `per_page=500` with no pagination loop; page 2+ is dropped. Untouched this run. |
| No CI | Nothing is enforced | There is no `.github/` at all. Every gate above is manual. |

---

## 9. Second Pass — remaining roadmap items

Everything deferred in §8 was subsequently implemented. All 15 sections of the
original brief are now addressed.

### What was added

| § | Item | Notes |
|---|---|---|
| 3, 4 | Import dialog UI | Date range prefilled from Core's derived window, smart/force choice, live preview of skipped vs. imported ranges, inline run history. Data Quality turns missing days into contiguous ranges with a per-connector backfill action. |
| 11 | API key UI | List/create/rotate/revoke; key shown exactly once; the Math.random() "key generator" is gone. |
| 12 | Vector-first map | Vector by default with zero external requests; tiles strictly opt-in; Leaflet bundled from npm so no third-party script origin; CSP allows only tile image hosts; large tracks simplified by deviation-from-line. |
| 14 | Legal pages | `/legal/datenschutz` and `/legal/impressum`, plain single-column text, highlighted placeholders, linked from footer, login, settings and docs. |
| 5, 6 | Analysis | `core/insights.py`: Pearson + Spearman, lagged correlations, trends with r², weekday routines, MAD-based anomalies, Welch period comparison, per-series quality. Six-section dashboard with a validated diverging heatmap. |
| 7 | Importer audit fixes | dawarich pagination; weather and home_assistant rewritten against their real APIs. |
| 13 | Docs + CI | First CI in the repo; production docs container; architecture, operations and troubleshooting pages; hosting URL in README. |
| 9 | OIDC | Configurable providers, PKCE, strict token validation, deliberately conservative account linking. |

### Further bugs found and fixed

Continuing the list from §8:

11. **`compare_periods` treated the most separable case as the least.** Two perfectly
    constant windows give zero standard error; the guard `if se:` fell through to
    `p = 1.0`, reporting a 100 % shift as insignificant.
12. **The OIDC signup path could insert a `user_identities` row before the `users` row
    it references.** SQLAlchemy's unit of work does not guarantee that ordering; fixed
    with an explicit flush.
13. **A test helper deadlocked against itself**, deleting rows from a nested session
    while the outer transaction still held their locks — the full suite hung rather
    than failed.
14. **Dawarich silently dropped every page after the first** (`per_page=500`, no loop).
15. **The weather importer could not have worked at all**: no coordinates, no window,
    a pointless `Authorization` header, and it expected rows where Open-Meteo returns
    columns.
16. **Home Assistant read `/api/states`**, which has no history, so a windowed sync was
    impossible and every entity collapsed into one metric.
17. **The map was broken in production**: the CSP forbade both the unpkg script and all
    tile images, and `script.onload` had no `onerror`, so the failure was a silent grey box.

### Verified at the end of this pass

| Suite | Result |
|---|---|
| `services/core/tests` | **149 passed** |
| `services/api-gateway/tests` | **10 passed** |
| `specs/tests` | **36 passed** |
| `tests/e2e` | **19 passed** |
| importers (8 services) | **137 passed** |
| **Total** | **351 passed, 0 failed** |

Per importer: apple_health 15, calendar 42, dawarich 13, home_assistant 16,
streak 13, weather 14, whoop 13, yazio 11.

| Gate | Result |
|---|---|
| `ruff check services/ specs/` | 82 findings — **below the 83 baseline** despite roughly 8,000 added lines. Remainder is the pre-existing broad-`except` style. |
| `tsc --noEmit` | clean |
| `eslint src` | 26 problems, all pre-existing; **0 in any file added or rewritten here** (was 32) |
| `next build` | passes (11 routes) |
| `mkdocs build --strict` | passes |
| Alembic 006 + 007 up/down/up | verified against Postgres |

### Open items and residual risk

| Item | Risk | Note |
|---|---|---|
| Tokens in `localStorage`, not `httpOnly` cookies | XSS can steal a session | Unchanged. Needs cookies plus a Next 16 `proxy.ts`. Access-token TTL of 12 h limits the window. |
| **Committed default secrets** | **Highest remaining risk** | `JWT_SECRET`, `INTERNAL_SERVICE_SECRET` and `ENCRYPTION_KEY` have defaults in the repository; `.env` is committed; Yazio OAuth client credentials are hardcoded in `client.py`; `init.sql` seeds an owner with a committed bcrypt hash. Documented in `docs/operations.md`, **not fixed** — rotating them is a deployment action, not a code change. |
| ~~`services/analysis/` a placeholder~~ | resolved | It is a real deployable in both compose files. The analyses moved there; it reads through Core's gRPC API and holds no database connection, enforced by an AST test. |
| ~~No scheduler~~ | resolved | Core ticks every 5 minutes, single-flight across replicas via a Postgres advisory lock. `SCHEDULER_ENABLED=false` disables it. |
| ~~OIDC has no admin UI~~ | resolved | Owner/admin CRUD plus a settings panel. The client secret is never returned and is preserved across edits. |
| ~~No RP-initiated OIDC logout~~ | resolved | Logout returns the provider's `end_session_url` when its discovery document offers one. Back-channel logout is still not implemented. |
| ~~`active_syncs` lock is process-local~~ | resolved | Core refuses to enqueue a connector with a run already in flight, so the duplicate never reaches an importer. Stale runs expire after 6 h. |
| ~~No browser-level tests~~ | resolved | 7 Playwright tests drive Chromium against a real stack, covering sign in → reload → sign out → reload, cookie invisibility to JS, cross-tab logout and CSRF. |
| ~~Fizzbee CLI unavailable~~ | resolved | All 12 specs model-check in 33 s. `task fizz:lint` runs anywhere including Windows; `task fizz:check` needs WSL 22.04+ or the container, since Fizzbee ships no Windows binary and needs glibc 2.34+. |
| ~~WHOOP token refresh~~ | resolved | Core refreshes ahead of expiry and persists the rotated refresh token encrypted. A rejected refresh surfaces as 409 "reconnect required". |

---

## 10. Third Pass — CI repair, cookie sessions, Fizzbee

Three things were asked for: get CI green, install the Fizzbee CLI, and move session
credentials out of `localStorage` into HTTP cookies.

### CI was failing for three unrelated reasons

| Job | Cause |
|---|---|
| Dashboard | `.gitignore` carried an unanchored `lib/` from the Python section, which matches a directory of that name at **any** depth. It silently excluded `apps/dashboard/src/app/lib/`, so `session.ts` — imported by `page.tsx` and the OIDC callback — existed only on the machine that wrote it and had never been committed. Local builds passed; CI could not resolve the module. |
| Core + Gateway | NATS ran as a `services:` container. That syntax cannot pass a command to the image, and the NATS server only enables JetStream with `-js`. `add_stream` failed, and because the test wrapped it in `except Exception: pass` the real error surfaced later as an unexplained `NoStreamResponseError` on publish. |
| Documentation | lychee treats a root-relative link as a hard error unless `--root-dir` is set, so the existing `--exclude '^/'` never ran — exclusion applies to a *resolved* URI. Separately, the deployment URL in the README returned 530 (Cloudflare: origin unreachable). |

All three are fixed and the pipeline is green as of `7e6f0d0`. The first is the one
worth remembering: a build that passes locally and fails in CI on a missing module is
usually a file that was never committed, and an over-broad ignore rule is the usual
reason.

### Sessions moved to `httpOnly` cookies

Recorded as an open risk in §8 and §9; now closed.

- `qs_access` and `qs_refresh` are `HttpOnly`, `Secure`, `SameSite=Lax`. The refresh
  cookie is scoped to `/api/v1/auth` so it does not ride along on every query.
- **The tokens are gone from the response bodies.** Removing them from `localStorage`
  alone would have been cosmetic: while login returns a token as JSON, any client can
  put it back somewhere readable. Tests assert their absence.
- CSRF, which `httpOnly` cookies newly expose: `SameSite=Lax` plus a double-submit
  token. `qs_csrf` is deliberately readable so the dashboard can echo it in
  `X-CSRF-Token`; an attacker's page can cause the cookie to be *sent* but cannot read
  it to build the header. Unsafe methods on the cookie path require it.
- `Authorization: Bearer` still works for services, scripts and tests, and needs no
  CSRF token — no browser attaches that header on its own.
- The privacy policy said "this application sets no cookies" and listed the
  localStorage keys. It now describes the three cookies, their flags, and why the CSRF
  one is readable.

Two defects surfaced while doing it:

- The Gateway built response headers with a dict comprehension, which silently
  collapses repeated keys. A login sets three cookies; two were being dropped.
- `change-password` revoked every session but left the cookies in place, so the UI kept
  rendering as signed-in until some later request happened to 401.

### Fizzbee: the CLI works, and the specs had never been run

Installing it exposed that the specs were unverified prose. `specs/README.md` said
`brew install fizzbee` and `fizzbee run <spec>`; the Taskfile ran
`fizzbee check specs/`. None of those exist — the binary is `fizz`, it takes one file,
and there is no `check` subcommand.

Running the real checker found:

- Mutable state declared at top level, where Fizzbee freezes it. Every spec that
  appended to a list failed with `cannot append to frozen list`.
- `exists` used as a variable name; it is a reserved quantifier keyword.
- `x = any(COLLECTION)`, deprecated in favour of `oneof`.
- **A genuine specification defect.** `tenant_isolation`'s `NoUnauthorizedAccess`
  compared results against the *live* share table, and the checker produced a
  counterexample in 3819 states: insert → grant → query → revoke left an
  already-returned result set looking unauthorized. No implementation can satisfy
  that — the response was already sent. The invariant now judges the authorization
  decision taken at query time.
- `ShareRevocationImmediate` had a body of `return True` and a comment claiming
  another invariant covered it. A tautology cannot fail, so it verified nothing. It
  has a real body now.

Installation notes worth keeping: there is **no Windows build**, and the checker needs
**glibc 2.34+**, so WSL on Ubuntu 20.04 parses a spec and then dies with
`GLIBC_2.34 not found`. Hence `infra/fizzbee.Dockerfile` and a runner that prefers a
native `fizz` and falls back to the container.

`specs/fizz.yaml` bounds exploration to 6 actions. The default of 100 does not
terminate for these models. This is not merely a speed concern: the checker holds its
state graph in memory, and an unbounded run exhausted the Docker Desktop VM and took
the local Postgres and NATS containers down with it. The runner caps container memory
so a runaway spec fails as itself.

### Verified in this pass

| Check | Result |
|---|---|
| Core | 153 passed |
| Gateway | 10 passed |
| Spec invariant tests (Python) | 36 passed |
| End-to-end | 19 passed |
| Importers | 137 passed across 8 services |
| **Total** | **355 passed, 0 failed** |
| `tsc --noEmit` | clean |
| ESLint | 25 problems, all pre-existing; 0 in any file added or rewritten (was 26) |
| `next build` | 11 routes |
| GitHub Actions | green |

### Fizzbee: finished, and where the check now runs

All 12 specifications verify — 33 s for the full set, locally and in CI.

Getting there needed two more rounds after the syntax repairs. Seven specs
reported `DEADLOCK detected`, which is Fizzbee flagging a state with no enabled
action; for a model of a workflow that finishes, that is the intended end, so
`deadlock_detection` is off with the trade-off documented in `specs/fizz.yaml`.
Then the two liveness specs timed out at 180 s: monotonic counters
(`next_idempotency_key`, `retry_count`) mint a never-before-seen state on every
step, so the graph never closes. Safety checking tolerates that because it only
reads the current state; liveness needs the whole graph. Bounded, they run in
0.3 s.

`distributed_ingestion` then failed liveness for a genuine reason worth keeping
in mind: weak fairness only obliges an action to fire while it is *continuously*
enabled, and `CoreConsume` needs the broker up, so the checker found a lasso
where the network flaps forever and the queue never drains. True, but a claim
about the network rather than the consumer. `fair<strong>` states the property
actually worth ruling out.

**Where it runs, and why not on every push.** The model check verifies the
*models*, not the implementation — a green run says the design is internally
consistent, not that the code matches it. Its cost is lumpy: a 340 MB archive and
a badly bounded spec that can run for minutes. Paying that on a push that touched
a React component buys nothing. So:

| Check | Runs | Cost |
|---|---|---|
| `lint_specs.py` (structural) | every push, and locally on Windows | seconds |
| `verify_specs.py` (model check) | changes under `specs/`, manual dispatch, weekly cron | ~1 min |

The path filter is enough to enforce AGENTS.md rule 5 — a spec cannot be added or
changed without triggering it — and the weekly cron catches a spec that stops
terminating after a Fizzbee release. Counterexample traces upload as artifacts on
failure. The failure mode this guards against is the one that already happened:
before this work the specs had never been run at all, so nobody noticed they used
syntax the parser rejects and that two assertions had a body of `return True`.

### Next steps

In the order I would take them.

1. **Rotate the committed secrets.** Still the highest risk in the repository and still
   not a code change: `JWT_SECRET`, `INTERNAL_SERVICE_SECRET`, `ENCRYPTION_KEY`, the
   hardcoded Yazio OAuth client credentials in
   `services/importers/yazio/src/yazio_importer/client.py`, and the seeded owner hash
   in `infra/db/init.sql`. Rotating `ENCRYPTION_KEY` requires re-encrypting stored
   connector credentials — plan that migration before turning the key.
2. **Finish the Fizzbee verification.** Ten specs are converted but not yet
   model-checked; the CI job added here is what confirms them. Expect each to need
   bounding the way `tenant_isolation` did. Treat any invariant whose body is
   `return True` as unwritten.
3. **Add a server-side route guard** (`proxy.ts`, Next 16's rename of `middleware.ts`).
   Cookies make this possible for the first time — the server can now see the
   credential. Today a protected page renders its shell before `/api/v1/auth/me`
   answers. No data leaks, but the flash is visible.
4. **Browser-level tests.** The frontend has no jest/vitest/playwright, so the cookie
   flows above are covered by server tests and type-checking only. Login → reload →
   logout → reload is the sequence most worth automating: it is the bug that started
   all of this.
5. **A scheduler.** `poll_interval_hours` sizes an import window but nothing triggers a
   run; every import is still manual.
6. **`services/analysis/`** is still a placeholder. Analyses run inside Core and are
   served over REST. Moving them out means finishing Core's gRPC server, which is a
   stub.

### Local environment note

Docker Desktop and WSL both became unresponsive during this session — `wsl --shutdown`
itself hung, which is why the remaining specs were verified in CI rather than locally.
A reboot should clear it. Nothing in the repository depends on that state.

---

## 11. Fourth Pass — closing the architectural gaps

Seven items, all of which had been recorded as known limitations rather than
fixed. Each is now implemented and verified.

### The analyses were in the wrong service

AGENTS.md rule 3 says Analysis reads from Core over gRPC and owns no database
connection. Core's gRPC server was an eleven-line `pass` stub, so that transport
did not exist — which is the actual reason the analyses ended up inside Core.
Nothing could have been built against it.

`CoreDataService` now serves `QueryDataPoints`, `GetDataPoint`,
`ListMetricTypes` and a new `ListDataSources`. Every handler filters on
`tenant_id` and validates it as a UUID before it reaches SQL, and every call
requires an internal service credential — the port being "internal" is not a
boundary, which is the same assumption that once let a bare `X-Tenant-ID` header
read any tenant.

The statistics are unchanged; `insights.py` and its 37 tests moved to
`services/analysis`, which obtains every input through gRPC. That rule is
enforced rather than asserted: a test parses each module's AST and fails if any
imports `sqlalchemy`, `asyncpg`, `psycopg` or `alembic`. An architectural rule
that is only written down gets broken quietly — nothing else would fail.

Two details worth keeping: `DataSourceSummary` has no field a connector
credential could travel in, and a Core outage is a 503 rather than an empty
result set, because "no correlations found" and "we could not read the data"
must not look identical to the dashboard.

### Nothing triggered an import

`poll_interval_hours` was stored, displayed and used to size a window, and read
by nothing that started a sync. Core schedules now, because Core owns both the
connector config and the sync history the decision needs.

The tick reuses `plan_and_enqueue_sync`, extracted from the HTTP handler, so a
scheduled run takes the same path as a manual one. A separate implementation for
scheduled runs is how the two silently diverge.

It takes a **transaction-scoped** Postgres advisory lock so two replicas cannot
both schedule — transaction-scoped specifically so a crashed replica releases it
when its connection dies, rather than stopping all scheduling until someone
restarts the database.

### The sync lock was process-local

Each importer kept an `active_syncs` set, which stops nothing once a second
replica exists. Rather than push a distributed lock into eight importers, Core
refuses to enqueue a connector that already has a queued or running `SyncRun`, so
the duplicate is never published. Stale runs expire after six hours: without
that, one importer crash wedges its connector permanently while the UI shows
"running" forever.

### WHOOP tokens expired after an hour

WHOOP access tokens last about an hour against a six-hour poll interval, so the
connector worked once and then 401'd until somebody pasted a new token in. Core
refreshes ahead of expiry — reacting to a 401 means every import starts with a
guaranteed-failed request against a provider that rate-limits auth failures.

Three cases lose a credential if handled naively, each now tested: WHOOP rotates
the refresh token and invalidates the old one; a response carrying no new refresh
token must keep the existing one; and editing a connector's poll interval must
carry the refresh grant over.

### OIDC: no admin UI, no provider logout

Providers were configurable only by inserting a row. Owner/admin CRUD plus a
settings panel now cover it, and saving validates the issuer's discovery document
first — validating later means the misconfiguration surfaces mid-login with a 502
as the only clue. A provider with linked accounts cannot be deleted, only
disabled: deleting it would lock out an OIDC-only account with no password.

Logout returns the provider's `end_session_url` so the browser can end that
session too. Deliberately without `id_token_hint`, which would put the user's
identity in a URL that lands in browser history and proxy logs.

### Browser tests

Seven Playwright tests drive Chromium against a real stack — Postgres, Core, the
Gateway and a production Next build — with the Gateway as the origin, because it
proxies both the UI and the API and that single-origin arrangement is what makes
the cookies behave as they do in production.

Three findings from writing them:

- `next dev` does not survive the Gateway's buffering proxy; the page arrives and
  never hydrates. `next start` does, and is what deploys.
- `page.request` shares the browser's cookie jar, so creating the account through
  it left the browser already signed in and the login form never rendered.
- Playwright's API request context will not send a `Secure` cookie over http,
  which made "a protected call after logout is refused" pass **vacuously** — 401
  whether or not logout worked. Those calls now run inside the page, with a
  companion test asserting 200 while signed in.

### Bugs found by the tooling, not by tests

Ruff's F821 caught two `NameError`s that no test would have: the scheduler's
enqueue callback used two unimported names (every scheduled sync would have
failed silently inside a `try/except` meant to stop one bad connector aborting a
tick), and the federated logout handler used `JSONResponse` without importing it.
Both now have tests that exercise the real path.

### Verified

| Check | Result |
|---|---|
| Core | 164 |
| Gateway | 10 |
| Analysis | 47 |
| Spec invariant tests | 36 |
| End-to-end | 19 |
| Importers (8 services) | 137 |
| Browser (Playwright) | 7 |
| **Total** | **420 passed, 0 failed** |
| Fizzbee | 12 of 12 specifications verified |
| Ruff | 82 (unchanged from baseline) |
| ESLint | 25 problems, all pre-existing; 0 in any new file |
| `tsc --noEmit` | clean |
| `mkdocs build --strict` | clean |
| Docker images | `services/core` and `services/analysis` both build |

### What is still open

1. **Rotate the committed secrets** (roadmap #23). Unchanged and still the
   highest risk: `JWT_SECRET`, `INTERNAL_SERVICE_SECRET`, `ENCRYPTION_KEY`, the
   hardcoded Yazio client credentials, and the seeded owner hash in `init.sql`.
   Rotating `ENCRYPTION_KEY` needs a re-encryption migration planned first.
2. **Server-side route guard** (roadmap #22). Cookies made it possible; a
   protected page still renders its shell before `/api/v1/auth/me` answers. No
   data leaks — the flash does.
3. **Back-channel OIDC logout.** If the session is ended at the provider, the
   local one survives until it expires.
4. **The Gateway's UI proxy buffers responses**, which is why `next dev` does not
   work behind it. Fine for the production build; worth revisiting if anyone
   wants to develop through the Gateway.
