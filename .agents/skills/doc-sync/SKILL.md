---
name: doc-sync
description: Validates and synchronizes documentation, README.md, GEMINI.md, API specs, and docstrings whenever code features or microservice architectures change.
---

# Documentation & README Sync Skill

The `doc-sync` skill ensures all codebase documentation remains 100% accurate, up-to-date, and free of broken links.

## 1. When to Trigger
Activate this skill whenever:
- Adding a new microservice or importer (e.g. `services/importers/<name>`).
- Changing environment variables, ports, or API routes in `services/core` or `services/api-gateway`.
- Updating protobuf schemas in `packages/proto`.
- Adding new task commands to `Taskfile.yml`.
- Before submitting a pull request or ending a major feature turn.

## 2. Verification Checklist
- [ ] **`README.md`**: Update microservice table, architecture diagram, environment variables, and task commands.
- [ ] **`GEMINI.md` / `agents.md`**: Ensure invariant rules match actual implementation details.
- [ ] **Relative Markdown Links**: Verify all local markdown links (e.g., `[LICENSE](file:///LICENSE)`) resolve to existing files.
- [ ] **Docstrings**: Ensure new public functions, classes, and tests have clear docstrings referencing spec invariants.

## 3. Automation
The workspace uses a `Stop` hook in `.agents/hooks.json` running `python .agents/scripts/validate_docs.py` to block completion if broken markdown links or un-documented microservice changes exist.
