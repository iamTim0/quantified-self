"""The list of published container images, and a way to build them locally.

One manifest, two consumers: `.github/workflows/release.yml` reads it with
`--matrix` to generate its build matrix, and a developer runs it directly to build
the same fourteen images on their machine. Written as one list rather than two
because a duplicated list of fourteen entries drifts -- a new importer gets added
to the compose file and the Taskfile and then silently never gets published.

    python tools/build_images.py                  # build all of them
    python tools/build_images.py core dashboard   # build some of them
    python tools/build_images.py --matrix         # the GitHub Actions matrix
    python tools/build_images.py --check          # every Dockerfile is listed?
    python tools/build_images.py --importers      # the importer test matrix

Building locally is worth doing before cutting a release: the release workflow is
the first thing that ever builds all of these together, and a Dockerfile can rot
without any test noticing. The dashboard's had -- its pnpm lockfile went stale
while CI installed with npm, so the image had been unbuildable for some time and
nothing said so.

Local builds pass the selected tag and the current checkout commit as
`SOURCE_VERSION` and `SOURCE_COMMIT`, so their health endpoints identify the
artefact instead of falling back to an anonymous development build.

Contexts differ per image and are not cosmetic. Core and Analysis build from the
repository root because they depend on `packages/proto`, and every importer does the
same because it depends on `packages/shared-schemas` for the metric catalog -- a path
dependency cannot resolve from outside the build context. The docs image needs
`mkdocs.yml` and `docs/`. Only the Gateway and the dashboard build from their own
directory, because neither has a path dependency on `packages/`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Registry path for the published images. The version is a tag on top of this:
# ghcr.io/<owner>/<repo>/<name>:<version>. The release workflow derives the prefix
# from $GITHUB_REPOSITORY instead, so a fork publishes to its own packages.
DEFAULT_IMAGE_PREFIX = "ghcr.io/iamtim0/quantified-self"


@dataclass(frozen=True)
class Image:
    name: str
    context: str
    dockerfile: str
    # Buildx cache mode for the release workflow. `max` caches every intermediate
    # layer and `min` only the final ones, and the choice is a budget: the Actions
    # cache is 10 GB per repository with least-recently-used eviction, so fourteen
    # `max` scopes overflow it and then evict each other in an order nobody
    # controls -- which is slower than caching less on purpose. `max` therefore
    # goes to the three images whose builds are long (a full Next.js production
    # build, two `uv sync` resolutions against packages/proto) and `min` to the eleven
    # remaining images, whose layers are small and quick to rebuild.
    cache: str = "min"
    # Most images use the service pyproject in the Dockerfile's directory. A
    # deliberately minimal image can declare a smaller dependency closure.
    dependency_manifest: str | None = None


IMAGES: tuple[Image, ...] = (
    Image("core", ".", "services/core/Dockerfile", cache="max"),
    Image(
        "core-migrate",
        ".",
        "services/core/Dockerfile.migrate",
        dependency_manifest="services/core/migrations/pyproject.toml",
    ),
    Image("analysis", ".", "services/analysis/Dockerfile", cache="max"),
    Image("api-gateway", "services/api-gateway", "services/api-gateway/Dockerfile"),
    Image("dashboard", "apps/dashboard", "apps/dashboard/Dockerfile", cache="max"),
    Image("docs", ".", "infra/docs.Dockerfile"),
    # Every importer builds from the repository root: each one resolves metric names
    # and units through the path dependency on packages/shared-schemas.
    Image("importer-yazio", ".", "services/importers/yazio/Dockerfile"),
    Image("importer-whoop", ".", "services/importers/whoop/Dockerfile"),
    Image("importer-dawarich", ".", "services/importers/dawarich/Dockerfile"),
    Image("importer-apple-health", ".", "services/importers/apple_health/Dockerfile"),
    Image("importer-streak", ".", "services/importers/streak/Dockerfile"),
    Image("importer-home-assistant", ".", "services/importers/home_assistant/Dockerfile"),
    Image("importer-weather", ".", "services/importers/weather/Dockerfile"),
    Image("importer-calendar", ".", "services/importers/calendar/Dockerfile"),
    Image("importer-github", ".", "services/importers/github/Dockerfile"),
)

# Dockerfiles that exist but are deliberately not published: the Fizzbee model
# checker is a development tool and runs nowhere near a deployment.
UNPUBLISHED_DOCKERFILES = frozenset({"infra/fizzbee.Dockerfile"})


def matrix() -> list[dict[str, str]]:
    """The `strategy.matrix.include` value for the release workflow."""
    return [
        {
            "image": image.name,
            "context": image.context,
            "dockerfile": image.dockerfile,
            "cache": image.cache,
        }
        for image in IMAGES
    ]


def find_unlisted_dockerfiles() -> list[str]:
    """Dockerfiles in the repository that this manifest does not build.

    A new importer arrives with a Dockerfile and a compose entry, and forgetting
    this file means it is simply never published -- with no error, because nothing
    else knows the image was supposed to exist.
    """
    listed = {image.dockerfile for image in IMAGES} | set(UNPUBLISHED_DOCKERFILES)
    found: list[str] = []

    for path in (
        *REPO_ROOT.glob("**/Dockerfile"),
        *REPO_ROOT.glob("**/*.Dockerfile"),
        *REPO_ROOT.glob("**/Dockerfile.*"),
    ):
        relative = path.relative_to(REPO_ROOT).as_posix()
        if any(part in relative for part in ("node_modules/", ".venv/", "site/")):
            continue
        if relative not in listed:
            found.append(relative)

    return sorted(found)


def importers() -> list[str]:
    """Every importer service, discovered rather than listed.

    A directory under `services/importers/` is an importer when it has a
    `pyproject.toml`. That rule is what `task test:importers` uses, and CI reads its
    matrix from here for the same reason `release.yml` reads `--matrix`: the CI
    matrix used to be eight names written out by hand, so a ninth importer was
    tested on the contributor's machine and never in CI -- the same silence as a
    Dockerfile missing from `IMAGES`, and just as invisible.

    Deliberately not derived from `IMAGES`: an importer is worth testing before it
    is worth publishing, and that order should not be a reason for it to go
    untested.
    """
    root = REPO_ROOT / "services" / "importers"
    if not root.is_dir():
        return []
    return sorted(
        path.name for path in root.iterdir() if (path / "pyproject.toml").is_file()
    )


def _source_commit() -> str:
    """Return the checkout revision used to build local images."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def build(selected: list[str], *, prefix: str, version: str) -> int:
    docker = shutil.which("docker")
    if docker is None:
        print("docker is not on PATH", file=sys.stderr)
        return 2

    images = [i for i in IMAGES if not selected or i.name in selected]
    unknown = sorted(set(selected) - {i.name for i in IMAGES})
    if unknown:
        print(f"unknown image(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(i.name for i in IMAGES)}", file=sys.stderr)
        return 2

    failures: list[str] = []
    build_args = [
        "--build-arg",
        f"SOURCE_VERSION={version}",
        "--build-arg",
        f"SOURCE_COMMIT={_source_commit()}",
    ]
    for index, image in enumerate(images, start=1):
        tag = f"{prefix}/{image.name}:{version}"
        print(f"[{index}/{len(images)}] {tag}", flush=True)
        result = subprocess.run(
            [docker, "build", *build_args, "-f", image.dockerfile, "-t", tag, image.context],
            cwd=REPO_ROOT,
            # One failing image must not abort the other twelve; the point of a
            # local run is to find out which ones are broken, not the first one.
            check=False,
        )
        if result.returncode != 0:
            failures.append(image.name)
            print(f"  FAILED: {image.name}", file=sys.stderr, flush=True)

    print()
    if failures:
        print(f"{len(failures)} of {len(images)} failed: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"{len(images)} image(s) built as {prefix}/<name>:{version}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="*", help="image names to build; default is all")
    parser.add_argument("--matrix", action="store_true", help="print the GitHub Actions matrix")
    parser.add_argument(
        "--check", action="store_true", help="fail if a Dockerfile is not in the manifest"
    )
    parser.add_argument(
        "--importers", action="store_true", help="print the importer names as a JSON array"
    )
    parser.add_argument("--prefix", default=DEFAULT_IMAGE_PREFIX, help="registry prefix for tags")
    parser.add_argument("--version", default="local", help="tag to build as")
    args = parser.parse_args()

    if args.matrix:
        print(json.dumps(matrix()))
        return 0

    if args.importers:
        print(json.dumps(importers()))
        return 0

    if args.check:
        unlisted = find_unlisted_dockerfiles()
        if unlisted:
            print("Dockerfiles that are built by nothing:", file=sys.stderr)
            for path in unlisted:
                print(f"  {path}", file=sys.stderr)
            print(
                "\nAdd them to IMAGES in tools/build_images.py so the release "
                "publishes them, or to UNPUBLISHED_DOCKERFILES if they are "
                "development-only.",
                file=sys.stderr,
            )
            return 1
        print(f"{len(IMAGES)} image(s) in the manifest; every Dockerfile accounted for.")
        return 0

    return build(args.images, prefix=args.prefix, version=args.version)


if __name__ == "__main__":
    raise SystemExit(main())
