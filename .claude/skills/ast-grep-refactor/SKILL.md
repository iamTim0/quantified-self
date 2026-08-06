---
name: ast-grep-refactor
description: AST-based structural code searching, linting, and refactoring across codebase files without fragile regex matching.
---

# AST-Grep & Structural Refactoring Skill

This skill is shared across Claude Code, Codex, and Gemini/Antigravity. The canonical
definition lives in one place so all clients behave identically.

**First action: read [.agents/skills/ast-grep-refactor/SKILL.md](../../../.agents/skills/ast-grep-refactor/SKILL.md)
and follow it exactly.** Do not refactor from this stub alone.

Quick reminder of when it applies: finding queries missing a `tenant_id` filter, locating
functions without type annotations or docstrings, and renaming symbols or signatures across
services and packages.
