"""No importer may write a metric name the registry does not define.

This reads the transformer sources rather than importing them, on purpose. Each importer
lives in its own virtualenv (AGENTS.md: isolated `pyproject.toml` per service), so a test
that imported all eight would only ever run under whichever environment happened to have
them all — which is none of them. Scanning the source has the further advantage of
catching a name that only appears on a branch no fixture exercises.

The failure this prevents is the one that made the registry necessary: every importer
inventing its own vocabulary, with nothing in the repository able to say so.
"""

import re
from pathlib import Path

import pytest
from shared_schemas.metrics import (
    UnknownMetricTypeError,
    canonical_metric_type,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
IMPORTERS = REPO_ROOT / "services" / "importers"

#: `metric_type: "x"`, `metric_type = "x"` and `"metric_type": "x"`. Only literals —
#: a name built at runtime cannot be checked here, and the transformers no longer
#: build any (yazio's `f"{meal_category}_calories"` was the last one).
_LITERAL = re.compile(r"""metric_type["']?\s*[:=]\s*["']([A-Za-z0-9_]+)["']""")


def _transformers() -> list[Path]:
    return sorted(IMPORTERS.rglob("transformer.py"))


def test_the_importers_are_actually_being_scanned():
    """A regex that matches nothing would make every test below pass silently."""
    found = _transformers()
    assert len(found) >= 8, f"expected every importer to have a transformer, found {found}"
    assert any(_LITERAL.findall(p.read_text(encoding="utf-8")) for p in found)


@pytest.mark.parametrize("transformer", _transformers(), ids=lambda p: p.parent.parent.parent.name)
def test_every_metric_literal_is_canonical(transformer: Path):
    source = transformer.read_text(encoding="utf-8")
    offenders: list[str] = []

    for name in sorted(set(_LITERAL.findall(source))):
        try:
            canonical = canonical_metric_type(name)
        except UnknownMetricTypeError:
            offenders.append(f"{name!r} is not registered")
            continue
        if canonical != name:
            offenders.append(f"{name!r} is a legacy alias of {canonical!r}")

    assert not offenders, (
        f"{transformer.relative_to(REPO_ROOT).as_posix()} writes metric names the "
        f"registry does not accept: {'; '.join(offenders)}"
    )
