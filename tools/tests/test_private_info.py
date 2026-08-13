"""Regression tests for the repository publication safety checks."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = REPO_ROOT / ".agents/scripts/check_private_info.py"
SPEC = importlib.util.spec_from_file_location("check_private_info", CHECKER_PATH)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def test_container_internal_path_is_allowed() -> None:
    """Container filesystem paths are not host-specific personal information."""
    assert CHECKER.check_text("compose.yml", "PGDATA=/home/postgres/pgdata/data\n") == []


def test_host_home_path_is_still_rejected() -> None:
    """A developer or operator home path remains forbidden."""
    host_path = "/home/" + "alice/project"
    problems = CHECKER.check_text("notes.md", f"Use {host_path} for local files.\n")

    assert len(problems) == 1
    assert host_path in problems[0]
