# Quantified Self - Project Agent Rules & Workflows

This workspace uses Antigravity Agentic Customizations configured under `.agents/`.

## 1. Absolute Rules & System Invariants
- Refer to [agents.md](agents.md) for full architectural guidelines.
- **Database Ownership**: Only `services/core/` can connect to or query PostgreSQL.
- **Tenant Isolation**: All queries must filter by `tenant_id`.
- **Idempotency**: All ingestion events require deterministic `idempotency_key`.
- **Inter-service Communication**: Importers publish to NATS (`qs.ingest.<source>`); Analysis queries Core via gRPC.

## 2. Enabled Skills
- `review-graph`: Traces cross-service dependency graphs and structural breaking changes.
- `spec-verifier`: Verifies implementation against Fizzbee specifications in `specs/`.
- `ast-grep-refactor`: Structural search and AST-based refactoring.
- `caveman` / `cavecrew`: Token compression and subagent delegation (`cavecrew-builder`, `cavecrew-investigator`).

## 3. Active Hooks
- PreToolUse command guard (`.agents/hooks.json` -> `.agents/scripts/pre_command_guard.py`) prevents dangerous destructive commands.
