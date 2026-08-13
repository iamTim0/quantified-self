# 🗺️ Quantified Self Platform — Project Roadmap

**Current Status**: **MILESTONE 8 COMPLETE** (Metric quarantine, tenant-scoped mapping rules and deferred replay are implemented; Phase 5/6 follow-up and final Phase 10 verification remain).

---

## 🟢 Phase 0: Architecture & Foundation (COMPLETED)

- [x] **Monorepo Architecture**: Independent microservices (`api-gateway`, `core`, `analysis`, `importers/yazio`, `importers/dawarich`).
- [x] **Database & Storage**: PostgreSQL 16 + TimescaleDB hypertable (`data_points`) + `pgvector` embeddings + PostGIS `geometry(Point, 4326)` + JSONB metadata.
- [x] **Infrastructure**: Docker Compose (`postgres:5433`, `nats:4222` JetStream), Taskfile, `uv` package management.
- [x] **Tenant Isolation**: Async-safe `contextvars` tenant context middleware enforcing `WHERE tenant_id = :tid`.
- [x] **Event-Driven Ingestion**: NATS JetStream consumer in Core service with exact-once deduplication via `idempotency_key`.
- [x] **Protobuf & gRPC Setup**: Code generation script (`packages/proto/generate.py`) for Python stubs.
- [x] **Formal Verification**: Fizzbee specifications (`specs/distributed_ingestion.fizz`, `specs/tenant_isolation.fizz`) + passing invariant and integration tests.
- [x] **Alembic Migrations**: Setup with mandatory `downgrade()` rollback functions (`alembic/versions/001_initial_schema.py` through `005_add_postgis_location_support.py`).
- [x] **Docs-as-Code Standard**: Implemented industry-standard "Docs-as-Code" methodology—maintaining all system documentation, API specifications, and agent guidelines (`AGENTS.md`, `README.md`, `ROADMAP.md`, `GEMINI.md`) version-controlled directly alongside code and synchronized via `doc-sync`.

---

## 🟢 Phase 1: Real Yazio & Dawarich Importers (COMPLETED)

- [x] **Yazio Client & API v15 Integration** (`services/importers/yazio`):
  - Yazio API v15 client for `/v15/user/consumed-items`, `/v15/user/summary`, `/v15/products/{id}` and `/v15/recipes/{id}`.
  - Resolves human-readable food names (`food_name`), exact calories, and macro ratios (Protein, Carbs, Fat) matching Yazio App 1:1.
- [x] **Dawarich GPS Location Importer** (`services/importers/dawarich`):
  - Dawarich API integration for `/api/v1/points` fetching WGS84 GPS coordinates (`latitude`, `longitude`, `altitude`).
  - Automated PostGIS spatial indexing (`geometry(Point, 4326)`) and interactive OpenStreetMap & Vector Route trajectory visualization in Next.js.

---

## 🟢 Phase 2: Per-User Sync Frequency & Connector Config (COMPLETED)

- [x] **Configurable Poll Frequency & Lookback**:
  - Core API (`POST /api/v1/data/sources/configure`) stores `poll_interval_hours` (1h, 3h, 6h, 12h, 24h, 168h) and `lookback_days` (7d, 14d, 30d, 60d, 90d).
  - Dynamic `last_sync_at` tracking returned on `GET /api/v1/data/sources`.
- [x] **Provider Catalog & 2-Step Modal Workflow**:
  - Step 1: Provider selection gallery (Yazio [Active], Dawarich [Active], Whoop [Coming Soon], Apple Health [Coming Soon]).
  - Step 2: Provider credential and sync schedule configuration form with live NATS queue group transparency.

---

## 🟢 Phase 3: Next.js 16 Web Dashboard & Trend Visualizer (COMPLETED)

- [x] **Next.js 16 App Router UI** (`apps/dashboard`):
  - Sleek, glassmorphism dark-mode interface built with Tailwind CSS & Lucide icons.
  - **Summary Metrics Cards**: Calories, Protein, Carbs, Fat, Sleep Score, Readiness Score, Dawarich GPS Standorte.
  - **Interactive OpenStreetMap & Vector Route Plotter**: Leaflet JS integration with custom map markers, clickable popups, and dark vector fallback.
  - **Responsive Charting**: ChartJS container with strict aspect ratio containment (`maintainAspectRatio: false`) and dynamic chart type switcher (Area, Line, Bar).

---

## 🟢 Phase 4: Universal Data Explorer & Saved Views System (COMPLETED)

- [x] **Universal Multi-Metric Query Engine**:
  - Full-text real-time search across food names, metric types, units, and raw metadata.
  - Multi-metric selection pills for side-by-side comparison on a unified timeline.
  - Aggregation modes: `SUM` (daily total calories/macros), `AVG` (daily average scores), `MAX` (daily peaks), `RAW`.
- [x] **Saved Views**:
  - Preset views (e.g. *"🍏 Yazio macronutrients"*, *"🔥 Calories and products"*, *"🌙 Sleep and recovery"*).
  - 1-click custom view saving, loading, and deletion persisted in `localStorage` & backend database.

---

## 🔵 Phase 5: Planned Importers & Integrations (Upcoming)

- [x] **🏋️ Streak / Gym Log App Importer**:
  - Importer service for Streak gym logging app to record workout sessions, sets, reps, weight lifted, and exercise progression history.
- [x] **🏠 Home Assistant Importer**:
  - Importer service integrating with Home Assistant API to collect smart home environmental metrics (bedroom temperature, humidity, noise levels, light exposure) for sleep & recovery correlation.
- [x] **⛅ Wetter Importer (Weather Data)**:
  - Open-Meteo / Weather API importer bringing historical and real-time local weather metrics (temperature, barometric pressure, precipitation, UV index) to correlate weather patterns with mood, HRV, and physical performance.
- [x] **📅 Kalender Importer (Calendar Data)**:
  - iCal / Google Calendar / Outlook integration importing daily schedules, meeting durations, and busy hours to analyze cognitive stress, routine consistency, and sleep impact.
- [ ] **🐙 GitHub Statistics Importer**:
  - Optional, tenant-scoped GitHub integration for importing user-authorized contribution statistics such as commits, pull requests, issues, reviews, and repository activity, with incremental synchronization, rate-limit handling, canonical metric registration, and provenance metadata.
- [ ] **⌚ Additional Health Wearables**:
  - Whoop, Apple Health, Garmin, Strava, and Oura ETL microservices.

---

## 🔵 Phase 6: Core Data Platform & UI Features (Upcoming)

- [x] **🔍 Data gap detection**:
  - Intelligent engine in Core / Analysis service detecting missing tracking days or timeline gaps across all connected sources.
  - Highlights data gaps visually in the Dashboard UI with 1-click backfill and manual entry triggers.
- [ ] **📁 Universal CSV and DB importer with a visual editor**:
  - Generic CSV & SQL/SQLite export importer featuring a drag-and-drop web upload interface.
  - **Visual Column Mapper & Data Editor**: Interactive UI allowing users to map arbitrary CSV columns to Quantified Self metrics, preview data tables, correct missing values or formatting errors visually, and execute batch imports.
  - Column headers arrive in whatever language the exporting app was set to, so the mapper reads and writes the connector mapping rules of Phase 8 rather than asking for the same translation on every upload.
- [x] **📈 Deterministic Insight Foundation**:
  - Tenant-scoped daily Pearson correlation analysis with a Dashboard Data Quality Center.
- [ ] **🤖 Generative AI & Vector Insight Features**:
  - gRPC reader querying Core → vector embeddings with `pgvector` → LLM health insights, trend anomaly alerts, and cross-metric correlation analysis.
- [ ] **📱 Mobile-first Dashboard**:
  - Optimize the dashboard layout, navigation, charts and import controls for phone-sized screens so the workspace remains useful on mobile.
- [ ] **🗓️ Daily Story Dashboard**:
  - Add a deliberate daily overview that turns the newest imported activity into an understandable timeline, highlights what happened today, and surfaces selected statistics from the analysis service instead of showing an arbitrary collection of cards.
- [ ] **🤝 Cross-Tenant Data Sharing**:
  - UI & API for managing `tenant_shares` consent grants with friends, family, or health coaches.
- [ ] **🔀 Smart Duplicate & Cross-Source Conflict Resolution**:
  - Core Service fuzzy duplicate detector for cross-source metrics (e.g. Yazio vs. Apple Health).
  - Dashboard UI "Conflict Resolver" modal for user approval/rejection of ambiguous duplicate entries.

---

## 🔵 Phase 7: Adaptive Ingestion, Importer Reliability & Authentication (Planned)

- [x] **Adaptive Import Windows & Gap Backfill**: derive connector-specific overlap windows, detect missing data, and recommend exact tenant-scoped backfill periods in the data UI.
- [x] **Smart Time-Range Duplicate Detection**: use coarse blocks and interval/binary search by default, with safe fallback for non-contiguous duplicates and a user-confirmed Force Import mode.
- [ ] **Importer Audit & Integration Coverage**: review every importer, including credentials, API/feed semantics, pagination, rate limits, time zones, incremental sync, retries, NATS, Gateway/Core, Docker and health checks.
- [x] **Calendar ICS Correctness**: valid Outlook/Office ICS URLs must not require an unrelated API key; distinguish public/private ICS feeds from OAuth/API integrations.
- [ ] **Importer Tests**: add self-contained unit, integration and end-to-end coverage using Docker-backed test services where appropriate.
- [x] **Tenant-Bound Authentication**: map bearer tokens and generated inbound API keys to exactly one tenant using only `Authorization: Bearer <token>`; hash, rotate, revoke and least-privilege keys.
- [x] **Logout & OIDC**: invalidate all session material on logout and add Google plus generic OIDC using Authorization Code + PKCE, state/nonce validation and safe account linking.
- [x] **Analysis Dashboard Expansion**: organize correlations, trends, anomalies, data quality, period comparisons, routines and baselines with interactive, statistically cautious visualizations.
- [x] **Vector-First Geodata UI**: make vectors the default, lazy-load optional map providers, evaluate free alternatives, and always provide a vector fallback.

## 🟢 Phase 8: Metric Mapping & Deferred Ingestion (COMPLETED)

Before Phase 8, a name this platform did not recognise cost the reading. Core acked and dropped
the event (`core/events/consumer.py`), and only the *shape* survived in
`ingest_field_reports`, which stores no values by design. That was the right answer for a field
nobody had looked at yet and the wrong one for a field whose only problem was its spelling: an
export can name its steps column in whatever language the app was set to, and a provider can
rename `avgHeartRate` to `heartRate`. Phase 8 keeps the value while the question is open and
lets the tenant answer it.

- [x] **🧊 Quarantine instead of drop**:
  - Store an unresolvable point in its own tenant-scoped table rather than discarding it —
    raw `metric_type`, timestamp, value, metadata (including `provider_value` and `units`),
    the importer's `idempotency_key`, connector, sync run, first and last seen.
  - Never in `data_points`. An unresolved name must not be readable by any analysis, chart or
    export, which is what keeps rule 15 true while the value is held.
  - Cascades from tenant and connector and is covered by account deletion, like
    `ingest_field_reports`.
- [x] **🔗 Per-connector mapping rules**:
  - Resolve an unmapped name in the Data Quality Center, which already lists it under
    **Not yet supported**, with four outcomes: **map**, **adopt**, **discard**, **keep**.
  - **Map** — the name is a catalogued metric under another spelling. The rule names the target
    metric *and the unit the source states*, because a translated export is as likely to change
    the unit as the name, and `convert()` runs on replay.
  - **Adopt** — a genuinely new quantity, landing in the `custom_` dynamic namespace with a
    declared unit, aggregation and cadence.
  - **Discard** — drop it and keep dropping it; the rule is what stops the same name arriving
    into the queue forever.
  - **Keep** — no decision yet. The rows wait, which is the point.
  - Rules are applied by Core before rejection and are held by Core. Importers stay stateless
    (rule 8) and learn nothing they would have to store.
- [x] **🔁 Retroactive replay**:
  - Applying a rule replays every quarantined row it matches as an ordinary tenant-scoped run,
    visible in the connector's history with the usual `ON CONFLICT DO NOTHING`.
  - Promotion **re-derives** `idempotency_key` from the canonical name via the shared
    `idempotency_key()` helper — the same value an importer produces once its transformer or the
    registry catches up. Rewriting the name without the key is precisely what the consumer
    rejects today, because it is how a series ends up with two rows per reading.
  - A rule applies to new arrivals from then on: a translation problem is answered once, not
    once per sync.
- [x] **🚧 The limits — a mapping is not a licence to invent**:
  - A rule may never redefine a name the registry already catalogues. A tenant-local rewrite of
    `steps` would put a wrong number in the same column as the right ones, and a wrong number is
    worse than a missing one (rule 19) because nothing distinguishes it from a right one.
  - Adoption goes under `custom_`, never as a bare name. A tenant does not extend the registry;
    the registry is extended in a commit.
  - Quarantine is bounded — caps on distinct unknown names and rows per connector, with refusals
    recorded rather than silent, and a retention default where *keep indefinitely* is an explicit
    per-name choice. A provider that nests record identifiers into keys otherwise fills the table
    with one name per record, the same failure `MAX_TRACKED_PATHS` already guards the field report
    against.
  - The Data Quality Center reports both capacity dimensions per connector, warns as soon as held
    values exist, explains the possible loss at 50%, escalates at 75%, and keeps a critical state
    visible after any value has been refused. It refreshes while the page is open, so a large
    import does not make the user discover the limit only after mapping.
  - Quarantine holds values, which the field report deliberately does not, so it stays a queue and
    never becomes the raw-payload archive rule 19 forbids: one row per unresolved point, no whole
    payloads. The categories the Apple Health archive path skips on purpose — ECG, cycle tracking,
    medications, State of Mind, clinical records — are excluded *before* quarantine and stay named
    in the field report only. An unrecognised field is not a way around a decision made deliberately.
- [x] **📊 Feedback into the registry**:
  - A tenant-scoped aggregate view of repeated rules — names and counts, no values or connector
    identifiers — turns repeated resolutions into evidence for a registry alias or transformer
    fix without leaking one tenant's data into another. It joins the field report's shape signal
    with this phase's resolution signal.
  - Nothing leaves the machine on its own, for the reason the field report's **Copy report** already
    gives: an outward-facing action is a decision the user makes each time.
- [x] **✅ Specification, tests and documentation**:
  - Fizzbee spec for the quarantine → resolve → replay transition: a quarantined row is promoted
    exactly once or discarded, never both, and never lands under a tenant other than the one it
    arrived for.
  - Documentation in [data quality](docs/features/data-quality.md) for the resolution workflow, and
    in [metrics](docs/metrics.md) for how a tenant rule relates to a registry alias.

## 🔵 Phase 9: Documentation & Legal Pages (Planned)

- [x] **Hosted MkDocs Material Documentation**: build and host a standalone `squidfunk/mkdocs-material` site with navigation, search, mobile layout, CI build and link validation.
- [x] Document architecture, data flows, analyses, importers, data gaps, Smart/Force import, APIs, operations, security, limitations and troubleshooting.
- [ ] Add contextual links from dashboard, import configuration, gap detection, duplicate detection, settings, login, registration and footer.
- [x] **German Privacy Policy & Imprint**: add plain, responsive text pages without cards or decorative UI; use realistic implementation-based templates, explicit placeholders, and a legal-review warning.

## 🔵 Phase 10: Verification & Governance (Required)

- [ ] Use Sub-Agents for independent importer, integration, test and documentation reviews when available; critically validate their results.
- [ ] Verify Core-only database ownership, gRPC Analysis access, NATS importer flow, tenant filters, idempotency, `X-Request-ID`, secret handling and no shared mutable state.
- [x] Update Fizzbee specifications and invariant-referencing test docstrings for new distributed behavior.
- [ ] Run linting, type checking, unit/integration/E2E tests and the MkDocs build; record unavailable external services, failures, risks and follow-up work.
- [ ] **Automated Release Workflow**: Implement a release workflow that automatically derives the version bump from conventional commits (e.g. `feat:`, `fix:`), generates changelogs, and publishes releases.
