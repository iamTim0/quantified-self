"""Project the metric registry into the two places that cannot import it.

The dashboard cannot import `shared_schemas`, and hand-maintaining a second catalog
in TypeScript would reintroduce exactly the drift this registry exists to remove — the
UI already had `steps`, `sleep_score` and `readiness_score` hardcoded, none of which any
importer emitted. Documentation drifted the same way, only worse: every page under
`docs/importers/` listed metric names, and most of them named metrics no transformer
had ever produced.

So the registry stays the single source of truth and this script writes both derived
copies, the way `packages/proto/generate.py` writes the generated Python stubs:

* `apps/dashboard/src/app/lib/metrics/catalog.ts` — the whole catalog as TypeScript.
* `docs/metrics.md` — the reference table, between the GENERATED markers. The prose
  around them is hand-written and is left alone.

Run it with `task metrics:generate` after changing `metrics.py`. Both outputs are
committed, and `packages/shared-schemas/tests/test_generated_catalog.py` fails if either
is stale, so a forgotten regeneration is a red test rather than a silently wrong UI or a
documentation page that lies.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from shared_schemas.metrics import (
    CANONICAL_KEYS,
    DYNAMIC_NAMESPACES,
    METRIC_ALIASES,
    METRIC_CATALOG,
)

OUTPUT = REPO_ROOT / "apps" / "dashboard" / "src" / "app" / "lib" / "metrics" / "catalog.ts"
DOCS = REPO_ROOT / "docs" / "metrics.md"

DOCS_BEGIN = "<!-- BEGIN GENERATED METRIC TABLE -->"
DOCS_END = "<!-- END GENERATED METRIC TABLE -->"

#: Category headings for the documentation site, which is English-only. The
#: registry keeps a label per language for the *metrics*, because the dashboard
#: shows those in both; the documentation only ever needs one.
CATEGORY_LABELS = {
    "activity": "Activity",
    "heart": "Heart and circulation",
    "sleep": "Sleep",
    "body": "Body",
    "nutrition": "Nutrition",
    "workout": "Training (endurance)",
    "strength": "Strength training",
    "location": "Location",
    "calendar": "Calendar",
    "environment": "Environment",
    "home": "Smart home",
    "custom": "Own metrics",
}

#: No label map for the aggregation. When the table was German one earned its
#: keep; in English the four enum values already read as words, and renaming them
#: for the table made the one page that documents an aggregation print something
#: no caller may send — `catalog.ts` types it `"average" | "sum" | "last" | "max"`
#: and `GET /api/v1/data/metrics/catalog` serves those. The table prints the value
#: verbatim, which also removes a dict that would `KeyError` on a new enum member.

HEADER = """/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Projected from `packages/shared-schemas/src/shared_schemas/metrics.py` by
 * `packages/shared-schemas/generate_catalog.py`. Change the metric there and run
 * `task metrics:generate`; editing this file only makes the two disagree, which is
 * the failure the registry was introduced to prevent.
 */

export type Aggregation = "average" | "sum" | "last" | "max";

export interface MetricDefinition {
  key: string;
  /** Unit of every value stored under this key. Empty string = carried in metadata. */
  unit: string;
  aggregation: Aggregation;
  category: string;
  labelDe: string;
  labelEn: string;
  sources: string[];
  aliases: string[];
  plausibleMin: number | null;
  plausibleMax: number | null;
  precision: number;
}

export interface MetricNamespace {
  prefix: string;
  category: string;
  labelDe: string;
  labelEn: string;
}
"""

FOOTER = """
/** Canonical key for a possibly legacy name, or null if the registry has neither. */
export function canonicalMetricType(raw: string): string | null {
  const name = (raw ?? "").trim();
  if (name in METRIC_CATALOG) return name;
  if (name in METRIC_ALIASES) return METRIC_ALIASES[name];
  return NAMESPACES.some((ns) => name.startsWith(ns.prefix) && name.length > ns.prefix.length)
    ? name
    : null;
}

/** The definition for a metric name, or null for a namespaced or unknown one. */
export function resolveMetric(raw: string): MetricDefinition | null {
  const name = (raw ?? "").trim();
  if (name in METRIC_CATALOG) return METRIC_CATALOG[name];
  const canonical = METRIC_ALIASES[name];
  return canonical ? METRIC_CATALOG[canonical] : null;
}

/**
 * Something displayable for any metric name — a catalogued definition, a label
 * derived from the namespace suffix, or the raw name for a metric the registry has
 * never heard of (a tenant's older rows survive a catalog change that way).
 */
export function describeMetric(raw: string, locale: "de" | "en" = "de"): {
  label: string;
  unit: string;
  aggregation: Aggregation;
  precision: number;
} {
  const definition = resolveMetric(raw);
  if (definition) {
    return {
      label: locale === "de" ? definition.labelDe : definition.labelEn,
      unit: definition.unit,
      aggregation: definition.aggregation,
      precision: definition.precision,
    };
  }

  const name = (raw ?? "").trim();
  const namespace = NAMESPACES.find(
    (ns) => name.startsWith(ns.prefix) && name.length > ns.prefix.length,
  );
  const readable = (namespace ? name.slice(namespace.prefix.length) : name)
    .replace(/_/g, " ")
    .replace(/\\b\\w/g, (c) => c.toUpperCase())
    .trim();

  return { label: readable || name, unit: "", aggregation: "average", precision: 1 };
}
"""


def _ts(value: object) -> str:
    """JSON is valid TypeScript for everything the catalog contains."""
    return json.dumps(value, ensure_ascii=False)


def render() -> str:
    definitions = []
    for key in CANONICAL_KEYS:
        d = METRIC_CATALOG[key]
        definitions.append(
            "  "
            + _ts(d.key)
            + ": {\n"
            + f"    key: {_ts(d.key)},\n"
            + f"    unit: {_ts(d.unit.value)},\n"
            + f"    aggregation: {_ts(d.aggregation.value)},\n"
            + f"    category: {_ts(d.category.value)},\n"
            + f"    labelDe: {_ts(d.label_de)},\n"
            + f"    labelEn: {_ts(d.label_en)},\n"
            + f"    sources: {_ts(list(d.sources))},\n"
            + f"    aliases: {_ts(list(d.aliases))},\n"
            + f"    plausibleMin: {_ts(d.plausible_min)},\n"
            + f"    plausibleMax: {_ts(d.plausible_max)},\n"
            + f"    precision: {_ts(d.precision)},\n"
            + "  },"
        )

    namespaces = [
        "  {\n"
        + f"    prefix: {_ts(ns.prefix)},\n"
        + f"    category: {_ts(ns.category.value)},\n"
        + f"    labelDe: {_ts(ns.label_de)},\n"
        + f"    labelEn: {_ts(ns.label_en)},\n"
        + "  },"
        for ns in DYNAMIC_NAMESPACES
    ]

    aliases = [f"  {_ts(alias)}: {_ts(canonical)}," for alias, canonical in sorted(METRIC_ALIASES.items())]

    return "\n".join(
        [
            HEADER,
            "export const METRIC_CATALOG: Record<string, MetricDefinition> = {",
            *definitions,
            "};",
            "",
            "/** Legacy or provider-specific name -> canonical key. */",
            "export const METRIC_ALIASES: Record<string, string> = {",
            *aliases,
            "};",
            "",
            "/** Prefixes under which unregistered metric names are legal. */",
            "export const NAMESPACES: MetricNamespace[] = [",
            *namespaces,
            "];",
            "",
            "/** Canonical keys, in registry order. */",
            "export const CANONICAL_KEYS: string[] = Object.keys(METRIC_CATALOG);",
            FOOTER,
        ]
    )


def render_docs_table() -> str:
    """The reference table for docs/metrics.md, grouped by category."""
    by_category: dict[str, list] = {}
    for key in CANONICAL_KEYS:
        by_category.setdefault(METRIC_CATALOG[key].category.value, []).append(METRIC_CATALOG[key])

    lines: list[str] = []
    for category, definitions in by_category.items():
        lines.append(f"### {CATEGORY_LABELS.get(category, category)}")
        lines.append("")
        lines.append("| `metric_type` | Meaning | Unit | Aggregation | Sources | Former names |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for d in definitions:
            unit = f"`{d.unit.value}`" if d.unit.value else "—"
            sources = ", ".join(d.sources) if d.sources else "—"
            aliases = ", ".join(f"`{a}`" for a in d.aliases) if d.aliases else "—"
            lines.append(
                f"| `{d.key}` | {d.label_en} | {unit} | "
                f"`{d.aggregation.value}` | {sources} | {aliases} |"
            )
        lines.append("")

    lines.append("### Dynamic namespaces")
    lines.append("")
    lines.append("| Prefix | Meaning | Sources |")
    lines.append("| --- | --- | --- |")
    for ns in DYNAMIC_NAMESPACES:
        sources = ", ".join(ns.sources) if ns.sources else "manual import"
        lines.append(f"| `{ns.prefix}` | {ns.label_en} | {sources} |")

    return "\n".join(lines)


def _splice_docs() -> bool:
    """Replace the generated block in docs/metrics.md. Returns True if it changed."""
    if not DOCS.exists():
        raise SystemExit(f"{DOCS} is missing; the hand-written prose has to exist first")

    text = DOCS.read_text(encoding="utf-8")
    try:
        head, rest = text.split(DOCS_BEGIN, 1)
        _, tail = rest.split(DOCS_END, 1)
    except ValueError:
        raise SystemExit(
            f"{DOCS} must contain the {DOCS_BEGIN} / {DOCS_END} markers"
        ) from None

    updated = f"{head}{DOCS_BEGIN}\n\n{render_docs_table()}\n\n{DOCS_END}{tail}"
    if updated == text:
        return False
    DOCS.write_text(updated, encoding="utf-8", newline="\n")
    return True


def _write(path: Path, rendered: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == rendered:
        return False
    # newline="\n" so the checked-in file is byte-identical whatever the platform,
    # which is what lets the staleness test compare text rather than parse TypeScript.
    path.write_text(rendered, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    for path, changed in (
        (OUTPUT, _write(OUTPUT, render())),
        (DOCS, _splice_docs()),
    ):
        verb = "wrote" if changed else "unchanged"
        print(f"{verb}: {path.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
