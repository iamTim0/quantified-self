"""Validation and replay helpers for deferred metric ingestion.

The registry remains the authority for catalogued names. Tenant rules may select a
catalogued target or create a ``custom_`` name with runtime metadata, but they never
alter the registry itself.
"""

import re
from dataclasses import dataclass
from typing import Any, Literal

from shared_schemas.metrics import (
    Aggregation,
    Cadence,
    MetricCategory,
    MetricDefinition,
    MetricUnit,
    UnknownMetricTypeError,
    canonical_metric_type,
    convert,
    describe,
)

MappingAction = Literal["map", "adopt", "discard", "keep"]


@dataclass(frozen=True)
class ValidatedMapping:
    """A validated rule ready to persist and apply."""

    action: MappingAction
    raw_metric_type: str
    target_metric_type: str | None
    source_unit: MetricUnit | None
    target_unit: MetricUnit | None
    aggregation: Aggregation | None
    cadence: Cadence | None


def custom_metric_definition(mapping: ValidatedMapping) -> MetricDefinition:
    """Build the tenant-local definition declared by an ``adopt`` rule."""
    if (
        mapping.action != "adopt"
        or mapping.target_metric_type is None
        or mapping.target_unit is None
        or mapping.aggregation is None
        or mapping.cadence is None
    ):
        raise ValueError("only a complete adopt mapping has a custom metric definition")
    label = mapping.target_metric_type.removeprefix("custom_").replace("_", " ").title()
    return MetricDefinition(
        key=mapping.target_metric_type,
        unit=mapping.target_unit,
        aggregation=mapping.aggregation,
        category=MetricCategory.CUSTOM,
        label_de=label,
        label_en=label,
        cadence=mapping.cadence,
    )


def _unit(value: str | None, *, field: str, required: bool) -> MetricUnit | None:
    if value is None or not value.strip():
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        unit = MetricUnit(value)
    except ValueError:
        raise ValueError(f"{field} must be a registered metric unit") from None
    if unit is MetricUnit.RUNTIME:
        raise ValueError(f"{field} must declare a concrete unit")
    return unit


def validate_mapping(
    *,
    raw_metric_type: str,
    action: MappingAction,
    target_metric_type: str | None = None,
    source_unit: str | None = None,
    target_unit: str | None = None,
    aggregation: str | None = None,
    cadence: str | None = None,
) -> ValidatedMapping:
    """Validate a user decision without changing the shared registry.

    ``map`` can target only a canonical catalogued metric. ``adopt`` is the only
    action allowed to use a dynamic namespace, and it must declare its unit,
    aggregation and cadence so the resulting point is interpretable.
    """
    raw = raw_metric_type.strip()
    if not raw or len(raw) > 128:
        raise ValueError("raw_metric_type must contain 1 to 128 characters")

    if action in {"discard", "keep"}:
        if any(value not in (None, "") for value in (target_metric_type, source_unit, target_unit, aggregation, cadence)):
            raise ValueError(f"{action} rules do not accept target or unit settings")
        return ValidatedMapping(action, raw, None, None, None, None, None)

    if not target_metric_type:
        raise ValueError(f"{action} rules require target_metric_type")
    target = target_metric_type.strip()
    if len(target) > 128:
        raise ValueError("target_metric_type must contain at most 128 characters")

    source = _unit(source_unit, field="source_unit", required=True)
    if action == "map":
        try:
            canonical = canonical_metric_type(target)
        except UnknownMetricTypeError:
            raise ValueError("map target_metric_type must be a catalogued metric") from None
        if canonical != target:
            raise ValueError("map target_metric_type must use the canonical registry name")
        definition = describe(target)
        target_from_registry = definition.unit
        if target_from_registry is MetricUnit.RUNTIME:
            raise ValueError("map target_metric_type must not be a dynamic metric")
        supplied_target = _unit(target_unit, field="target_unit", required=False)
        if supplied_target is not None and supplied_target is not target_from_registry:
            raise ValueError("target_unit must match the registry unit for the mapped metric")
        # Validate the conversion while the user is looking at the form, rather than
        # storing a rule that will fail only when the first historical row is replayed.
        try:
            convert(1.0, source, target_from_registry)
        except ValueError as exc:
            raise ValueError(str(exc)) from None
        return ValidatedMapping(action, raw, target, source, target_from_registry, None, None)

    if action != "adopt":
        raise ValueError(f"unsupported mapping action: {action}")
    if not target.startswith("custom_") or target == "custom_":
        raise ValueError("adopt target_metric_type must be a non-empty custom_ name")
    if re.fullmatch(r"custom_[a-z0-9_]+", target) is None:
        raise ValueError("adopt target_metric_type may contain only lowercase letters, digits and underscores")
    adopted_unit = _unit(target_unit, field="target_unit", required=True)
    try:
        adopted_aggregation = Aggregation(aggregation or "")
    except ValueError:
        raise ValueError("adopt aggregation must be average, sum, last or max") from None
    try:
        adopted_cadence = Cadence(cadence or "")
    except ValueError:
        raise ValueError("adopt cadence must be daily, continuous or event") from None
    try:
        convert(1.0, source, adopted_unit)
    except ValueError as exc:
        raise ValueError(str(exc)) from None
    return ValidatedMapping(
        action,
        raw,
        target,
        source,
        adopted_unit,
        adopted_aggregation,
        adopted_cadence,
    )


def replay_value(
    value: float | None,
    metadata: dict[str, Any] | None,
    mapping: ValidatedMapping,
) -> tuple[float | None, dict[str, Any]]:
    """Convert one quarantined value and preserve provider provenance."""
    copied = dict(metadata or {})
    copied["mapped_from"] = mapping.raw_metric_type
    copied["mapping_action"] = mapping.action
    if mapping.action == "adopt":
        if mapping.aggregation is None or mapping.cadence is None:
            raise ValueError("an adopted metric must declare aggregation and cadence")
        copied["aggregation"] = mapping.aggregation.value
        copied["cadence"] = mapping.cadence.value
    if value is None:
        copied.setdefault("provider_value", None)
        copied["units"] = mapping.source_unit.value if mapping.source_unit else copied.get("units", "")
        return None, copied
    if mapping.source_unit is None or mapping.target_unit is None:
        raise ValueError("a replayable mapping must declare source and target units")
    # The quarantine metadata carries the provider's original representation. Keep
    # that evidence when possible; ``value`` is a database float and may have already
    # normalised an integer spelling by the time replay runs.
    copied["provider_value"] = copied.get("provider_value", value)
    copied["units"] = mapping.source_unit.value
    converted = convert(float(value), mapping.source_unit, mapping.target_unit)
    return converted, copied
