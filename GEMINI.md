# Quantified Self - Project Agent Rules & Workflows

This workspace uses Antigravity Agentic Customizations configured under `.agents/`.

## 1. Absolute Rules & System Invariants
- Refer to [agents.md](agents.md) for full architectural guidelines.
- **Database Ownership**: Only `services/core/` can connect to or query PostgreSQL. No other service may import SQLAlchemy or asyncpg.
- **Tenant Isolation**: All database queries MUST filter by `tenant_id`. API Gateway injects `X-Tenant-ID`.
- **Tenant & User Separation**: Workspace (`tenants`) is separated from User identity (`users`). JWT claims contain `user_id`, `tenant_id`, and `role`.
- **Stateless Importers**: Importers do NOT store tokens in `.env` or local DBs. They retrieve encrypted credentials dynamically from Core Data Service.
- **Zero Plaintext Secrets**: Secrets MUST NEVER be published in plaintext over NATS events or logged to stdout. All credentials are encrypted at rest via Fernet AES-256 (`ENCRYPTION_KEY`).
- **End-to-End Correlation Tracking**: Every request/event propagates `X-Request-ID` across API Gateway, Core Service, NATS, and Importers with log prefixes `[req_id=...]`.
- **Idempotency**: All ingestion events require deterministic `idempotency_key` = `SHA256(tenant_id + source_id + metric_type + timestamp)`.
- **Inter-service Communication**: Importers publish to NATS (`qs.ingest.<source>`); Analysis queries Core via gRPC.
- **No Auto-Seed Data**: Microservices and importers MUST NEVER automatically generate mock seed data on startup or missing config.

## 2. Enabled Skills
- `review-graph`: Traces cross-service dependency graphs and structural breaking changes.
- `spec-verifier`: Verifies implementation against Fizzbee specifications in `specs/`.
- `ast-grep-refactor`: Structural search and AST-based refactoring.
- `caveman` / `cavecrew`: Token compression and subagent delegation (`cavecrew-builder`, `cavecrew-investigator`).

## 3. Active Hooks
- PreToolUse command guard (`.agents/hooks.json` -> `.agents/scripts/pre_command_guard.py`) prevents dangerous destructive commands.
