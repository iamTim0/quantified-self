from typing import Any

from shared_schemas.metrics import METRIC_CATALOG


def provenance(metric_type: str, provider_value: Any, units: str | None = None) -> dict[str, Any]:
    """The two metadata fields every data point carries about the number that arrived.

    AGENTS.md rule 19: `provider_value` is the number exactly as the provider stated it,
    before any unit conversion, and `units` is the unit it was in. Together they answer
    "why does this differ from the number in the provider's own app" without a
    re-import, and they are what makes a conversion bug recoverable instead of
    destructive — the converted value is derived, the pair below is evidence.

    ``units`` falls back to the unit the registry declares for the metric, which is what
    the value is in once an importer has converted it, and is the honest answer for a
    provider that declares no unit at all. It stays empty for a metric outside the
    catalog, because a namespaced metric's unit is only known at runtime.

    Defined here rather than in each transformer so that "every point carries it" is one
    fact in one place instead of nine copies drifting apart.
    """
    if units is None:
        definition = METRIC_CATALOG.get(metric_type)
        units = definition.unit.value if definition is not None else ""
    return {"provider_value": provider_value, "units": units}
