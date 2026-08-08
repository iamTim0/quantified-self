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
8. **Stateless Importers & Connector Credentials**: Importers MUST NOT store access tokens in `.env` files or hardcoded configuration. Importers query Core Data Service dynamically (`GET /api/v1/internal/data/sources/{source_type}/token`) for encrypted credentials configured by users in the Dashboard UI. If no credentials exist, importers MUST remain idle without generating fake data.
9. **NEVER Auto-Seed Data**: Microservices and importers MUST NEVER automatically generate mock seed data on startup or missing configuration. Seed data generation must be executed explicitly via dedicated CLI commands (`python -m importer.seed`).
10. **Stateless & Independent Tests (No Assumed Data)**: Tests MUST NEVER assume pre-existing database state, pre-seeded rows, or dirty environment data. Tests must be completely self-contained, creating their required fixtures during setup and cleaning up afterwards.
11. **Tenant & User Separation**: Tenants represent workspace/organization containers (`tenants` table). Users represent individual accounts (`users` table with `email`, `password_hash`, `tenant_id`, `role`). JWT claims MUST contain `user_id`, `tenant_id`, and `role`.
12. **Zero Plaintext Secrets in Broker or Logs**: Access tokens/secrets MUST NEVER be sent in plaintext over NATS Message Broker events, logged to stdout/stderr, or stored unencrypted. All secrets are encrypted at rest with Fernet AES-256 using a shared secret `ENCRYPTION_KEY` (with a deterministic `DEFAULT_DEV_KEY` fallback for local dev).
13. **End-to-End Correlation ID (`X-Request-ID`)**: Every HTTP request originating at Gateway or client MUST be tagged with a unique `X-Request-ID`. All downstream microservices (Core, Importers, Analysis) MUST propagate `X-Request-ID` in HTTP headers, NATS events, and log outputs (`[req_id=...]`).
14. **No Personal or Environment-Specific Information in the Repository**: This repository is intended to be published. Nothing committed to it may identify the person who runs it, the machine it was written on, or where it is deployed. Specifically forbidden anywhere in tracked files — source, tests, fixtures, documentation, compose files, commit messages, planning notes:
    - **Real email addresses.** Use `@example.com` or `@example.test`. The one exception is the author line in `LICENSE`, which is a copyright notice and belongs there.
    - **Real password hashes**, even "just a dev account". `infra/db/init.sql` once seeded an owner with a committed bcrypt hash for a real address; every clone carried the credentials for that account.
    - **Deployment hostnames and public URLs.** These come from `PUBLIC_HOST` / `PUBLIC_BASE_URL` at deploy time. A hostname in the source tells a reader of the public repository exactly what to point their tools at.
    - **Absolute local filesystem paths** (`C:\Users\…`, `/home/…`, `/Users/…`). Use repository-relative paths.
    - **Real personal data of any kind** — names in placeholders, actual health data, actual location traces, screenshots containing either.
    - **Agent working state.** Per-run scratch directories and AI planning artifacts are not project documentation and MUST NOT be committed, least of all wired into the published documentation nav. Durable outputs belong in `specs/` (specifications), `docs/` (behaviour and operation) or a commit message (why a change was made) — under their own names, in the form the project already uses. A running log of what an agent did is not one of those: it duplicates the git history in a shape nothing verifies.

    Development *defaults* for secrets (`JWT_SECRET`, `ENCRYPTION_KEY`, …) are a deliberate exception: they are published on purpose so local development needs no configuration, and production refuses to start on them. Everything above is not that — it is information about a particular person and a particular deployment, and no mechanism downstream can undo committing it.

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
- **Connector Config**: Dashboard UI -> Gateway -> Core Service (`POST /api/v1/data/sources/configure` -> Fernet AES-256 Encrypted DB) -> Importer dynamic fetch.
- **Tracing**: Request -> Gateway (injects `X-Request-ID`) -> Core (`X-Request-ID` in headers & logs `[req_id=...]`) -> Importers/NATS (`X-Request-ID`).

---

## Testing Requirements

- **Location**: Every service must have a dedicated `tests/` directory.
- **Unit Tests**: Use `pytest`. Mock all external dependencies (NATS, external APIs, gRPC clients).
- **Integration Tests**: Must use `docker compose` to spin up actual backing services (PostgreSQL, NATS) for tests.
- **Self-Contained Fixtures**: Every integration test must create its required tenant/user/data rows explicitly and teardown afterwards. Never assume pre-existing database records.
- **Traceability**: Invariant mapping in test docstrings (e.g., `"""Verifies Fizzbee Invariant: NoDuplicateRecords"""`).

---

## When Adding a New Importer

If the user asks to add an integration for a new data source:

1. Create a new directory: `services/importers/<name>/`
2. Implement four core modules: `config.py`, `client.py`, `transformer.py`, `main.py`.
3. Configure the importer to fetch connector credentials dynamically from Core Data Service DB (`GET /api/v1/internal/data/sources/<name>/token`).
4. Configure the importer to publish to the NATS subject `qs.ingest.<name>`.
5. Ensure the `idempotency_key` is generated correctly in the transformer.
6. Add a `Dockerfile` for the new service and add it to `infra/docker-compose.yml`.
7. Write a Fizzbee spec extension ONLY IF new distributed patterns are introduced.
8. Add comprehensive test coverage.

---

## Anti-Patterns to Reject

If you see these patterns, you MUST fix them or refuse to write them:

- ❌ Direct database access from API Gateway, Analysis, or Importers.
- ❌ Missing `tenant_id` filters in `SELECT`, `UPDATE`, or `DELETE` statements.
- ❌ Synchronous HTTP calls from Importers to Core for data ingestion (MUST use NATS).
- ❌ Hardcoded tenant IDs or API secrets in `.env` or source code.
- ❌ Plaintext API tokens in NATS events or log outputs.
- ❌ Un-correlated requests missing `X-Request-ID` headers or log prefixes `[req_id=...]`.
- ❌ Automatic generation of fake/seed data on service startup or fallback.
- ❌ Tests that depend on pre-existing database state or pre-run seed commands.
- ❌ Skipping Fizzbee specifications for new, complex distributed coordination.
- ❌ Sharing mutable state between microservices.
- ❌ A real email address, deployment hostname, absolute local path or personal name anywhere in a tracked file (rule 14).
- ❌ Committing agent scratch directories or AI planning documents, and never into the published docs nav.
- ❌ Self-registration enabled by default. `ALLOW_REGISTRATION` is `False`; the first account is created with `python -m core.create_owner`.

## Documentation Requirements for New Features

Every new user-facing or operational feature MUST include code-to-documentation updates in the MkDocs site under `docs/`. Feature documentation must explain:

1. What the feature does and why it exists.
2. How data flows through the platform while preserving service boundaries.
3. How users or operators configure and use it.
4. How imported or derived data can be retrieved through tenant-scoped Core/Gateway APIs.
5. Expected recommendations, interpretation guidance, and known limitations.

Importer changes MUST update `docs/importers/` and link to external API setup references when relevant. Analysis, data-quality, and visualization features MUST update `docs/features/`. The documentation site is built with MkDocs/Material and served separately from the product UI under `/docs`.
