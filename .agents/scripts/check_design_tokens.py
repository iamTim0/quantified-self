#!/usr/bin/env python3
"""Fail if a dashboard component reaches past the design tokens.

The dashboard has a semantic colour layer (`--color-surface`, `--color-ink`,
`--color-brand`, ...) declared in `globals.css`, and for a long time it also had
three other ways of saying the same thing: raw Tailwind palette utilities, a
block of `[data-theme="dark"] .bg-white { ... !important }` rules translating
those utilities for the dark theme, and `dark:` variants used by a handful of
files. A component written against any of the three follows the theme only for
the exact class strings somebody remembered to list.

That is not hypothetical. `bg-slate-50/60` and `bg-slate-900` stayed near-white
and near-invisible in dark mode for as long as they did precisely because the
shim can only cover what it enumerates, and `text-slate-400` -- 2.56:1 on white,
below the 4.5:1 WCAG 1.4.3 asks of text -- reached 171 occurrences on units,
timestamps and sample sizes before anyone counted.

So this is a ratchet, not a gate. Every violation that exists today is listed in
the allowlist beside this file; the check fails on anything *new*, and the
allowlist shrinks as files are migrated. A rule nobody can satisfy gets deleted,
which is why it starts from where the code actually is.

    python .agents/scripts/check_design_tokens.py

Exit code is non-zero if a file outside the allowlist violates a rule.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = REPO_ROOT / "apps" / "dashboard" / "src"
ALLOWLIST_PATH = Path(__file__).with_name("design_tokens_allowlist.json")

#: Palette families a component must not name directly. `slate` carries the
#: neutrals, the rest carry status; both have semantic tokens.
PALETTE = "slate|gray|zinc|neutral|stone|emerald|green|rose|red|amber|yellow|sky|blue|violet|purple|teal"

#: Utilities that take a colour. `divide` and `ring` are included because they
#: are borders by another name and were missed by the shim for exactly that.
COLOR_UTILITIES = "text|bg|border|divide|ring|from|via|to|fill|stroke|shadow|outline|accent|caret|decoration"

RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "raw-palette",
        re.compile(rf"\b(?:{COLOR_UTILITIES})-(?:{PALETTE})-\d{{2,3}}\b"),
        "names a Tailwind palette colour directly; use a semantic token "
        "(bg-surface, text-ink, text-ink-muted, border-line, bg-brand, ...)",
    ),
    (
        "arbitrary-font-size",
        re.compile(r"text-\[\d+(?:\.\d+)?px\]"),
        "sets a pixel font size; use the type scale "
        "(text-meta, text-body, text-emph, text-title, text-page, text-stat)",
    ),
    (
        "hex-literal",
        # Skips `#` inside a URL fragment or an id selector by requiring the
        # 3/6-digit form followed by a non-word character.
        re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b(?![\w-])"),
        "hardcodes a colour; charts read tokens through useChartTheme(), "
        "SVG can reference var(--color-...) directly",
    ),
)

#: Files that *define* the palette or generate an asset from it, rather than
#: consuming one. `globals.css` is exempt from every rule, not just the hex one:
#: it declares the tokens, and its comments quote the very class names the other
#: rules look for -- explaining what was replaced is not a violation.
COLOR_SOURCES = {
    "apps/dashboard/scripts/generate-icons.ts",
}

#: Exempt from all rules. The palette cannot be written in terms of itself.
PALETTE_DEFINITION = "apps/dashboard/src/app/globals.css"


def load_allowlist() -> dict[str, list[str]]:
    if not ALLOWLIST_PATH.exists():
        return {}
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


def scan() -> tuple[list[str], dict[str, list[str]]]:
    """Return (failures, current) -- current is the full inventory, for --update."""
    allowlist = load_allowlist()
    failures: list[str] = []
    current: dict[str, list[str]] = {}

    for path in sorted(DASHBOARD.rglob("*")):
        if path.suffix not in {".tsx", ".ts", ".css"} or not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel == PALETTE_DEFINITION:
            continue
        allowed = set(allowlist.get(rel, []))
        text = path.read_text(encoding="utf-8")
        hit_ids: list[str] = []

        for rule_id, pattern, explanation in RULES:
            if rule_id == "hex-literal" and rel in COLOR_SOURCES:
                continue
            if not pattern.search(text):
                continue
            hit_ids.append(rule_id)
            if rule_id in allowed:
                continue
            example = pattern.search(text)
            failures.append(f"{rel}: {rule_id} -- {explanation}\n    first match: {example.group(0)}")

        if hit_ids:
            current[rel] = sorted(hit_ids)

    return failures, current


def main() -> int:
    failures, current = scan()

    if "--update" in sys.argv:
        ALLOWLIST_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"allowlist rewritten: {len(current)} file(s) carry a known violation")
        return 0

    if failures:
        print("Design token violations outside the allowlist:\n")
        for failure in failures:
            print(f"  {failure}")
        print(
            "\nMigrate the file, or -- only when the violation is deliberate and "
            "explained -- record it with:\n"
            "  python .agents/scripts/check_design_tokens.py --update"
        )
        return 1

    remaining = sum(len(ids) for ids in current.values())
    print(
        f"design tokens: no new violations. "
        f"{remaining} known violation(s) across {len(current)} file(s) remain in the allowlist."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
