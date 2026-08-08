"""The generated copies of the registry must match the registry they came from.

Without this test, `task metrics:generate` is a step somebody remembers to run. The
failure it prevents is the one the registry was introduced to fix: the UI — and the
documentation — holding a different idea of the metrics than the services that write
them. Both had drifted that way before, the docs so far that most importer pages listed
metric names no transformer produced.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GENERATOR = REPO_ROOT / "packages" / "shared-schemas" / "generate_catalog.py"

GENERATED = {
    "dashboard catalog": REPO_ROOT / "apps/dashboard/src/app/lib/metrics/catalog.ts",
    "docs table": REPO_ROOT / "docs/metrics.md",
}


@pytest.fixture(scope="module")
def regenerated() -> dict[str, tuple[str, str]]:
    """Content of each generated file before and after re-running the generator."""
    before = {}
    for name, path in GENERATED.items():
        assert path.exists(), f"{path} is missing; run `task metrics:generate`"
        before[name] = path.read_text(encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(GENERATOR)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        # The assertion below reports the generator's own error; raising here would
        # replace it with a CalledProcessError that says nothing about why.
        check=False,
    )
    assert result.returncode == 0, result.stderr

    return {
        name: (before[name], path.read_text(encoding="utf-8"))
        for name, path in GENERATED.items()
    }


@pytest.mark.parametrize("name", list(GENERATED))
def test_generated_file_is_current(name, regenerated):
    before, after = regenerated[name]
    assert before == after, (
        f"{GENERATED[name].relative_to(REPO_ROOT).as_posix()} is out of date with "
        "packages/shared-schemas/src/shared_schemas/metrics.py. "
        "Run `task metrics:generate` and commit the result."
    )
