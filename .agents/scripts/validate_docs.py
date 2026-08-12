import json
import os
import re
import subprocess
import sys
from typing import Any


def get_modified_files() -> list[str]:
    """Returns list of modified or untracked files in git workspace."""
    try:
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False)
        lines = res.stdout.strip().split("\n")
        files: list[str] = []
        for line in lines:
            if line:
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    files.append(parts[1])
        return files
    except Exception:  # noqa: BLE001
        return []

CODE_ROOTS = ("services/", "packages/", "specs/")

# Extensions that carry behaviour worth documenting. Everything else under those
# roots -- `.dockerignore`, a lockfile, a cache -- cannot need a README change,
# and warning about it teaches the reader to ignore this check.
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".proto", ".fizz", ".sql")

IGNORED_PARTS = ("__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "node_modules")


def is_code(path: str) -> bool:
    if not path.startswith(CODE_ROOTS):
        return False
    if any(part in path for part in IGNORED_PARTS):
        return False
    return path.endswith(CODE_SUFFIXES)


def is_doc(path: str) -> bool:
    return path.endswith(".md") or "docs" in path


def validate_markdown_links(filepath: str) -> list[str]:
    """Validates that local markdown relative links point to existing files."""
    if not os.path.exists(filepath):
        return []
    
    broken_links: list[str] = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Find [text](path)
    links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
    base_dir = os.path.dirname(filepath) or "."

    for text, target in links:
        if target.startswith("http://") or target.startswith("https://") or target.startswith("#") or target.startswith("mailto:"):  # noqa: PIE810
            continue
        
        # Clean query/hash
        clean_target = target.split("#")[0].split("?")[0]
        if not clean_target:
            continue

        target_path = os.path.normpath(os.path.join(base_dir, clean_target))
        if not os.path.exists(target_path):
            broken_links.append(target)

    return broken_links

def main() -> None:
    try:
        raw_input = sys.stdin.read()
        parsed_input = json.loads(raw_input) if raw_input else {}
    except (json.JSONDecodeError, OSError):
        parsed_input = {}

    data: dict[str, Any] = parsed_input if isinstance(parsed_input, dict) else {}

    is_codex = data.get("hook_event_name") == "Stop"

    modified = get_modified_files()

    code_changes = [f for f in modified if is_code(f)]
    doc_changes = [f for f in modified if is_doc(f)]

    issues = []

    # 1. Check broken links in key documentation files
    for doc in ["README.md", "GEMINI.md", "CLAUDE.md", "AGENTS.md"]:
        if os.path.exists(doc):
            broken = validate_markdown_links(doc)
            if broken:
                issues.append(f"Broken links found in {doc}: {', '.join(broken)}")

    # 2. Check if structural code changes occurred without doc updates
    if code_changes and not doc_changes:
        # If new importer or service added, require README update
        new_services = [f for f in code_changes if "importers/" in f or "services/" in f]
        if new_services:
            listed = ", ".join(sorted(new_services)[:4])
            more = "" if len(new_services) <= 4 else f" (+{len(new_services) - 4} more)"
            issues.append(
                f"Uncommitted source changes with no documentation change anywhere: "
                f"{listed}{more}. Update the relevant page under docs/, or README.md "
                f"if it changes how the project is run."
            )

    # Response for Stop hook or PostToolUse
    if issues:
        # Request agent to continue and fix docs
        reason = "Documentation & README Validation Check:\n" + "\n".join(
            f"- {issue}" for issue in issues
        )
        output = {"decision": "block", "reason": reason} if is_codex else {
            "decision": "continue",
            "reason": reason,
        }
    else:
        output = {} if is_codex else {"decision": "allow"}

    print(json.dumps(output))

if __name__ == "__main__":
    main()
