#!/usr/bin/env python3
"""Run every Fizzbee specification in specs/ through the model checker.

Fizzbee publishes Linux and macOS binaries only -- there is no Windows build --
and the checker is linked against glibc 2.34+, which rules out older WSL
distributions. This script therefore prefers a `fizz` already on PATH and
otherwise falls back to the container image built from infra/fizzbee.Dockerfile,
so the same command works on any host and in CI.

Usage:
    python .agents/scripts/verify_specs.py               # all specs
    python .agents/scripts/verify_specs.py tenant_isolation
    python .agents/scripts/verify_specs.py --timeout 300

Exit code is non-zero if any spec fails to compile or violates an invariant.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "specs"
IMAGE = "qs-fizzbee:v0.5.2"

# The checker holds its state graph in memory. An unbounded spec will grow until
# something dies -- and on Docker Desktop that "something" was the whole Linux VM,
# which took the developer's Postgres and NATS containers down with it. Capping
# the container makes a runaway spec fail as itself instead.
CONTAINER_MEMORY = "3g"

# Per-spec wall-clock ceiling. A spec that needs longer than this is not bounded
# tightly enough to be worth running on every push; fix the spec, do not raise
# the limit casually.
DEFAULT_TIMEOUT_SECONDS = 180


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    probe = subprocess.run(  # noqa: PLW1510
        ["docker", "image", "inspect", IMAGE],
        capture_output=True,
        text=True,
    )
    return probe.returncode == 0


def _build_image() -> bool:
    print(f"Building {IMAGE} (first run only, downloads ~340 MB)...", flush=True)
    build = subprocess.run(  # noqa: PLW1510
        [
            "docker", "build",
            "-f", str(REPO_ROOT / "infra" / "fizzbee.Dockerfile"),
            "-t", IMAGE,
            str(REPO_ROOT),
        ]
    )
    return build.returncode == 0


def _command_for(spec: Path, native: str | None) -> list[str]:
    relative = spec.relative_to(REPO_ROOT).as_posix()
    if native:
        return [native, relative]
    return [
        "docker", "run", "--rm",
        "--memory", CONTAINER_MEMORY,
        "-v", f"{REPO_ROOT}:/work",
        IMAGE,
        relative,
    ]


def run_spec(spec: Path, native: str | None, timeout: int) -> tuple[bool, str, float]:
    started = time.monotonic()
    try:
        result = subprocess.run(  # noqa: PLW1510
            _command_for(spec, native),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s -- the spec needs tighter bounds", timeout

    elapsed = time.monotonic() - started
    output = (result.stdout or "") + (result.stderr or "")

    # Fizzbee reports an invariant violation in its output and its exit code, and
    # a compile error only on the exit code. Check both rather than trusting one.
    if result.returncode != 0 or "FAILED" in output:
        interesting = [
            line
            for line in output.splitlines()
            if line.strip() and "DeprecationWarning" not in line
        ]
        return False, "\n".join(interesting[:25]), elapsed

    return True, "", elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "specs", nargs="*", help="spec names to check (default: all in specs/)"
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    if args.specs:
        targets = []
        for name in args.specs:
            path = SPECS_DIR / (name if name.endswith(".fizz") else f"{name}.fizz")
            if not path.exists():
                print(f"No such spec: {path}", file=sys.stderr)
                return 2
            targets.append(path)
    else:
        targets = sorted(SPECS_DIR.glob("*.fizz"))

    if not targets:
        print("No specifications found in specs/", file=sys.stderr)
        return 2

    native = shutil.which("fizz")
    if not native:
        if not _docker_available():
            if not shutil.which("docker"):
                print(
                    "Neither `fizz` nor docker is available. Install the Fizzbee CLI "
                    "(https://fizzbee.io) or Docker, then re-run.",
                    file=sys.stderr,
                )
                return 2
            if not _build_image():
                print("Could not build the Fizzbee image.", file=sys.stderr)
                return 2
        print(f"Using {IMAGE} (no `fizz` on PATH)\n")
    else:
        print(f"Using {native}\n")

    failures: list[str] = []
    for spec in targets:
        print(f"  {spec.name} ... ", end="", flush=True)
        ok, detail, elapsed = run_spec(spec, native, args.timeout)
        if ok:
            print(f"ok ({elapsed:.1f}s)")
        else:
            print(f"FAILED ({elapsed:.1f}s)")
            print("      " + detail.replace("\n", "\n      "))
            failures.append(spec.name)

    print()
    if failures:
        print(f"{len(failures)} of {len(targets)} specifications failed: {', '.join(failures)}")
        return 1
    print(f"All {len(targets)} specifications verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
