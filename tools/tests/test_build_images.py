"""Unit tests for tools.build_images.

The point of these is drift: the release workflow builds what this manifest says
and nothing else, so an image missing from it is an image that never gets
published -- silently, because no build fails when a build does not happen.
"""

import re
from pathlib import Path

from tools.build_images import IMAGES, find_unlisted_dockerfiles, matrix

REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"


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
    assert all(set(entry) == {"image", "context", "dockerfile"} for entry in entries)
