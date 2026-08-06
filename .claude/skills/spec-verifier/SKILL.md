---
name: spec-verifier
description: Formally verifies system implementation against Fizzbee specifications in specs/ and ensures docstrings link tests to target invariants.
---

# Spec-Verifier Skill

This skill is shared across Claude Code, Codex, and Gemini/Antigravity. The canonical
definition lives in one place so all clients behave identically.

**First action: read [.agents/skills/spec-verifier/SKILL.md](../../../.agents/skills/spec-verifier/SKILL.md)
and follow it exactly.** Do not verify from this stub alone.

Quick reminder of when it applies: before implementing a new distributed interaction pattern
(AGENTS.md rule 5 — Fizzbee First), when changing ingestion or idempotency behavior, and when
checking that tests cite the Fizzbee invariant they verify.
