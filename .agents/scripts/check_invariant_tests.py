"""Reject vacuous executable invariant tests.

The Fizzbee models and their Python mappings are safety-critical documentation.
An empty ``test_*`` function, a lone ``pass`` or ``assert True`` gives the
repository a green check without checking a property. Keep this guard small and
AST-based so it has no test-runner or third-party dependency.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = REPO_ROOT / "specs" / "tests"


def _without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    if body and isinstance(body[0], ast.Expr):
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return body[1:]
    return body


def _is_vacuous(body: list[ast.stmt]) -> bool:
    body = _without_docstring(body)
    if not body:
        return True
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return True
    if len(body) == 1 and isinstance(body[0], ast.Return):
        return isinstance(body[0].value, ast.Constant) and body[0].value.value is True
    if len(body) == 1 and isinstance(body[0], ast.Assert):
        return isinstance(body[0].test, ast.Constant) and body[0].test.value is True
    return False


def main() -> int:
    failures: list[str] = []
    for path in sorted(TEST_ROOT.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_") or not _is_vacuous(node.body):
                continue
            failures.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {node.name}")

    if failures:
        print("Vacuous invariant tests found:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"Checked executable invariant tests in {TEST_ROOT.relative_to(REPO_ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
