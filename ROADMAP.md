# 🗺️ Quantified Self Platform — Project Roadmap

**Current Status**: **MILESTONE 5 COMPLETED** 🎉 (Production Microservices + Yazio ETL Importer + Dawarich GPS Importer + Universal Data Explorer & Saved Views + Next.js Dashboard).

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
- [x] **Saved Views ("Gespeicherte Ansichten")**:
  - Preset views (e.g. *"🍏 Yazio Makronährstoffe"*, *"🔥 Kalorien & Produkte"*, *"🌙 Schlaf & Regeneration"*).
  - 1-click custom view saving, loading, and deletion persisted in `localStorage` & backend database.

---

## 🔵 Phase 5: Planned Importers & Integrations (Upcoming)

- [ ] **🏋️ Streak / Gym Log App Importer**:
  - Importer service for Streak gym logging app to record workout sessions, sets, reps, weight lifted, and exercise progression history.
- [ ] **🏠 Home Assistant Importer**:
  - Importer service integrating with Home Assistant API to collect smart home environmental metrics (bedroom temperature, humidity, noise levels, light exposure) for sleep & recovery correlation.
- [ ] **⛅ Wetter Importer (Weather Data)**:
  - Open-Meteo / Weather API importer bringing historical and real-time local weather metrics (temperature, barometric pressure, precipitation, UV index) to correlate weather patterns with mood, HRV, and physical performance.
- [ ] **📅 Kalender Importer (Calendar Data)**:
  - iCal / Google Calendar / Outlook integration importing daily schedules, meeting durations, and busy hours to analyze cognitive stress, routine consistency, and sleep impact.
- [ ] **⌚ Additional Health Wearables**:
  - Whoop, Apple Health, Garmin, Strava, and Oura ETL microservices.

---

## 🔵 Phase 6: Core Data Platform & UI Features (Upcoming)

- [ ] **🔍 Datenlücken-Erkennung (Data Gap Detection)**:
  - Intelligent engine in Core / Analysis service detecting missing tracking days or timeline gaps across all connected sources.
  - Highlights data gaps visually in the Dashboard UI with 1-click backfill and manual entry triggers.
- [ ] **📁 Universal CSV & DB Importer mit Visuellem Editor**:
  - Generic CSV & SQL/SQLite export importer featuring a drag-and-drop web upload interface.
  - **Visual Column Mapper & Data Editor**: Interactive UI allowing users to map arbitrary CSV columns to Quantified Self metrics, preview data tables, correct missing values or formatting errors visually, and execute batch imports.
- [ ] **🤖 Analysis Service AI & Insight Features**:
  - gRPC reader querying Core → vector embeddings with `pgvector` → LLM health insights, trend anomaly alerts, and cross-metric correlation analysis.
- [ ] **🤝 Cross-Tenant Data Sharing**:
  - UI & API for managing `tenant_shares` consent grants with friends, family, or health coaches.
- [ ] **🔀 Smart Duplicate & Cross-Source Conflict Resolution**:
  - Core Service fuzzy duplicate detector for cross-source metrics (e.g. Yazio vs. Apple Health).
  - Dashboard UI "Conflict Resolver" modal for user approval/rejection of ambiguous duplicate entries.
