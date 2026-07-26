import json
import os
import re
import subprocess
import sys


def get_modified_files():
    """Returns list of modified or untracked files in git workspace."""
    try:
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, check=False)
        lines = res.stdout.strip().split("\n")
        files = []
        for line in lines:
            if line:
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    files.append(parts[1])
        return files
    except Exception:
        return []

def validate_markdown_links(filepath):
    """Validates that local markdown relative links point to existing files."""
    if not os.path.exists(filepath):
        return []
    
    broken_links = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Find [text](path)
    links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', content)
    base_dir = os.path.dirname(filepath) or "."

    for text, target in links:
        if target.startswith("http://") or target.startswith("https://") or target.startswith("#") or target.startswith("mailto:"):
            continue
        
        # Clean query/hash
        clean_target = target.split("#")[0].split("?")[0]
        if not clean_target:
            continue

        target_path = os.path.normpath(os.path.join(base_dir, clean_target))
        if not os.path.exists(target_path):
            broken_links.append(target)

    return broken_links

def main():
    try:
        raw_input = sys.stdin.read()
        data = json.loads(raw_input) if raw_input else {}
    except Exception:
        data = {}

    modified = get_modified_files()
    
    code_changes = [f for f in modified if f.startswith("services/") or f.startswith("packages/") or f.startswith("specs/")]
    doc_changes = [f for f in modified if f.endswith(".md") or "docs" in f]

    issues = []

    # 1. Check broken links in key documentation files
    for doc in ["README.md", "GEMINI.md", "agents.md"]:
        if os.path.exists(doc):
            broken = validate_markdown_links(doc)
            if broken:
                issues.append(f"Broken links found in {doc}: {', '.join(broken)}")

    # 2. Check if structural code changes occurred without doc updates
    if code_changes and not doc_changes:
        # If new importer or service added, require README update
        new_services = [f for f in code_changes if "importers/" in f or "services/" in f]
        if new_services:
            issues.append(f"Code changes detected in microservices ({len(new_services)} files), but README.md or GEMINI.md were not updated.")

    # Response for Stop hook or PostToolUse
    if issues:
        # Request agent to continue and fix docs
        output = {
            "decision": "continue",
            "reason": "Documentation & README Validation Check:\n" + "\n".join(f"- {issue}" for issue in issues)
        }
    else:
        output = {"decision": "allow"}

    print(json.dumps(output))

if __name__ == "__main__":
    main()
