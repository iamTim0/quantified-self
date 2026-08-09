# 🗺️ Quantified Self Platform — Project Roadmap

**Current Status**: **MILESTONE 6 IN PROGRESS** (Roadmap foundation: environmental importers, tenant-scoped data quality, mapped batch imports, correlations and conflict discovery).

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

- [ ] **🏋️ Streak / Gym Log App Importer**:
  - Importer service for Streak gym logging app to record workout sessions, sets, reps, weight lifted, and exercise progression history.
- [x] **🏠 Home Assistant Importer**:
  - Importer service integrating with Home Assistant API to collect smart home environmental metrics (bedroom temperature, humidity, noise levels, light exposure) for sleep & recovery correlation.
- [x] **⛅ Wetter Importer (Weather Data)**:
  - Open-Meteo / Weather API importer bringing historical and real-time local weather metrics (temperature, barometric pressure, precipitation, UV index) to correlate weather patterns with mood, HRV, and physical performance.
- [x] **📅 Kalender Importer (Calendar Data)**:
  - iCal / Google Calendar / Outlook integration importing daily schedules, meeting durations, and busy hours to analyze cognitive stress, routine consistency, and sleep impact.
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
- [x] **📈 Deterministic Insight Foundation**:
  - Tenant-scoped daily Pearson correlation analysis with a Dashboard Data Quality Center.
- [ ] **🤖 Generative AI & Vector Insight Features**:
  - gRPC reader querying Core → vector embeddings with `pgvector` → LLM health insights, trend anomaly alerts, and cross-metric correlation analysis.
- [ ] **🤝 Cross-Tenant Data Sharing**:
  - UI & API for managing `tenant_shares` consent grants with friends, family, or health coaches.
- [ ] **🔀 Smart Duplicate & Cross-Source Conflict Resolution**:
  - Core Service fuzzy duplicate detector for cross-source metrics (e.g. Yazio vs. Apple Health).
  - Dashboard UI "Conflict Resolver" modal for user approval/rejection of ambiguous duplicate entries.

---

## 🔵 Phase 7: Adaptive Ingestion, Importer Reliability & Authentication (Planned)

- [ ] **Adaptive Import Windows & Gap Backfill**: derive connector-specific overlap windows, detect missing data, and recommend exact tenant-scoped backfill periods in the data UI.
- [ ] **Smart Time-Range Duplicate Detection**: use coarse blocks and interval/binary search by default, with safe fallback for non-contiguous duplicates and a user-confirmed Force Import mode.
- [ ] **Importer Audit & Integration Coverage**: review every importer, including credentials, API/feed semantics, pagination, rate limits, time zones, incremental sync, retries, NATS, Gateway/Core, Docker and health checks.
- [ ] **Calendar ICS Correctness**: valid Outlook/Office ICS URLs must not require an unrelated API key; distinguish public/private ICS feeds from OAuth/API integrations.
- [ ] **Importer Tests**: add self-contained unit, integration and end-to-end coverage using Docker-backed test services where appropriate.
- [ ] **Tenant-Bound Authentication**: map bearer tokens and generated inbound API keys to exactly one tenant using only `Authorization: Bearer <token>`; hash, rotate, revoke and least-privilege keys.
- [ ] **Logout & OIDC**: invalidate all session material on logout and add Google plus generic OIDC using Authorization Code + PKCE, state/nonce validation and safe account linking.
- [ ] **Analysis Dashboard Expansion**: organize correlations, trends, anomalies, data quality, period comparisons, routines and baselines with interactive, statistically cautious visualizations.
- [ ] **Vector-First Geodata UI**: make vectors the default, lazy-load optional map providers, evaluate free alternatives, and always provide a vector fallback.

## 🔵 Phase 8: Documentation & Legal Pages (Planned)

- [ ] **Hosted MkDocs Material Documentation**: build and host a standalone `squidfunk/mkdocs-material` site with navigation, search, mobile layout, CI build and link validation.
- [ ] Document architecture, data flows, analyses, importers, data gaps, Smart/Force import, APIs, operations, security, limitations and troubleshooting.
- [ ] Add contextual links from dashboard, import configuration, gap detection, duplicate detection, settings, login, registration and footer.
- [ ] **German Privacy Policy & Imprint**: add plain, responsive text pages without cards or decorative UI; use realistic implementation-based templates, explicit placeholders, and a legal-review warning.

## 🔵 Phase 9: Verification & Governance (Required)

- [ ] Use Sub-Agents for independent importer, integration, test and documentation reviews when available; critically validate their results.
- [ ] Verify Core-only database ownership, gRPC Analysis access, NATS importer flow, tenant filters, idempotency, `X-Request-ID`, secret handling and no shared mutable state.
- [ ] Update Fizzbee specifications and invariant-referencing test docstrings for new distributed behavior.
- [ ] Run linting, type checking, unit/integration/E2E tests and the MkDocs build; record unavailable external services, failures, risks and follow-up work.
