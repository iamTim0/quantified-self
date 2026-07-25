# 🗺️ Quantified Self Platform — Project Roadmap

**Current Goal**: Milestone 1 — First Working Importer (Oura Ring) + Basic User Dashboard.

---

## 🟢 Phase 0: Architecture & Foundation (COMPLETED)

- [x] **Monorepo Architecture**: Independent microservices (`api-gateway`, `core`, `analysis`, `importers/oura`).
- [x] **Database & Storage**: PostgreSQL 16 + TimescaleDB hypertable (`data_points`) + `pgvector` embeddings + JSONB metadata.
- [x] **Infrastructure**: Docker Compose (`postgres:5433`, `nats:4222` JetStream), Taskfile, `uv` package management.
- [x] **Tenant Isolation**: Async-safe `contextvars` tenant context middleware enforcing `WHERE tenant_id = :tid`.
- [x] **Event-Driven Ingestion**: NATS JetStream consumer in Core service with exact-once deduplication via `idempotency_key`.
- [x] **Protobuf & gRPC Setup**: Code generation script (`packages/proto/generate.py`) for Python stubs.
- [x] **Formal Verification**: Fizzbee specifications (`specs/distributed_ingestion.fizz`, `specs/tenant_isolation.fizz`) + 14 passing invariant and integration tests.
- [x] **Alembic Migrations**: Setup with mandatory `downgrade()` rollback functions (`alembic/versions/001_initial_schema.py`).
- [x] **Licensing & Initial Commit**: PolyForm Noncommercial License 1.0.0 & git initial commit.

---

## 🟡 Phase 1: Real Oura Importer (ETL Pipeline)

- [ ] **Oura Client Integration** (`services/importers/oura/src/oura_importer/client.py`)
  - Implement Oura API v2 client for `/v2/usercollection/daily_sleep`, `/v2/usercollection/daily_activity`, and `/v2/usercollection/daily_readiness`.
  - Rate-limit handling & exponential backoff retry.
- [ ] **Token & Credentials Management**
  - Store Oura Access Tokens mapped to `tenant_id` and `source_id`.
- [ ] **Scheduler & Ingestion Loop** (`services/importers/oura/src/oura_importer/main.py`)
  - APScheduler cron job polling Oura API every N minutes.
  - Transform API JSON → standard `DataPoint` + SHA256 `idempotency_key` → publish to `qs.ingest.oura`.
- [ ] **Mock / Sandbox Data Seed Generator**
  - Script to generate realistic dummy Oura sleep & activity time-series data for dev testing.

---

## 🟡 Phase 2: Core Data Service Query APIs

- [ ] **REST Data Query Endpoint** (`services/core/src/core/main.py`)
  - `GET /api/v1/data/metrics`: Query time-series metrics with filters (`tenant_id`, `metric_type`, `start_time`, `end_time`, `page`).
  - `GET /api/v1/data/metrics/types`: List all available metric types for a tenant.
- [ ] **gRPC Core Server Implementation** (`services/core/src/core/grpc/server.py`)
  - Serves `QueryDataPoints`, `GetDataPoint`, and `ListMetricTypes` RPCs.

---

## 🟡 Phase 3: Auth & Gateway Proxy

- [ ] **JWT Auth & Header Injection** (`services/api-gateway/src/gateway/auth.py`)
  - Validate JWT, extract `tenant_id` claim, inject `X-Tenant-ID` header.
- [ ] **Dev Token Generator**
  - Utility endpoint / CLI to generate dev JWT tokens for test tenants.
- [ ] **Gateway Routing** (`services/api-gateway/src/gateway/main.py`)
  - Reverse proxy `/api/v1/data/*` to Core Data Service.
  - Reverse proxy `/api/v1/analysis/*` to Analysis Service.

---

## 🟡 Phase 4: Basic User Dashboard (Web UI)

- [ ] **Web Dashboard UI** (`apps/dashboard/` or `services/dashboard/`)
  - Modern, responsive dashboard web interface.
  - **Summary Metrics Cards**: Sleep Score, Readiness Score, HRV, Daily Steps.
  - **Interactive Time-Series Charts**: Visualizing trends over days/weeks/months (Chart.js / Recharts).
  - **Data Source Status Widget**: Shows Oura connection status, last sync timestamp, and manual sync trigger.

---

## 🔵 Phase 5: Future Milestones (Post-MVP)

- [ ] **Analysis Service AI Features**: gRPC reader querying Core → vector embeddings with pgvector → LLM health insights & correlation analysis.
- [ ] **Cross-Tenant Data Sharing**: UI & API for managing `tenant_shares` consent grants with friends/partner.
- [ ] **Additional Importers**: Whoop, Apple Health, Garmin, Strava ETL services.
