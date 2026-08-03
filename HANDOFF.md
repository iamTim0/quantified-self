# 🤝 Agent Handoff Document — Quantified Self Platform

**Date**: 2026-07-26  
**Repository**: Quantified Self Platform (`iamTim0/quantified-self`)  
**Current Branch**: `main`  

---

## 1. 🎯 Current Project Status & Executive Summary

The **Quantified Self Platform** is a multi-tenant, microservice-based personal health analytics platform built with Python (FastAPI, SQLAlchemy 2.0, TimescaleDB, pgvector), NATS JetStream, gRPC, and Next.js 15 App Router.

### Completed Milestones:
- **Phase 1: Real Yazio Importer**:
  - Implemented Yazio v15 ETL importer (`services/importers/yazio`) fetching food diary, calories, and macros.
  - Ingested metric data points into TimescaleDB via NATS JetStream.
- **Phase 2: Core Data Service REST Query APIs**:
  - `GET /api/v1/data/metrics` (time-series filtering), `GET /api/v1/data/metrics/types`, `GET /api/v1/data/metrics/summary`.
- **Phase 3: Auth & API Gateway Proxy**:
  - Reverse proxy (`services/api-gateway`) with PyJWT validation, `X-Tenant-ID` header injection, and dev token generator `/api/v1/auth/dev-token`.
- **Phase 4: Encrypted Connector Secrets Management**:
  - Fernet AES-256 symmetric encryption at rest for API keys (`services/core/src/core/security/crypto.py`) with `DEFAULT_DEV_KEY` fallback for unconfigured dev environments.
  - `POST /api/v1/data/sources/configure` (encrypts tokens) and `GET /api/v1/data/sources` (returns masked tokens `••••••••a1b2`).
- **Phase 5: User Auth, Tenant/User Separation & Data Sharing**:
  - **User & Tenant Separation (Alembic Migration `003_separate_users_and_tenants`)**: Created `users` table (`id`, `tenant_id`, `email`, `password_hash`, `name`, `role`). Updated ORM models in `services/core/src/core/db/models.py`.
  - **User Auth Endpoints**: `POST /api/v1/auth/signup` & `POST /api/v1/auth/login` in Core Service & Gateway with Argon2 / bcrypt password hashing. JWT claims contain `user_id`, `tenant_id`, `email`, `role`.
  - **Data Sharing APIs**: `POST /api/v1/data/shares` (grant read access to grantee email) & `GET /api/v1/data/shares` & `DELETE /api/v1/data/shares/{id}`.
  - **Frontend UI Components**: Updated `Header.tsx`, `AuthScreen.tsx`, `page.tsx` showing active User (name, email, role) and Workspace Tenant Name & ID.
- **Phase 6: End-to-End Request Correlation Tracing (`X-Request-ID`)**:
  - Implemented `RequestTracingMiddleware` and contextvar-based `CorrelationLogFilter` in API Gateway, Core Service, and Yazio Importer.
  - Propagates `X-Request-ID` across HTTP calls and log lines with `[req_id=...]` prefix for full system visibility.
- **Phase 7: Next.js 15 App Router Dashboard (`apps/dashboard`)**:
  - Full modern React 19 / Next.js 15 App Router frontend with Chart.js time-series graphs, live metric cards, connector modal, and sharing modal.
- **Phase 8: Security Audit, Documentation & Invariant Rules Synchronization**:
  - Fully synchronized [AGENTS.md](file:///C:/Users/thoff/Documents/GitHub/quantified-self/AGENTS.md), [HANDOFF.md](file:///C:/Users/thoff/Documents/GitHub/quantified-self/HANDOFF.md), and [GEMINI.md](file:///C:/Users/thoff/Documents/GitHub/quantified-self/GEMINI.md).
  - All 34 automated unit, integration, and Fizzbee spec tests passing.
- **Phase 9: Request-Driven Importers & Importer Standard**:
  - **Zero Background Polling**: Converted Yazio importer and defined platform blueprint for all future importers to run without periodic background polling loops.
  - **Asynchronous NATS Task Queue (`qs.task.sync.<source_type>`)**: Core publishes task events upon connector configuration (`POST /configure`) or on-demand sync triggers (`POST /{source_type}/sync`).
  - **In-Flight Lock**: Importers maintain an in-memory lock per `tenant_id` to skip duplicate concurrent tasks.
  - **Custom Configuration Payload**: Importers dynamically retrieve decrypted access tokens + custom `config` dicts (`lookback_days`, categories) from Core Data Service DB on demand.
  - **Importer Standard Specification (`docs/importer-standard.md`)**: Formal architectural specification and developer contract for all platform importers. All 38 automated test suites passing cleanly.

---

## 2. 🏛 Architecture & Infrastructure

### Ports & Services Map:
| Service | Location | Port / Protocol | Details |
|---|---|---|---|
| **TimescaleDB** | `infra/docker-compose.yml` | `5433` (Host) -> `5432` (Container) | PostgreSQL 16 + TimescaleDB + pgvector |
| **NATS JetStream** | `infra/docker-compose.yml` | `4222` (Client), `127.0.0.1:8222` (Mon) | Stream: `ingestion`, Subject: `qs.ingest.>` |
| **API Gateway** | `services/api-gateway` | `8000` (HTTP) | Entry point, JWT auth, CORS, proxy |
| **Core Data Service** | `services/core` | `8001` (HTTP), `50051` (gRPC) | Owns DB & NATS consumer, multi-tenant |
| **Analysis Service** | `services/analysis` | `8002` (HTTP) | Data science & insights via gRPC to Core |
| **Yazio Importer** | `services/importers/yazio` | Background ETL | Tasks from NATS -> Fetches Yazio API -> Publishes to NATS |
| **Dashboard** | `apps/dashboard` | `3000` (HTTP) | Next.js 15 App Router + Tailwind CSS |

---

## 3. 🚨 Absolute Rules & Architectural Invariants

Agents working on this repository MUST obey these non-negotiable invariants:

1. **Database Ownership**: Only `services/core/` can connect to or query PostgreSQL. No other service may import SQLAlchemy or asyncpg.
2. **Tenant Isolation**: Every database query MUST filter by `tenant_id`. Every API request MUST have `X-Tenant-ID` injected.
3. **Tenant & User Separation**: Workspace (`tenants` table) is separated from User identity (`users` table). JWT claims contain `user_id`, `tenant_id`, `email`, and `role`.
4. **Stateless Importers & Connector Credentials**: Importers MUST NOT store access tokens in `.env` files. Importers query Core Data Service dynamically (`GET /api/v1/internal/data/sources/{source_type}/token`) for encrypted credentials configured by users via Dashboard UI. If no token exists, importers stay idle.
5. **Zero Plaintext Secrets in Broker or Logs**: Access tokens/secrets MUST NEVER be sent in plaintext over NATS Message Broker events or logged. All credentials are encrypted at rest via Fernet AES-256 (`ENCRYPTION_KEY`).
6. **End-to-End Correlation ID (`X-Request-ID`)**: Every HTTP request originating at Gateway MUST be tagged with a unique `X-Request-ID`. All downstream microservices MUST propagate `X-Request-ID` in HTTP headers, NATS events, and log outputs (`[req_id=...]`).
7. **Idempotency**: All ingestion events require deterministic `idempotency_key` = `SHA256(tenant_id + source_id + metric_type + timestamp)`.
8. **Inter-service Communication**: Importers publish to NATS (`qs.ingest.<source>`); Analysis queries Core via gRPC.
9. **Strict Workflow Order**: Every feature MUST follow `fizzbee spec` -> `invariant tests in specs/tests/` -> `production implementation`.
10. **NEVER Auto-Seed Data**: Microservices and importers MUST NEVER automatically generate mock seed data on startup or missing config.
11. **Stateless & Data-Independent Tests**: Tests MUST NEVER assume pre-existing database state or pre-seeded rows. Tests must be completely self-contained.
12. **Lint & Typecheck Mandate**: Always run `uv run --with ruff ruff check services/ specs/`, `npx tsc --noEmit` (in `apps/dashboard`), and `npx pnpm --prefix apps/dashboard lint` before completing work.

---

## 4. 🧪 Test & Verification Commands

All test suites are passing (34/34 total tests):

```bash
# 1. Run Fizzbee Invariant Tests (20 tests)
uv run --with pytest --with cryptography pytest specs/tests -v

# 2. Run Core Service Integration & API Tests (10 tests)
uv run --directory services/core --with pytest --with pytest-asyncio --with httpx --with cryptography --with passlib --with argon2-cffi --with pyjwt python -m pytest tests -v

# 3. Run API Gateway Tests (4 tests)
uv run --directory services/api-gateway --with pytest --with pytest-asyncio --with httpx --with pyjwt python -m pytest tests -v

# 4. Run Next.js Dashboard Typecheck & Linter
cd apps/dashboard
npx tsc --noEmit
pnpm lint

# 5. Run Python Linter
uv run --with ruff ruff check services/ specs/
```

---

## 5. 🚀 Next Steps / Roadmap Tasks

Refer to [ROADMAP.md](file:///C:/Users/thoff/Documents/GitHub/quantified-self/ROADMAP.md) for full details:

1. **Whoop 4.0 & Apple Health Importers**:
   - Create `services/importers/whoop` and `services/importers/apple_health`.
   - Write `.fizz` specifications in `specs/` first.
2. **Analysis Service gRPC Endpoints**:
   - Expand `services/analysis` with trend detection, anomaly detection algorithms, and gRPC client connection to Core.

---

## 🔑 Environment Configuration
Use [.env.example](file:///C:/Users/thoff/Documents/GitHub/quantified-self/.env.example) to configure environment variables. Never commit `.env` files with production secrets.
