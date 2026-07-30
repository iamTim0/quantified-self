# 🗺️ Quantified Self Platform — Project Roadmap

**Current Status**: **MILESTONE 5 COMPLETED** 🎉 (Production Microservices + Yazio ETL Importer + Universal Data Explorer & Saved Views + Next.js Dashboard).

---

## 🟢 Phase 0: Architecture & Foundation (COMPLETED)

- [x] **Monorepo Architecture**: Independent microservices (`api-gateway`, `core`, `analysis`, `importers/yazio`).
- [x] **Database & Storage**: PostgreSQL 16 + TimescaleDB hypertable (`data_points`) + `pgvector` embeddings + JSONB metadata.
- [x] **Infrastructure**: Docker Compose (`postgres:5433`, `nats:4222` JetStream), Taskfile, `uv` package management.
- [x] **Tenant Isolation**: Async-safe `contextvars` tenant context middleware enforcing `WHERE tenant_id = :tid`.
- [x] **Event-Driven Ingestion**: NATS JetStream consumer in Core service with exact-once deduplication via `idempotency_key`.
- [x] **Protobuf & gRPC Setup**: Code generation script (`packages/proto/generate.py`) for Python stubs.
- [x] **Formal Verification**: Fizzbee specifications (`specs/distributed_ingestion.fizz`, `specs/tenant_isolation.fizz`) + passing invariant and integration tests.
- [x] **Alembic Migrations**: Setup with mandatory `downgrade()` rollback functions (`alembic/versions/001_initial_schema.py`).

---

## 🟢 Phase 1: Real Yazio Importer & ETL Pipeline (COMPLETED)

- [x] **Yazio Client & API v15 Integration** (`services/importers/yazio/src/yazio_importer/client.py`):
  - Yazio API v15 client for `/v15/user/consumed-items`, `/v15/user/summary`, `/v15/products/{id}` and `/v15/recipes/{id}`.
  - Rate-limit backoff (HTTP 429), HTTP 401 handling, and Fernet AES-256 encrypted credential retrieval.
- [x] **Product Name & Nutrient Calculation Transformer** (`services/importers/yazio/src/yazio_importer/transformer.py`):
  - Resolves human-readable food names (`food_name`) for all products and recipes.
  - Computes exact calories and macro ratios (Protein, Carbs, Fat) per serving/gram and daily summary totals matching the Yazio App 1:1.
  - Generates 64-char SHA256 `idempotency_key` per data point.
- [x] **Ingestion Loop** (`services/importers/yazio/src/yazio_importer/main.py`):
  - NATS JetStream consumer on `qs.task.sync.yazio` publishing ingested events to NATS subject `qs.ingest.yazio`.

---

## 🟢 Phase 2: Per-User Sync Frequency & Connector Config (COMPLETED)

- [x] **Configurable Poll Frequency & Lookback**:
  - Core API (`POST /api/v1/data/sources/configure`) stores `poll_interval_hours` (1h, 3h, 6h, 12h, 24h, 168h) and `lookback_days` (7d, 14d, 30d, 60d, 90d).
  - Dynamic `last_sync_at` tracking returned on `GET /api/v1/data/sources`.
- [x] **Provider Catalog & 2-Step Modal Workflow**:
  - Step 1: Provider selection gallery (Yazio [Available], Whoop [Coming Soon], Apple Health [Coming Soon], Dawarich [Coming Soon]).
  - Step 2: Provider credential and sync schedule configuration form.

---

## 🟢 Phase 3: Next.js 16 Web Dashboard & Trend Visualizer (COMPLETED)

- [x] **Next.js 16 App Router UI** (`apps/dashboard`):
  - Sleek, glassmorphism dark-mode interface built with Tailwind CSS & Lucide icons.
  - **Summary Metrics Cards**: Calories, Protein, Carbs, Fat, Sleep Score, Readiness Score.
  - **Responsive Chart Overflow Protection**: ChartJS container with strict aspect ratio containment (`maintainAspectRatio: false`) and dynamic chart type switcher (Area, Line, Bar).
  - **Connected Sources Table**: Status badges, formatted last sync timestamps (*"Vor X Min"*), and poll frequency labels.

---

## 🟢 Phase 4: Universal Data Explorer & Saved Views System (COMPLETED)

- [x] **Universal Multi-Metric Query Engine**:
  - Full-text real-time search across food names, metric types, units, and raw metadata.
  - Multi-metric selection pills for side-by-side comparison on a unified timeline.
  - Aggregation modes: `SUM` (daily total calories/macros), `AVG` (daily average scores), `MAX` (daily peaks), `RAW`.
- [x] **Saved Views ("Gespeicherte Ansichten")**:
  - Preset views (e.g. *"🍏 Yazio Makronährstoffe"*, *"🔥 Kalorien & Produkte"*, *"🌙 Schlaf & Regeneration"*).
  - 1-click custom view saving, loading, and deletion persisted in `localStorage`.

---

## 🔵 Phase 5: Future Milestones (Post-MVP)

- [ ] **Additional Importers**: Whoop, Apple Health, Dawarich, Garmin, Strava ETL services.
- [ ] **Analysis Service AI Features**: gRPC reader querying Core → vector embeddings with pgvector → LLM health insights & correlation analysis.
- [ ] **Cross-Tenant Data Sharing**: UI & API for managing `tenant_shares` consent grants with friends/partner.
- [ ] **Smart Duplicate & Cross-Source Conflict Resolution**:
  - Core Service fuzzy duplicate detector for cross-source metrics (e.g. Yazio vs. Apple Health).
  - Dashboard UI "Conflict Resolver" modal for user approval/rejection of ambiguous duplicates.
