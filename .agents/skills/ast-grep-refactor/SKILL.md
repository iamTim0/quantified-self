---
name: ast-grep-refactor
description: AST-based structural code searching, linting, and refactoring across codebase files without fragile regex matching.
---

# AST-Grep & Structural Refactoring Skill

The `ast-grep-refactor` skill uses Abstract Syntax Tree (AST) pattern matching to inspect and refactor Python code safely.

## 1. When to Use
- Locating functions missing type annotations or docstrings.
- Finding queries lacking `tenant_id` filters across SQL queries or ORM calls.
- Renaming symbols, updating function signatures across microservices, or refactoring imports across python packages.

## 2. Patterns & Examples

### Finding SQL queries without tenant_id
```python
# Pattern: Find query calls missing tenant_id parameter
session.execute(select($MODEL).where($COND))
# Fix: Ensure .where($MODEL.tenant_id == tenant_id) is included
```

### Finding unhandled async tasks
```python
# Pattern: asyncio.create_task without tracking reference
asyncio.create_task($CORO)
```

## 3. Best Practices
- Always verify refactoring results with `uv run pytest` or `task test:all` after structural edits.
