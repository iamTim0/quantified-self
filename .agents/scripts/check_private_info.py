#!/usr/bin/env python3
"""Fail if a tracked file contains personal or environment-specific information.

AGENTS.md rule 14. This repository is meant to be published, and the things it
must not carry are the things nobody notices adding: an email address in a
fixture, a deployment hostname in a Traefik rule, `C:\\Users\\...` in a note, a
bcrypt hash in a seed script.

Everything below was actually found in this repository, which is why the check
exists rather than the rule alone:

* `infra/db/init.sql` seeded an owner account with a real address and a real
  bcrypt hash, so every clone carried working credentials for a real person;
* the deployment hostname appeared in seven files, including three Traefik host
  rules, telling any reader exactly where to point their tools;
* six agent task briefs recorded the absolute path of the machine that wrote
  them.

Deliberately narrow. A check that cries wolf gets deleted, so this looks only for
patterns with no legitimate use in a published repository, and every allowance is
listed rather than inferred.

    python .agents/scripts/check_private_info.py

Exit code is non-zero if anything is found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Domains reserved for documentation and testing (RFC 2606 and RFC 6761) plus
# GitHub's privacy-preserving author form.
ALLOWED_EMAIL_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "users.noreply.github.com",
    "noreply.anthropic.com",
)
# Reserved TLDs. `.test` is set aside by RFC 6761 for exactly this, so any
# address under it is a fixture by construction -- `a@b.test` included.
ALLOWED_EMAIL_TLDS = (".test", ".invalid", ".example", ".localhost")

# The author line of a copyright notice is a name on purpose.
#
# The same goes for *other people's* copyright notices, which is why the licence
# texts the dashboard image redistributes are listed here. `nanoid` and `postcss`
# both carry their author's address in that line, and reproducing the notice
# verbatim is the entire purpose of the file -- redacting it would defeat the
# obligation the file exists to satisfy. Neither is information about who runs this
# repository or where, which is what rule 14 is about.
SKIP_FILES = {
    "LICENSE",
    "apps/dashboard/THIRD-PARTY-NOTICES.txt",
}

# Binary-ish and vendored trees git may still track, plus the upstream font licences
# vendored verbatim under apps/dashboard/licenses/.
SKIP_PREFIXES = ("site/", "node_modules/", ".venv/", "apps/dashboard/licenses/")

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# Match the complete path so a known container-internal path can be allowed
# without accidentally allowing every path below the same user directory.
LOCAL_PATH = re.compile(
    r"(?:[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\[A-Za-z0-9._-]+)*"
    r"|/home/[a-z0-9._-]+(?:/[a-z0-9._-]+)*"
    r"|/Users/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*)"
)
BCRYPT = re.compile(r"\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}")
# A literal host in a Traefik rule. `${VAR}` and localhost are the only forms a
# published repository should contain.
TRAEFIK_HOST = re.compile(r"Host\(`([^`]+)`\)")

# The one bcrypt string that is allowed: an obviously fake fixture, identical in
# both places that use it, matching no real password.
ALLOWED_BCRYPT = {"$2b$12$abcdefghijklmnopqrstuv0123456789012345678901234567890ab"}
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}
# This is the default data directory inside the Timescale container, not a
# developer's or operator's host filesystem. Keep the allowance exact: other
# paths in the container's user directory must still be reported.
ALLOWED_CONTAINER_PATHS = {"/home/postgres/pgdata/data"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    )
    return [
        line
        for line in out.stdout.splitlines()
        if line and not line.startswith(SKIP_PREFIXES) and line not in SKIP_FILES
    ]


def check_text(relative: str, text: str) -> list[str]:
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in EMAIL.finditer(line):
            domain = match.group(1).lower()
            allowed = any(
                domain == d or domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS
            ) or domain.endswith(ALLOWED_EMAIL_TLDS)
            if not allowed:
                problems.append(
                    f"{relative}:{number}: real email address {match.group(0)!r} "
                    f"(use one of: {', '.join(ALLOWED_EMAIL_DOMAINS[:4])})"
                )

        for match in LOCAL_PATH.finditer(line):
            path_name = match.group(0).rstrip(".,;:!?")
            if path_name in ALLOWED_CONTAINER_PATHS:
                continue
            problems.append(
                f"{relative}:{number}: absolute local path {path_name!r} "
                "(use a repository-relative path)"
            )

        for match in BCRYPT.finditer(line):
            # Substring, not equality: the pattern captures a fixed 53
            # characters and the fixture is longer, so an exact comparison
            # never matched and the allowance silently did nothing.
            if not any(match.group(0) in allowed for allowed in ALLOWED_BCRYPT):
                problems.append(
                    f"{relative}:{number}: a bcrypt hash. Even a development "
                    "account's hash is crackable offline once published."
                )

        if relative.endswith((".yml", ".yaml")):
            for match in TRAEFIK_HOST.finditer(line):
                host = match.group(1)
                if "${" in host or host in ALLOWED_HOSTS:
                    continue
                problems.append(
                    f"{relative}:{number}: hardcoded deployment host {host!r} "
                    "(use ${PUBLIC_HOST:-localhost})"
                )

    return problems


def check_file(relative: str) -> list[str]:
    path = REPO_ROOT / relative
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # binary or unreadable; nothing to read here

    return check_text(relative, text)


def main() -> int:
    problems: list[str] = []
    files = tracked_files()
    for relative in files:
        problems.extend(check_file(relative))

    if problems:
        print(f"{len(problems)} problem(s) found (AGENTS.md rule 14):\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nThis repository is meant to be published. None of the above can be "
            "undone by a later commit -- it stays in the history.",
            file=sys.stderr,
        )
        return 1

    print(f"{len(files)} tracked file(s) checked: no personal information found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
