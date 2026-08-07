#!/usr/bin/env python3
"""Structural pre-flight check for Fizzbee specifications.

This is **not** a model checker. It explores no state space and proves nothing
about the invariants. What it does is catch, on any machine including plain
Windows PowerShell, the mistakes that otherwise cost a full CI round trip.

It exists because Fizzbee ships no Windows binary and its checker needs
glibc 2.34+, so the real check only runs under WSL, a container, or CI. Every
rule below corresponds to a failure that actually occurred in this repository the
first time the specs were run for real:

  Init            state at top level is frozen; appending to it panics
  LoopVars        `for k, v in d.items()` -- Fizzbee allows exactly one variable
  Liveness        a bare `eventually assertion` panics the invariant checker
  InvariantSyntax `invariant NAME:` is not Fizzbee syntax and never parsed
  Tautology       an assertion whose body is `return True` cannot fail
  Deprecated      `= any(COLLECTION)` is deprecated in favour of `oneof`
  Reserved        `exists` and `any` are keywords and cannot name a variable

Usage:
    python .agents/scripts/lint_specs.py
    py .agents/scripts/lint_specs.py            # Windows launcher

Exit code is non-zero if any error-level finding is present. Tautologies are
warnings: they are usually a placeholder someone meant to come back to, and
`--strict` promotes them to errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "specs"

# Words Fizzbee reserves; using one as a variable is a parse error.
RESERVED = {"exists", "any", "oneof", "atomic", "fair", "action", "require", "always", "eventually"}

BLOCK_START = re.compile(
    r"^(atomic\s+|serial\s+|parallel\s+|oneof\s+)?(fair\s+)?"
    r"(action|func|role|always|eventually|invariants|assertion|compose|refine)\b"
)
TOP_LEVEL_ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")
MULTI_LOOP_VAR = re.compile(r"^\s*for\s+[A-Za-z_][A-Za-z0-9_]*\s*,")
BARE_EVENTUALLY = re.compile(r"^eventually\s+assertion\b")
INVARIANT_KEYWORD = re.compile(r"^invariant\s+[A-Za-z_]")
DEPRECATED_ANY = re.compile(r"=\s*any\s*\(")
ASSERTION_HEAD = re.compile(
    r"^((?:always|eventually)(?:\s+(?:always|eventually))?)\s+assertion\s+([A-Za-z_][A-Za-z0-9_]*)\s*:"
)


@dataclass
class Finding:
    path: Path
    line: int
    rule: str
    message: str
    level: str = "error"


def _assignment_target(line: str) -> str | None:
    match = TOP_LEVEL_ASSIGN.match(line)
    return match.group(1) if match else None


def lint(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    lines = path.read_text(encoding="utf-8").split("\n")

    in_block = False
    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        if BLOCK_START.match(line):
            in_block = True

        if INVARIANT_KEYWORD.match(line):
            findings.append(
                Finding(
                    path,
                    number,
                    "InvariantSyntax",
                    "`invariant NAME:` is not Fizzbee syntax. Use "
                    "`always assertion NAME:` with a body that returns a bool.",
                )
            )

        if BARE_EVENTUALLY.match(line):
            findings.append(
                Finding(
                    path,
                    number,
                    "Liveness",
                    "A bare `eventually assertion` panics the checker. Fizzbee "
                    "accepts always, always-eventually, eventually-always and exists.",
                )
            )

        if MULTI_LOOP_VAR.match(line):
            findings.append(
                Finding(
                    path,
                    number,
                    "LoopVars",
                    "Fizzbee allows exactly one loop variable. Iterate the keys "
                    "and index for the value instead of unpacking `.items()`.",
                )
            )

        if DEPRECATED_ANY.search(line):
            findings.append(
                Finding(
                    path,
                    number,
                    "Deprecated",
                    "`= any(COLLECTION)` is deprecated; use `oneof(COLLECTION)`.",
                    level="warning",
                )
            )

        target = _assignment_target(line) if not line.startswith((" ", "\t")) else None
        if target is not None and not in_block:
            if target.islower() or (target.startswith("_") and not target.isupper()):
                findings.append(
                    Finding(
                        path,
                        number,
                        "Init",
                        f"`{target}` looks like mutable state assigned at top level, "
                        "where Fizzbee freezes it -- appending to it panics with "
                        "'cannot append to frozen list'. Move it into `action Init:`. "
                        "(Constants are UPPER_CASE and belong here.)",
                    )
                )

        stripped = line.strip()
        for word in RESERVED:
            if re.match(rf"^{word}\s*=(?!=)", stripped):
                findings.append(
                    Finding(
                        path,
                        number,
                        "Reserved",
                        f"`{word}` is a Fizzbee keyword and cannot be used as a "
                        "variable name.",
                    )
                )

    findings.extend(_find_tautologies(path, lines))
    return findings


def _find_tautologies(path: Path, lines: list[str]) -> list[Finding]:
    """Assertions whose only statement is `return True` verify nothing."""
    findings: list[Finding] = []
    for index, raw in enumerate(lines):
        head = ASSERTION_HEAD.match(raw.strip())
        if not head:
            continue

        body: list[str] = []
        for follower in lines[index + 1 :]:
            if follower.strip() and not follower.startswith((" ", "\t")):
                break
            if follower.strip() and not follower.strip().startswith("#"):
                body.append(follower.strip())

        if body == ["return True"]:
            findings.append(
                Finding(
                    path,
                    index + 1,
                    "Tautology",
                    f"`{head.group(2)}` has a body of only `return True`. It cannot "
                    "fail, so it verifies nothing -- give it a real body or delete it.",
                    level="warning",
                )
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict", action="store_true", help="treat warnings as errors"
    )
    parser.add_argument(
        "paths", nargs="*", help="specific .fizz files (default: all in specs/)"
    )
    args = parser.parse_args()

    specs = (
        [Path(p).resolve() for p in args.paths]
        if args.paths
        else sorted(SPECS_DIR.glob("*.fizz"))
    )
    if not specs:
        print("No specifications found in specs/", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    for spec in specs:
        all_findings.extend(lint(spec))

    errors = [f for f in all_findings if f.level == "error"]
    warnings = [f for f in all_findings if f.level == "warning"]

    for finding in sorted(all_findings, key=lambda f: (f.path.name, f.line)):
        try:
            rel = finding.path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = finding.path.as_posix()
        print(f"{rel}:{finding.line}: {finding.level}: [{finding.rule}] {finding.message}")

    print()
    print(
        f"{len(specs)} specification(s) checked: "
        f"{len(errors)} error(s), {len(warnings)} warning(s)."
    )
    if not all_findings:
        print("No structural problems. This does NOT model-check them --")
        print("run `task fizz:check` (WSL or container) or push and let CI do it.")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
