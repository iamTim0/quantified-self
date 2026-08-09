# Quantified Self - Project Agent Rules & Workflows (Claude Code)

This workspace uses shared agentic customizations under `.agents/`; Claude Code, Codex, and
Gemini/Antigravity all read the same skills and run the same lifecycle scripts. Claude-specific
wiring lives in [.claude/](.claude/README.md).

The full architectural rulebook is imported below and is binding for every turn:

@AGENTS.md

## 1. Absolute Rules & System Invariants
- Refer to [AGENTS.md](AGENTS.md) for the complete, numbered rules (1-15). Summary of the
  invariants that are violated most often:
- **Database Ownership**: Only `services/core/` can connect to or query PostgreSQL. No other service may import SQLAlchemy or asyncpg.
- **Tenant Isolation**: All database queries MUST filter by `tenant_id`. API Gateway injects `X-Tenant-ID`.
- **Tenant & User Separation**: Workspace (`tenants`) is separated from User identity (`users`). JWT claims contain `user_id`, `tenant_id`, and `role`.
- **Stateless Importers**: Importers do NOT store tokens in `.env` or local DBs. They retrieve encrypted credentials dynamically from Core Data Service.
- **Zero Plaintext Secrets**: Secrets MUST NEVER be published in plaintext over NATS events or logged to stdout. All credentials are encrypted at rest via Fernet AES-256 (`ENCRYPTION_KEY`).
- **End-to-End Correlation Tracking**: Every request/event propagates `X-Request-ID` across API Gateway, Core Service, NATS, and Importers with log prefixes `[req_id=...]`.
- **Idempotency**: All ingestion events require deterministic `idempotency_key` = `SHA256(tenant_id + source_id + metric_type + timestamp)`.
- **One Metric, One Name, One Unit**: Every `metric_type` comes from the registry in `packages/shared-schemas/src/shared_schemas/metrics.py`, resolved via `canonical_metric_type()` *before* the idempotency key is derived; values are converted into the registry's unit. Never invent a metric name. See [Metrics](docs/metrics.md).
- **Inter-service Communication**: Importers publish to NATS (`qs.ingest.<source>`); Analysis queries Core via gRPC.
- **No Auto-Seed Data**: Microservices and importers MUST NEVER automatically generate mock seed data on startup or missing config.
- **One Language**: The repository is English — code, comments, docs, logs, commit messages, service responses. Two exceptions, both content: `apps/dashboard/src/app/lib/i18n/catalog-de.ts`, and the German half of the two legal documents under `apps/dashboard/src/app/legal/`, whose wording is legally binding. A German comment is a defect.
- **No User-Visible Literals in Components**: Every dashboard string goes through `t("area.thing")` and exists in **both** catalogues; `catalog-de.ts` is typed against the English one, so a missing key fails `tsc`. Dates and numbers come from `useI18n()`, never from a hardcoded locale.
- **Localize at the Edge**: Services answer in English and hand out a stable `code` (plus `params`) for anything the UI must say in another language. A client never branches on prose, and a value it compares against (`direction`, `status`) is an English identifier changed on both sides in one commit.
- **Defaults Are Local**: A default in `config.py` names loopback and the port the service actually binds; container hostnames belong in the compose files. A fallback list remembers which candidate answered.

## 2. Enabled Skills
Project skills are registered in `.claude/skills/` and delegate to the canonical definitions in
`.agents/skills/`, so all three clients share one source of truth.

- `review-graph`: Traces cross-service dependency graphs and structural breaking changes.
- `spec-verifier`: Verifies implementation against Fizzbee specifications in `specs/`.
- `ast-grep-refactor`: Structural search and AST-based refactoring.
- `doc-sync`: Keeps repository documentation and implementation changes synchronized.
- `caveman-commit` / `caveman-review`: Token-compressed commit messages and review comments
  (installed at user scope in `~/.claude/skills/`, not in this repository).

## 3. Active Hooks
- Claude Code: [.claude/settings.json](.claude/settings.json) -> `PreToolUse` on `Bash`/`PowerShell`
  runs `.agents/scripts/pre_command_guard.py`; `Stop` runs `.agents/scripts/validate_docs.py`.
- Gemini/Antigravity: `.agents/hooks.json` -> the same two scripts.
- Codex: `.codex/hooks.json` -> the same two scripts with Codex-native hook contracts.
- The guard denies destructive commands (`rm -rf /`, force-push to `main`); the validator blocks
  turn completion on broken markdown links or microservice changes shipped without doc updates.
- Editing hooks mid-session does not reload them: open `/hooks` once or restart Claude Code.

## 4. MCP
- No project-scoped MCP servers are configured, and none may be committed here.
- Keep MCP credentials and machine-specific servers in local client configuration
  (`claude mcp add --scope user ...`), mirroring the Codex and Gemini policy.

## 5. Commands
Use `task` (see [Taskfile.yml](Taskfile.yml)) rather than ad-hoc shell pipelines:
`task test:all`, `task lint`, `task docs:serve`. Python dependencies are managed per service with
`uv`.
