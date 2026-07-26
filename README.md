# 🔬 Quantified Self Platform

A SaaS-ready, microservice-based personal data analytics platform.

![CI](https://img.shields.io/badge/CI-Passing-success)
![License](https://img.shields.io/badge/License-PolyForm_Noncommercial_1.0.0-red)
![Python Version](https://img.shields.io/badge/Python-3.12%2B-blue)

## Architecture Overview

The Quantified Self Platform uses a microservice architecture built for scale, isolation, and robustness. It separates data ingestion, storage, and analysis into distinct services that communicate asynchronously or via strict RPC contracts.

```mermaid
flowchart TD
    subgraph External
        Client[User / Client App]
        OuraExport[Oura CSV export]
    end

    subgraph Platform
        Gateway[API Gateway\nFastAPI]
        Core[Core Data Service\nFastAPI]
        Analysis[Analysis Service\nFastAPI]
        
        NATS[(NATS JetStream)]
        DB[(PostgreSQL\n+ TimescaleDB + pgvector)]
    end

    Client -->|HTTP/JWT| Gateway
    Gateway -->|HTTP/REST| Core
    Gateway -->|HTTP/REST| Analysis
    
    OuraExport -->|CSV upload| Gateway
    NATS -->|Consume Event| Core
    Core -->|SQL| DB
    
    Analysis -->|gRPC| Core
```

### Services

| Service | Port | Purpose | Communication |
| --- | --- | --- | --- |
| **API Gateway** | 8000 | Auth, routing, JWT validation, injects tenant context | HTTP (REST) in/out |
| **Core** | 8001 | Owns DB. Consumes ingestion events. Serves gRPC queries | NATS (in), gRPC (out), PostgreSQL |
| **Analysis** | 8002 | AI/Data Science, complex queries, embeddings | gRPC (to Core), HTTP (from Gateway) |
| **Oura CSV import** | Dashboard | Imports a user-provided Oura CSV export | HTTP via Gateway to Core |

## Tech Stack

| Category | Technology | Purpose |
| --- | --- | --- |
| **Backend Framework** | Python 3.12+, FastAPI | High-performance async APIs |
| **Database** | PostgreSQL 16, TimescaleDB, pgvector | Time-series data, vector embeddings, relational data |
| **ORM & DB Drivers** | SQLAlchemy 2.0, asyncpg | Async database access |
| **Message Broker** | NATS JetStream | Asynchronous, durable data ingestion |
| **RPC & Serialization**| gRPC, Protobuf (`buf`) | Fast, typed internal communication |
| **Dependency Mgmt** | `uv` | Fast Python package management |
| **Orchestration** | Docker Compose | Local development and testing |
| **Task Runner** | Taskfile | Cross-language script execution |
| **Formal Verification**| Fizzbee | Designing and verifying distributed systems |

## Project Structure

```text
quantified-self/
├── services/
│   ├── api-gateway/       # Auth, routing, JWT
│   ├── core/              # Owns PostgreSQL, NATS consumer, gRPC server
│   ├── analysis/          # AI/DS, queries Core via gRPC
│   └── importers/
│       └── oura/          # NATS publisher, polls Oura API
├── packages/
│   ├── proto/             # Protobuf definitions (buf)
│   └── shared-schemas/    # Shared Pydantic models
├── specs/                 # Fizzbee formal specifications
├── infra/                 # Infrastructure configuration
│   ├── docker-compose.yml
│   └── db/init.sql
├── Taskfile.yml
├── README.md
└── agents.md
```

## Getting Started

### Prerequisites
- Docker & Docker Compose
- `uv` (Python dependency manager)
- Taskfile (`go-task`)
- `buf` (Protobuf compiler)

### Clone & Setup
```bash
git clone https://github.com/iamTim0/quantified-self.git
cd quantified-self
task setup
```

### Start Infrastructure
Start the database and NATS:
```bash
task dev:up
```

### Run Services
You can run individual services using Taskfile commands:
```bash
task run:core
task run:gateway
task run:importer:oura
```

### Environment Variables

| Variable | Description | Example |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://user:pass@localhost:5432/qs` |
| `NATS_URL` | NATS JetStream URL | `nats://localhost:4222` |
| `JWT_SECRET` | Secret for signing JWTs | `supersecret` |

## Database Schema

The database utilizes PostgreSQL extended with **TimescaleDB** for hypertable-based time-series data storage and **pgvector** for AI embeddings. Additional flexibility is provided via JSONB metadata columns.

### Key Tables
- `tenants`: Core multi-tenancy entity.
- `data_sources`: Registered integrations (e.g., specific user's Oura ring).
- `data_points`: TimescaleDB hypertable containing actual metrics.
- `tenant_shares`: Explicit consent grants for cross-tenant data sharing.

### Deduplication Strategy
Deduplication happens at the database level using an `idempotency_key` (a unique constraint). The core service performs an `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING`.

## Multi-Tenancy & Data Sharing

### Tenant Isolation
The platform employs **application-level filtering**. There is no Row-Level Security (RLS). Every database query in the Core service MUST explicitly filter by `tenant_id`. The API Gateway extracts the `tenant_id` from the JWT and passes it downstream (via HTTP headers or gRPC metadata).

### Data Sharing
Cross-tenant sharing uses an explicit consent model via the `tenant_shares` table. If Tenant A queries Tenant B's data, the application checks this table before fulfilling the request.

## Adding a New Importer

API importers are stateless workers fetching data and pushing it into the system. The only currently enabled user-facing import is the Oura CSV upload in the Dashboard; API/token connectors are not presented as available integrations.

1. **Create Directory**: Make `services/importers/<name>/`
2. **Template**: Copy the structure from the Oura importer template.
3. **Client**: Implement `client.py` to handle external API pagination, rate limits, and auth.
4. **Transformer**: Implement `transformer.py` to map external data to the standard platform `DataPoint`.
5. **NATS Subject**: Configure publishing to `qs.ingest.<name>`.
6. **Docker**: Add the service to `infra/docker-compose.yml`.
7. **Verify**: Write a Fizzbee spec for any novel data flows introduced.
8. **Tests**: Add unit and integration tests.

## Fizzbee (Formal Verification)

We use **Fizzbee** to mathematically model and verify our distributed architecture patterns before writing code.
- **Why**: To prevent race conditions, dropped messages, and complex distributed bugs.
- **Where**: Specifications live in `specs/`.
- **How**: Run `task spec:check` to verify invariants.

## Development

### Task Commands

| Command | Action |
| --- | --- |
| `task setup` | Install dependencies, tools |
| `task dev:up` | Start infra (DB, NATS) via Docker |
| `task proto:generate`| Compile protobuf files |
| `task test` | Run all test suites |
| `task lint` | Run ruff and mypy |

### Testing
- **Unit**: Pytest, mocking external APIs and DBs.
- **Integration**: Testing against actual local Docker services.
- **Fizzbee Mapping**: Tests must explicitly reference the Fizzbee invariants they are validating in their docstrings.

## License
[PolyForm Noncommercial License 1.0.0](LICENSE). Free for personal use, self-hosting, modification, and non-commercial sharing. Commercial use, monetization, or selling as a paid service is strictly prohibited.
