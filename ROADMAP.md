# 🗺️ Quantified Self Platform — Project Roadmap

**Current Status**: **MILESTONE 1 COMPLETED** 🎉 (First Working Importer + Basic User Dashboard).

---

## 🟢 Phase 0: Architecture & Foundation (COMPLETED)

- [x] **Monorepo Architecture**: Independent microservices (`api-gateway`, `core`, `analysis`, `importers/yazio`).
- [x] **Database & Storage**: PostgreSQL 16 + TimescaleDB hypertable (`data_points`) + `pgvector` embeddings + JSONB metadata.
- [x] **Infrastructure**: Docker Compose (`postgres:5433`, `nats:4222` JetStream), Taskfile, `uv` package management.
- [x] **Tenant Isolation**: Async-safe `contextvars` tenant context middleware enforcing `WHERE tenant_id = :tid`.
- [x] **Event-Driven Ingestion**: NATS JetStream consumer in Core service with exact-once deduplication via `idempotency_key`.
- [x] **Protobuf & gRPC Setup**: Code generation script (`packages/proto/generate.py`) for Python stubs.
- [x] **Formal Verification**: Fizzbee specifications (`specs/distributed_ingestion.fizz`, `specs/tenant_isolation.fizz`) + 14 passing invariant and integration tests.
- [x] **Alembic Migrations**: Setup with mandatory `downgrade()` rollback functions (`alembic/versions/001_initial_schema.py`).
- [x] **Licensing & Initial Commit**: PolyForm Noncommercial License 1.0.0 & git initial commit.

---

## 🟢 Phase 1: Real Yazio Importer (ETL Pipeline) (COMPLETED)

- [x] **Yazio Client Integration** (`services/importers/yazio/src/yazio_importer/client.py`):
  - Yazio API v15 client for `/v15/user/consumed-items`.
  - OAuth2 password grant token exchange & refresh, rate-limit backoff (HTTP 429), and HTTP 401 handling.
- [x] **Data Transformer** (`services/importers/yazio/src/yazio_importer/transformer.py`):
  - Transforms Yazio JSON consumed items into standard `DataPoint` records with 64-char SHA256 `idempotency_key`.
- [x] **Ingestion Loop** (`services/importers/yazio/src/yazio_importer/main.py`):
  - NATS JetStream consumer on `qs.task.sync.yazio` publishing ingested events to NATS subject `qs.ingest.yazio`.

---

## 🟢 Phase 2: Core Data Service Query APIs (COMPLETED)

- [x] **Formal Verification**: Fizzbee specification (`specs/core_query.fizz`) modeling multi-tenant read query isolation and consent checking.
- [x] **REST Data Query Endpoints** (`services/core/src/core/main.py`):
  - `GET /api/v1/data/metrics`: Query time-series data points with filters (`metric_type`, `start_time`, `end_time`, `limit`).
  - `GET /api/v1/data/metrics/types`: List all distinct metric types stored for a tenant.
  - `GET /api/v1/data/metrics/summary`: Summary statistics (count, average, min, max, latest timestamp) for all metric types.
- [x] **Integration Test Suite**: 9 passing integration & context isolation tests (`services/core/tests/test_query_endpoints.py`).

---

## 🟢 Phase 3: Auth & Gateway Proxy (COMPLETED)

- [x] **Formal Verification**: Fizzbee specification (`specs/auth_gateway.fizz`) modeling JWT validation & header injection.
- [x] **JWT Auth & Header Injection** (`services/api-gateway/src/gateway/auth.py`):
  - Validate JWT, extract `tenant_id` claim, inject `X-Tenant-ID` header.
- [x] **Dev Token Generator** (`/api/v1/auth/dev-token`):
  - Utility endpoint / CLI to generate dev JWT tokens for test tenants.
- [x] **Gateway Routing** (`services/api-gateway/src/gateway/main.py`):
  - Reverse proxy `/api/v1/data/*` to Core Data Service (`http://127.0.0.1:8001`).

---

## 🟢 Phase 4: Basic User Dashboard (Web UI) (COMPLETED)

- [x] **Web Dashboard UI** (`apps/dashboard/index.html`):
  - Modern, glassmorphism web interface with dark mode aesthetic.
  - **Summary Metrics Cards**: Sleep Score (84.2), Readiness Score (80.4), HRV Balance (62.3 ms), Daily Steps (8,994).
  - **Interactive Time-Series Charts**: Sleep & Readiness trends over 30 days using Chart.js.
  - **Data Source Status Widget**: Oura connection status, last sync timestamp, and manual sync trigger button.
  - **Task command**: `task dashboard` serves UI on `http://localhost:3000`.

---

## 🔵 Phase 5: Future Milestones (Post-MVP)

- [ ] **Analysis Service AI Features**: gRPC reader querying Core → vector embeddings with pgvector → LLM health insights & correlation analysis.
- [ ] **Cross-Tenant Data Sharing**: UI & API for managing `tenant_shares` consent grants with friends/partner.
- [ ] **Smart Duplicate & Cross-Source Conflict Resolution**:
  - Core Service automatic exact-match hash filtering (`ON CONFLICT DO NOTHING`).
  - Core Service fuzzy duplicate detector for cross-source metrics (e.g. Yazio vs. Apple Health).
  - Dashboard UI "Conflict Resolver" modal for user approval/rejection of ambiguous duplicates with similarity scoring.
- [ ] **Additional Importers**: Whoop, Apple Health, Garmin, Strava ETL services.
