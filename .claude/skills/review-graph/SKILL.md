---
name: review-graph
description: Graph-aware code and architectural impact review. Traces dependency graphs, import chains, breaking contract changes, multi-tenant isolation, and service boundary violations across microservices.
---

# Review-Graph Skill

This skill is shared across Claude Code, Codex, and Gemini/Antigravity. The canonical
definition lives in one place so all clients behave identically.

**First action: read [.agents/skills/review-graph/SKILL.md](../../../.agents/skills/review-graph/SKILL.md)
and follow it exactly.** Do not review from this stub alone.

Quick reminder of when it applies: multi-file pull requests and large refactors, changes to
`packages/proto/`, `services/core/` schemas or any inter-service contract, and any review that
must confirm strict multi-tenant isolation.
