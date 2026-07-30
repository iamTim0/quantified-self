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
        YazioAPI[Yazio API v15]
    end

    subgraph Platform
        Gateway[API Gateway\nFastAPI]
        Core[Core Data Service\nFastAPI]
        Analysis[Analysis Service\nFastAPI]
        YazioImporter[Yazio Importer\nPython Stateless Worker]
        
        NATS[(NATS JetStream)]
        DB[(PostgreSQL\n+ TimescaleDB + pgvector)]
    end

    Client -->|HTTP/JWT| Gateway
    Gateway -->|HTTP/REST| Core
    Gateway -->|HTTP/REST| Analysis
    
    YazioImporter -->|Poll v15| YazioAPI
    YazioImporter -->|Publish Event| NATS
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
| **Yazio Importer** | Container | Polls Yazio API v15 for meals, products & daily macros | NATS publisher (`qs.ingest.yazio`) |

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
├── apps/
│   └── dashboard/         # Next.js 16 Web Dashboard UI
├── services/
│   ├── api-gateway/       # Auth, routing, JWT
│   ├── core/              # Owns PostgreSQL, NATS consumer, gRPC server
│   ├── analysis/          # AI/DS, queries Core via gRPC
│   └── importers/
│       └── yazio/         # NATS publisher, polls Yazio API v15
├── packages/
│   ├── proto/             # Protobuf definitions (buf)
│   └── shared-schemas/    # Shared Pydantic models
├── specs/                 # Fizzbee formal specifications
├── infra/                 # Infrastructure configuration
│   ├── docker-compose.yml
│   └── db/init.sql
├── Taskfile.yml
├── README.md
└── AGENTS.md
```

## Getting Started

### Prerequisites
- Docker & Docker Compose
- `uv` (Python dependency manager)
- Taskfile (`go-task`)
- Node.js 22 & pnpm 9+

### Clone & Setup
```bash
git clone https://github.com/iamTim0/quantified-self.git
cd quantified-self
task setup
```

### Start Infrastructure & Microservices
Start all backing services and microservices using Docker Compose:
```bash
docker compose -f infra/docker-compose.yml up -d
```

### Run Services Locally
You can run individual services locally using Taskfile commands:
```bash
task run:core
task run:gateway
task run:importer:yazio
task dashboard
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
- `tenants`: Core multi-tenancy workspace entity.
- `users`: Individual user accounts with roles and hashed credentials.
- `data_sources`: Registered integrations (e.g., user's Yazio connector).
- `data_points`: TimescaleDB hypertable containing actual metrics.
- `tenant_shares`: Explicit consent grants for cross-tenant data sharing.

### Deduplication Strategy
Deduplication happens at the database level using a 64-character SHA256 `idempotency_key`:
$$\text{SHA256}(\text{tenant\_id} + ":" + \text{source\_id} + ":" + \text{metric\_type} + ":" + \text{timestamp})$$
The core service executes `INSERT INTO data_points ... ON CONFLICT (tenant_id, idempotency_key, timestamp) DO NOTHING`.

## Multi-Tenancy & Data Sharing

### Tenant Isolation
The platform employs **application-level filtering**. Every database query in the Core service MUST explicitly filter by `tenant_id`. The API Gateway extracts the `tenant_id` from the JWT and passes it downstream (`X-Tenant-ID`).

### Data Sharing
Cross-tenant sharing uses an explicit consent model via the `tenant_shares` table.

## Adding a New Importer

API importers are stateless workers fetching data and pushing it into NATS JetStream.

1. **Create Directory**: Make `services/importers/<name>/`
2. **Template**: Copy structure from `services/importers/yazio/`.
3. **Client**: Implement `client.py` to handle external API pagination, rate limits, and auth.
4. **Transformer**: Implement `transformer.py` to map external JSON to standard platform `DataPoint` records.
5. **NATS Subject**: Configure publishing to `qs.ingest.<name>`.
6. **Docker**: Add the service to `infra/docker-compose.yml`.
7. **Tests**: Add unit and integration tests.

## Fizzbee (Formal Verification)

We use **Fizzbee** to mathematically model and verify our distributed architecture patterns before writing code. Specifications live in `specs/`.
