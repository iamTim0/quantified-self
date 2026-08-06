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
| 3 | Data gap detection and backfill recommendation | P1 | `completed` (API; UI prefill open) |
| 4 | Smart/Force duplicate detection | P1 | `completed` (API; UI toggle open) |
| 8 | Calendar ICS integration | P2 | `completed` |
| 9 | Importer and end-to-end tests | P1 | `completed` for changed paths |
| 18 | Final verification (lint, types, tests, docs build) | P1 | `completed` |
| 5 | Analysis dashboard restructure | P3 | `deferred` |
| 6 | Additional analyses (Spearman, lagged, baselines) | P3 | `deferred` |
| 7 | Full importer audit (all 8) | P3 | partial — inventory done, fixes deferred |
| 11 | OIDC providers (Google + generic) | P3 | `deferred` |
| 14 | Vector-first geodata | P3 | `deferred` |
| 15 | Hosted documentation site | P3 | partial — pages added, hosting/CI open |
| 16 | Contextual UI links to docs | P3 | partial — calendar + import plan only |
| 17 | Privacy policy and imprint | P3 | `deferred` |

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

### Follow-up recommendation

Next session, in order: wire the smart/force and API-key UI (the backends are done and
documented), then the map CSP fix, then legal pages, then the analysis dashboard.
