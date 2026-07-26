# 🤝 Agent Handoff Document — Quantified Self Platform

**Date**: 2026-07-26  
**Repository**: Quantified Self Platform (`iamTim0/quantified-self`)  
**Current Branch**: `main`  
**Latest Commit**: `66d7727` (`security: fix 5 CRITICAL, 6 HIGH, 5 MEDIUM, 3 LOW findings...`)

---

## 1. 🎯 Current Project Status & Executive Summary

The **Quantified Self Platform** is a multi-tenant, microservice-based personal health analytics platform built with Python (FastAPI, SQLAlchemy 2.0, TimescaleDB, pgvector), NATS JetStream, gRPC, and Next.js 15 App Router.

### Completed Milestones:
- **Phase 1: Real Oura Importer & Mock Seed Generator**:
  - Implemented Oura Ring v2 ETL importer (`services/importers/oura`) and 30-day mock seed data generator (`seed.py`).
  - Successfully published and ingested **310+ metric data points** into TimescaleDB via NATS JetStream.
- **Phase 2: Core Data Service REST Query APIs**:
  - `GET /api/v1/data/metrics` (time-series filtering with `metric_type`, `start_time`, `end_time`, `limit`).
  - `GET /api/v1/data/metrics/types` (distinct metric listing).
  - `GET /api/v1/data/metrics/summary` (aggregated averages, min, max, count, latest timestamp).
- **Phase 3: Auth & API Gateway Proxy**:
  - HTTP reverse proxy (`services/api-gateway`) with PyJWT validation, `X-Tenant-ID` header injection, and dev token generator `/api/v1/auth/dev-token`.
- **Phase 4: Encrypted Connector Secrets Management**:
  - Fernet AES-256 symmetric encryption at rest for API keys (`services/core/src/core/security/crypto.py`).
  - `POST /api/v1/data/sources/configure` (encrypts tokens) and `GET /api/v1/data/sources` (returns masked tokens `••••••••a1b2`).
- **Phase 5: Next.js 15 App Router Dashboard (`apps/dashboard`)**:
  - Full modern React 19 / Next.js 15 App Router frontend with Chart.js time-series graphs, live metric cards, and connector configuration modal.
- **Phase 6: Full Security Audit & Hardening**:
  - Fixed 5 CRITICAL, 6 HIGH, 5 MEDIUM, and 3 LOW findings (CORS, header whitelisting, ephemeral dev key fallback, Next.js CSP headers, env template).
- **Phase 7: Full Authentication & Cross-Tenant Data Sharing**:
  - Implemented DB Alembic Migration (`002_add_auth_fields`) for user authentication (`email`, `password_hash`).
  - Added REST Endpoints: `/api/v1/auth/signup`, `/api/v1/auth/login`, and sharing endpoints `/api/v1/data/shares` (`POST`, `GET`, `DELETE`).
  - Enforced authorization/consent grants in metric querying (`GET /api/v1/data/metrics?target_tenant_id=...`).
  - Built out Next.js Dashboard UI for Auth (`AuthScreen.tsx`) & Consent Grant Management (`ShareModal.tsx`).

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
| **Oura Importer** | `services/importers/oura` | Background ETL | Polls Oura API -> Publishes to NATS |
| **Dashboard** | `apps/dashboard` | `3000` (HTTP) | Next.js 15 App Router + Tailwind CSS |

---

## 3. 🚨 Absolute Rules & Architectural Invariants

Agents working on this repository MUST obey these non-negotiable invariants:

1. **Database Ownership**: Only `services/core/` can connect to or query PostgreSQL. No other service may import SQLAlchemy or asyncpg.
2. **Tenant Isolation**: Every database query MUST filter by `tenant_id`. Every API request MUST have `X-Tenant-ID` injected.
3. **Idempotency**: All ingestion events require deterministic `idempotency_key` = `SHA256(tenant_id + source_id + metric_type + timestamp)`.
4. **Inter-service Communication**: Importers publish to NATS (`qs.ingest.<source>`); Analysis queries Core via gRPC.
5. **Strict Workflow Order**: Every feature MUST follow `fizzbee spec` -> `invariant tests in specs/tests/` -> `production implementation`.
6. **Lint & Typecheck Mandate**: Always run `uv run --with ruff ruff check services/ specs/`, `npx tsc --noEmit` (in `apps/dashboard`), and `npm run lint` (in `apps/dashboard`) before completing work.

---

## 4. 🧪 Test & Verification Commands

All test suites are passing (34/34 total tests):

```bash
# 1. Run Fizzbee Invariant Tests (20 tests)
uv run --with pytest --with cryptography pytest specs/tests -v

# 2. Run Core Service Integration & API Tests (10 tests)
uv run --directory services/core --with pytest --with pytest-asyncio --with httpx --with cryptography python -m pytest tests -v

# 3. Run API Gateway Tests (4 tests)
uv run --directory services/api-gateway --with pytest --with pytest-asyncio --with httpx --with pyjwt python -m pytest tests -v

# 4. Run Next.js Dashboard Typecheck & Linter
cd apps/dashboard
npx tsc --noEmit
npm run lint

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
3. **User Authentication Flow**:
   - Replace dev JWT token generator with full user login/signup or OAuth2 flow.

---

## 🔑 Environment Configuration
Use [.env.example](file:///C:/Users/thoff/Documents/GitHub/quantified-self/.env.example) to configure environment variables. Never commit `.env` files with production secrets.
