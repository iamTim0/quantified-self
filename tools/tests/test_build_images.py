"""Unit tests for tools.build_images.

The point of these is drift: the release workflow builds what this manifest says
and nothing else, so an image missing from it is an image that never gets
published -- silently, because no build fails when a build does not happen.
"""

import re
from pathlib import Path

import pytest
from tools.build_images import IMAGES, find_unlisted_dockerfiles, importers, matrix

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_every_dockerfile_is_either_published_or_explicitly_not():
    """Every Dockerfile in the repository is in the manifest or excluded by name."""
    assert find_unlisted_dockerfiles() == []


def test_manifest_paths_exist():
    """Each entry points at a Dockerfile and a context that are really there."""
    for image in IMAGES:
        assert (REPO_ROOT / image.dockerfile).is_file(), image.dockerfile
        assert (REPO_ROOT / image.context).is_dir(), image.context


def test_image_names_are_unique_and_registry_safe():
    """GHCR rejects uppercase in a repository path, and duplicates overwrite."""
    names = [image.name for image in IMAGES]
    assert len(names) == len(set(names))
    for name in names:
        assert name == name.lower()
        assert " " not in name


def test_every_importer_is_published():
    """A new importer that never reaches the registry cannot be deployed.

    Derived from the directory listing rather than a hardcoded count, so adding
    services/importers/<new>/ with a Dockerfile fails this until it is published.
    """
    importer_dirs = {
        path.parent.name
        for path in (REPO_ROOT / "services" / "importers").glob("*/Dockerfile")
    }
    published = {
        image.name.removeprefix("importer-").replace("-", "_")
        for image in IMAGES
        if image.name.startswith("importer-")
    }
    assert importer_dirs == published


def test_production_compose_and_manifest_name_the_same_images():
    """The two ends of the pipeline have to agree on the image names.

    A name in the manifest but not in the compose file is an image nobody runs; a
    name in the compose file but not in the manifest is a `pull` that fails with
    `manifest unknown` on the next release. Neither shows up until a deploy.

    Read with a regular expression rather than a YAML parser so this test needs no
    dependency beyond pytest, which is how CI runs it.
    """
    text = PROD_COMPOSE.read_text(encoding="utf-8")
    in_compose = set(re.findall(r"\$\{QS_IMAGE_PREFIX:-[^}]+\}/([a-z0-9-]+):", text))
    assert in_compose == {image.name for image in IMAGES}


def test_matrix_shape_matches_what_the_workflow_reads():
    """release.yml consumes this with fromJSON into strategy.matrix.include."""
    entries = matrix()
    assert len(entries) == len(IMAGES)
    assert all(set(entry) == {"image", "context", "dockerfile", "cache"} for entry in entries)


def test_every_importer_directory_is_discovered():
    """`--importers` is what CI expands into its test matrix.

    Discovery is by `pyproject.toml`, which is also what `task test:importers`
    looks for, so the local run and the CI run cover the same set. A new importer
    is therefore tested in CI the moment it exists, without a list to remember.
    """
    with_pyproject = {
        path.parent.name
        for path in (REPO_ROOT / "services" / "importers").glob("*/pyproject.toml")
    }
    assert set(importers()) == with_pyproject
    assert importers() == sorted(importers()), "the matrix order must be stable"


def test_ci_reads_the_importer_matrix_instead_of_listing_it():
    """A hardcoded matrix is the drift this discovery exists to remove.

    Reading the workflow as text keeps this dependency-free, the same choice the
    compose test above makes. It asserts on the expansion, not on formatting: if
    somebody replaces it with a literal list again, the `fromJSON` disappears.
    """
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "build_images.py --importers" in text
    assert "fromJSON(needs.importer-list.outputs.importers)" in text


@pytest.mark.parametrize(
    "image",
    [i for i in IMAGES if (REPO_ROOT / i.dockerfile).parent.joinpath("pyproject.toml").is_file()],
    ids=lambda i: i.name,
)
def test_every_declared_path_dependency_is_copied_into_the_image(image):
    """A path dependency the Dockerfile does not copy is a build that cannot resolve it.

    Core declared `qs-shared-schemas` for some time while its Dockerfile copied only
    `packages/proto`, and the image was unbuildable the whole time. Two things kept that
    quiet: nothing in CI builds these images -- the release workflow is the first thing
    that ever does -- and a cached `uv sync` layer from before the dependency existed kept
    answering, so `docker compose up --build` succeeded locally. When the cache finally
    went, it failed with `Distribution not found at: file:///app/packages/shared-schemas`,
    which reads like a broken checkout.

    Cheap to check statically, so it does not need a Docker daemon: the dependency is
    declared in the service's own `pyproject.toml` and the COPY is in its Dockerfile.
    """
    service = (REPO_ROOT / image.dockerfile).parent
    manifest = (service / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (REPO_ROOT / image.dockerfile).read_text(encoding="utf-8")

    # `qs-proto = { path = "../../packages/proto", editable = true }`
    declared = {
        "packages/" + match.group(1)
        for match in re.finditer(r'path\s*=\s*"(?:\.\./)+packages/([^"]+)"', manifest)
    }

    # The dependency's own `pyproject.toml`, specifically. That is the file whose absence
    # produced `Distribution not found`, and asserting on any COPY that merely mentions
    # the path is satisfied by copying only the source tree — which was enough to let this
    # very check pass while the build stayed broken.
    missing = sorted(
        path for path in declared if f"COPY {path}/pyproject.toml" not in dockerfile
    )

    assert not missing, (
        f"{image.dockerfile} does not copy the pyproject.toml of path dependencies its "
        f"own pyproject.toml declares, so `uv sync` inside the image cannot resolve "
        f"them: {missing}"
    )


def test_cache_modes_are_valid_and_bounded():
    """`cache` goes straight into buildx's cache-to, and the budget is 10 GB.

    Only two values mean anything to buildx, and `max` on all thirteen would
    overflow the Actions cache — which is the failure this field exists to avoid,
    so a future edit that sets them all to max should fail here.
    """
    assert {image.cache for image in IMAGES} <= {"min", "max"}
    assert sum(image.cache == "max" for image in IMAGES) <= 4
