# Quantified Self - Project Agent Rules & Workflows

This workspace uses shared agentic customizations under `.agents/`; Codex mirrors the
same skills and lifecycle behavior through `.codex/`, and Claude Code through `.claude/`
plus [CLAUDE.md](CLAUDE.md).

## 1. Absolute Rules & System Invariants
- Refer to [AGENTS.md](AGENTS.md) for full architectural guidelines.
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
Canonical definitions live in `.agents/skills/`; Claude Code registers them via stubs in `.claude/skills/`.

- `review-graph`: Traces cross-service dependency graphs and structural breaking changes.
- `spec-verifier`: Verifies implementation against Fizzbee specifications in `specs/`.
- `ast-grep-refactor`: Structural search and AST-based refactoring.
- `doc-sync`: Keeps repository documentation and implementation changes synchronized.
- `caveman` / `cavecrew`: Token compression and subagent delegation (`cavecrew-builder`, `cavecrew-investigator`).

## 3. Active Hooks
- Gemini/Antigravity: `.agents/hooks.json` -> `.agents/scripts/pre_command_guard.py` and `validate_docs.py`.
- Codex: `.codex/hooks.json` uses the same scripts with Codex-native hook contracts.
- Claude Code: `.claude/settings.json` uses the same scripts (`PreToolUse` on `Bash`/`PowerShell`, `Stop`).
- Codex requires reviewing and trusting project hooks through `/hooks` after first setup or changes; Claude Code reloads hook changes only after `/hooks` or a restart.

## 4. MCP
- No project-scoped MCP servers are currently configured.
- Keep MCP credentials and machine-specific servers in local client configuration, never in this repository.
- The `notebooklm` server is configured per-user in each client (Gemini `~/.gemini/settings.json`, Claude Code user scope).
