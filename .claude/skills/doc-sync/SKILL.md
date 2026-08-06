---
name: doc-sync
description: Validates and synchronizes documentation, README.md, GEMINI.md, CLAUDE.md, API specs, and docstrings whenever code features or microservice architectures change.
---

# Documentation & README Sync Skill

This skill is shared across Claude Code, Codex, and Gemini/Antigravity. The canonical
definition lives in one place so all clients behave identically.

**First action: read [.agents/skills/doc-sync/SKILL.md](../../../.agents/skills/doc-sync/SKILL.md)
and follow it exactly.** Do not sync docs from this stub alone.

Quick reminder of when it applies: adding an importer or microservice, changing environment
variables, ports, API routes, protobuf schemas, or `Taskfile.yml` commands, and before opening
a pull request. The `Stop` hook in [.claude/settings.json](../../settings.json) runs the same
validator, so unresolved broken links or undocumented service changes will block completion.
