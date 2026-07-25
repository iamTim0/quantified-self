# System Prompt & Rules for AI Agents

## Project Identity

You are working on the **Quantified Self Platform**, a SaaS-ready, microservice-based personal data analytics platform.

**Architecture Summary**: This is a multi-tenant Python (FastAPI/asyncio) monorepo. It features strict separation of concerns: Importers poll external APIs and publish to NATS JetStream. A central Core service consumes these events and uniquely owns a PostgreSQL (TimescaleDB + pgvector) database. An Analysis service performs data science tasks, querying the Core service synchronously via gRPC. All services are deployed independently and share schema definitions via Protobuf and shared Pydantic packages.

---

## Absolute Rules (MUST FOLLOW)

These rules are non-negotiable. Breaking them will result in immediate rejection of code.

1. **Database Ownership**: Only `services/core/` may contain database connection code or SQL queries. No other service may import `SQLAlchemy`, `asyncpg`, or any database driver. The Analysis Service queries Core via gRPC ONLY. Importers do not talk to the database.
2. **Tenant Isolation**: Every database query MUST filter by `tenant_id` in the `WHERE` clause. Every NATS event MUST include a `tenant_id`. Every API endpoint MUST validate `tenant_id` from the authentication context. There are ZERO exceptions for multi-tenant data safety.
3. **Inter-Service Communication**: Importers communicate with Core EXCLUSIVELY via NATS JetStream (subject pattern: `qs.ingest.<source_type>`). Analysis communicates with Core EXCLUSIVELY via gRPC. Do not introduce direct HTTP calls between internal services for primary data flow.
4. **Idempotency**: Every data ingestion event MUST include an `idempotency_key`. The key must be a deterministic hash of `(tenant_id, source_id, metric_type, timestamp)`. Core MUST use `INSERT ... ON CONFLICT (tenant_id, idempotency_key) DO NOTHING` to guarantee exact-once storage semantics.
5. **Fizzbee First**: Before implementing any new distributed interaction pattern, a Fizzbee specification MUST be written in `specs/` and verified. Implementation tests MUST reference the specific Fizzbee invariant they verify in their docstrings.
6. **No Shared State**: Services do NOT share database connections, in-memory state, Redis instances, or file systems. Each service must be independently deployable.
7. **Schema Changes & Mandatory Rollbacks**: Database migrations go through `services/core/` exclusively using Alembic (`services/core/alembic/`). Every migration script MUST define both `upgrade()` AND a fully functional `downgrade()` (rollback) function. Empty or non-functional `downgrade()` functions are strictly forbidden. Protobuf contract changes go through `packages/proto/` using `generate.py`.

---

## Code Conventions

- **Python**: Version 3.12+. Use `async/await` heavily.
- **Typing**: Type hints are strictly required everywhere.
- **Validation**: Use Pydantic V2 for all data validation and parsing.
- **Dependencies**: Use `uv` for dependency management. Each service has its own isolated `pyproject.toml`.
- **Shared Code**: Code reused across services (like base models) lives in `packages/shared-schemas/`.
- **Protobuf**: Definitions live in `packages/proto/quantified_self/v1/`.

---

## Data Flow Patterns

- **Ingestion**: Importer -> NATS (`qs.ingest.<type>`) -> Core (Consumer) -> PostgreSQL DB.
- **Query**: External Client -> Gateway (JWT auth, header injection) -> Core (via gRPC from Analysis, or REST from Gateway) -> Client Response.
- **Sharing**: Access control via the `tenant_shares` table. Explicit grant/revoke required.

---

## Testing Requirements

- **Location**: Every service must have a dedicated `tests/` directory.
- **Unit Tests**: Use `pytest`. Mock all external dependencies (NATS, external APIs, gRPC clients).
- **Integration Tests**: Must use `docker compose` to spin up actual backing services (PostgreSQL, NATS) for tests.
- **Traceability**: Invariant mapping in test docstrings (e.g., `"""Verifies Fizzbee Invariant: NoDuplicateRecords"""`).

---

## When Adding a New Importer

If the user asks to add an integration for a new data source:

1. Create a new directory: `services/importers/<name>/`
2. Implement four core modules: `config.py`, `client.py`, `transformer.py`, `main.py`.
3. Configure the importer to publish to the NATS subject `qs.ingest.<name>`.
4. Ensure the `idempotency_key` is generated correctly in the transformer.
5. Add a `Dockerfile` for the new service and add it to `infra/docker-compose.yml`.
6. Write a Fizzbee spec extension ONLY IF new distributed patterns are introduced.
7. Add comprehensive test coverage.

---

## Anti-Patterns to Reject

If you see these patterns, you MUST fix them or refuse to write them:

- ❌ Direct database access from API Gateway, Analysis, or Importers.
- ❌ Missing `tenant_id` filters in `SELECT`, `UPDATE`, or `DELETE` statements.
- ❌ Synchronous HTTP calls from Importers to Core for data ingestion (MUST use NATS).
- ❌ Hardcoded tenant IDs in source code.
- ❌ Skipping Fizzbee specifications for new, complex distributed coordination.
- ❌ Sharing mutable state between microservices.
