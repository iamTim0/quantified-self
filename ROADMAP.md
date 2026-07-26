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

## 🟢 Phase 1: Real Oura Importer (ETL Pipeline) (COMPLETED)

- [x] **Formal Verification**: Fizzbee specification (`specs/importer_oura.fizz`) modeling polling, 429 rate limit backoff, 401 token refresh, and SHA256 idempotency key generation.
- [x] **Oura Client Integration** (`services/importers/oura/src/oura_importer/client.py`):
  - Oura API v2 client for `/v2/usercollection/daily_sleep`, `/v2/usercollection/daily_activity`, and `/v2/usercollection/daily_readiness`.
  - Rate-limit handling (HTTP 429 backoff) & token error handling (HTTP 401).
- [x] **Data Transformer** (`services/importers/oura/src/oura_importer/transformer.py`):
  - Transforms Oura JSON into standard `DataPoint` records with 64-char SHA256 `idempotency_key`.
- [x] **Scheduler & Ingestion Loop** (`services/importers/oura/src/oura_importer/main.py`):
  - APScheduler cron job polling Oura API and publishing events to NATS subject `qs.ingest.oura`.
- [x] **Mock Data Seed Generator** (`services/importers/oura/src/oura_importer/seed.py`):
  - Generated 30 days of realistic time-series metric data (310 data points ingested into TimescaleDB).

---

## 🟢 Phase 2: Core Data Service Query APIs (COMPLETED)

- [x] **Formal Verification**: Fizzbee specification (`specs/core_query.fizz`) modeling multi-tenant read query isolation and consent checking.
- [x] **REST Data Query Endpoints** (`services/core/src/core/main.py`):
  - `GET /api/v1/data/metrics`: Query time-series data points with filters (`metric_type`, `start_time`, `end_time`, `limit`).
  - `GET /api/v1/data/metrics/types`: List all distinct metric types stored for a tenant.
  - `GET /api/v1/data/metrics/summary`: Summary statistics (count, average, min, max, latest timestamp) for all metric types.
- [x] **Integration Test Suite**: 9 passing integration & context isolation tests (`services/core/tests/test_query_endpoints.py`).

---

## 🟡 Phase 3: Auth & Gateway Proxy (NEXT)

- [ ] **JWT Auth & Header Injection** (`services/api-gateway/src/gateway/auth.py`)
  - Validate JWT, extract `tenant_id` claim, inject `X-Tenant-ID` header.
- [ ] **Dev Token Generator**
  - Utility endpoint / CLI to generate dev JWT tokens for test tenants.
- [ ] **Gateway Routing** (`services/api-gateway/src/gateway/main.py`)
  - Reverse proxy `/api/v1/data/*` to Core Data Service (`http://localhost:8001`).
  - Reverse proxy `/api/v1/analysis/*` to Analysis Service.

---

## 🟡 Phase 4: Basic User Dashboard (Web UI)

- [ ] **Web Dashboard UI** (`apps/dashboard/` or `services/dashboard/`)
  - Modern, responsive dashboard web interface.
  - **Summary Metrics Cards**: Sleep Score, Readiness Score, HRV, Daily Steps.
  - **Interactive Time-Series Charts**: Visualizing trends over days/weeks/months.
  - **Data Source Status Widget**: Shows Oura connection status, last sync timestamp, and manual sync trigger.

---

## 🔵 Phase 5: Future Milestones (Post-MVP)

- [ ] **Analysis Service AI Features**: gRPC reader querying Core → vector embeddings with pgvector → LLM health insights & correlation analysis.
- [ ] **Cross-Tenant Data Sharing**: UI & API for managing `tenant_shares` consent grants with friends/partner.
- [ ] **Additional Importers**: Whoop, Apple Health, Garmin, Strava ETL services.
