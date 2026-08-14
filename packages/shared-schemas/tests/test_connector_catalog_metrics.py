"""The connector cards may not promise a metric the registry does not define.

`test_importer_metric_names.py` guards the *writing* side: no transformer may emit a
name the registry has never heard of. This guards the *promising* side, which had no
check at all and had drifted exactly as far as the documentation once did.

`PROVIDER_CATALOG` in the dashboard's connector modal carries the chips shown on each
provider card. They used to be hand-written display text, in two languages at once —
`["Calories", "Protein", …]` beside `["Steps", "Heart rate", …]` — and several named
nothing any importer produces: `"Consumed products"`, `"Sleep stages"`, `"Workouts"`.
Two of them carried a unit in the name (`"Weight (kg)"`, `"Busy Hours"`), which is the
duplicate AGENTS.md rule 15 exists to prevent — `calendar_busy_hours` is deliberately
not even an alias.

So the field holds canonical keys now and the card resolves each one through
`describeMetric()`, which carries the registry's English and German label. This test is
what keeps it that way: a slug that is not canonical, or that its own provider does not
emit, fails here rather than appearing on a card as a promise nothing keeps.

It reads the TypeScript as text, for the same reason the importer scan reads Python
without importing it: there is no Python that can import a `.tsx`, and the alternative
is a check that lives in the dashboard's own test run and therefore says nothing about
the registry it is supposed to agree with.
"""

import re
from pathlib import Path

import pytest
from shared_schemas.metrics import (
    DYNAMIC_NAMESPACES,
    METRIC_CATALOG,
    UnknownMetricTypeError,
    canonical_metric_type,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MODAL = REPO_ROOT / "apps/dashboard/src/app/components/ConnectorModal.tsx"

#: Every provider that has a card. Below this, a scan that matched nothing would report
#: a healthy catalog, which is the failure mode `test_importer_metric_names.py` was
#: rewritten to remove.
MINIMUM_PROVIDERS = 8


def _catalog_source() -> str:
    """Just the `PROVIDER_CATALOG` literal, so no other `id:` can be mistaken for one."""
    text = MODAL.read_text(encoding="utf-8")
    opening = "export const PROVIDER_CATALOG: ProviderCatalogItem[] = ["
    start = text.find(opening)
    assert start != -1, f"{MODAL.name} no longer declares PROVIDER_CATALOG as expected"
    end = text.find("\n];", start)
    assert end != -1, "PROVIDER_CATALOG is not terminated by a `];` line"
    return text[start + len(opening) : end]


def _entries() -> list[tuple[str, tuple[str, ...]]]:
    """`(provider id, declared metric slugs)` for every card in the catalog."""
    source = _catalog_source()
    found = [
        (provider, tuple(re.findall(r"\"([a-z0-9_]+)\"", block)))
        for provider, block in re.findall(
            r"id:\s*\"([a-z_]+)\".*?supportedMetrics:\s*\[(.*?)\]", source, re.DOTALL
        )
    ]
    # An entry the pattern skipped is invisible rather than failing, so compare against
    # the number of ids actually present.
    declared = len(re.findall(r"^\s{4}id:\s*\"", source, re.MULTILINE))
    assert len(found) == declared, (
        f"matched {len(found)} of {declared} catalog entries; the shape of "
        "PROVIDER_CATALOG changed and this scan no longer reads all of it"
    )
    return found


def _namespace_for(slug: str):
    return next((ns for ns in DYNAMIC_NAMESPACES if slug.startswith(ns.prefix)), None)


def test_the_catalog_is_actually_being_scanned():
    entries = _entries()
    assert len(entries) >= MINIMUM_PROVIDERS, (
        f"expected at least {MINIMUM_PROVIDERS} provider cards, read {len(entries)}"
    )
    assert all(slugs for _, slugs in entries), (
        "a provider card declares no metric slugs, so it is checked for nothing: "
        f"{[provider for provider, slugs in entries if not slugs]}"
    )


@pytest.mark.parametrize(("provider", "slugs"), _entries(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_declared_metric_is_canonical(provider: str, slugs: tuple[str, ...]):
    """A chip names a metric by its registry key, never by an alias or display text."""
    offenders: list[str] = []

    for slug in slugs:
        try:
            canonical = canonical_metric_type(slug)
        except UnknownMetricTypeError:
            offenders.append(f"{slug!r} is not registered")
            continue
        if canonical != slug:
            offenders.append(f"{slug!r} is a legacy alias of {canonical!r}")

    assert not offenders, (
        f"the {provider} card declares metric names the registry does not accept: "
        f"{'; '.join(offenders)}"
    )


@pytest.mark.parametrize(("provider", "slugs"), _entries(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_declared_metric_is_emitted_by_that_provider(provider: str, slugs: tuple[str, ...]):
    """The card is a promise about *this* connector, so the registry has to agree.

    Checked against `sources` rather than merely against the catalog, because a
    canonical key is not enough: `weather_temperature` on the Home Assistant card would
    pass the test above while telling the reader that connecting Home Assistant fills a
    series only the weather importer writes.
    """
    offenders: list[str] = []

    for slug in slugs:
        if (definition := METRIC_CATALOG.get(slug)) is not None:
            if provider not in definition.sources:
                offenders.append(
                    f"{slug!r} is emitted by {definition.sources or '(manual import only)'}"
                )
            continue

        # Not catalogued: legal only under this provider's own dynamic namespace, which
        # is how a provider whose metric set the user's installation decides names
        # examples without inventing catalog entries for them.
        namespace = _namespace_for(slug)
        if namespace is None:
            offenders.append(f"{slug!r} is neither catalogued nor namespaced")
        elif provider not in namespace.sources:
            offenders.append(
                f"{slug!r} sits under the {namespace.prefix!r} namespace, which belongs "
                f"to {namespace.sources or '(manual import only)'}"
            )

    assert not offenders, (
        f"the {provider} card promises metrics that connector does not produce: "
        f"{'; '.join(offenders)}"
    )
