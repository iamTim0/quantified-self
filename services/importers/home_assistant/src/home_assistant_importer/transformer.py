"""Transform Home Assistant state rows to canonical ingestion events.

The previous transformer emitted a single metric literally named
``home_assistant`` for every entity, so a temperature sensor and a humidity sensor
collapsed into the same series. It also fell back to ``now()`` when a row had no
timestamp, producing a fresh ``idempotency_key`` — and therefore a duplicate row —
on every sync.

Each entity now gets its own metric name derived from its ``entity_id``, and rows
without a usable timestamp or a numeric state are skipped.

Home Assistant is the reason the metric registry has dynamic namespaces at all: every
installation exposes a different set of entities, so the catalog cannot enumerate them
in advance. ``home_assistant_`` is registered as a namespace
(packages/shared-schemas/src/shared_schemas/metrics.py), which makes these names legal
without pretending they carry a known unit -- the unit comes from the entity's
``unit_of_measurement`` attribute and travels in the event metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from shared_schemas import idempotency_key
from shared_schemas.metrics import UnknownMetricTypeError, canonical_metric_type

logger = logging.getLogger(__name__)

SOURCE_TYPE = "home_assistant"
NAMESPACE = "home_assistant_"

# States that are not measurements but do carry meaning as 1/0.
BOOLEAN_STATES = {"on": 1.0, "off": 0.0, "home": 1.0, "not_home": 0.0, "open": 1.0, "closed": 0.0}
# States that mean "no reading", not "zero".
UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}


#: SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4, defined once
#: in `shared_schemas`. An alias rather than a wrapper: a wrapper would be a fifth
#: identical docstring to keep in step, and its `timestamp: str` annotation would hide
#: that the shared function also takes a `datetime`.
generate_idempotency_key = idempotency_key


def metric_name(entity_id: str) -> str:
    """``sensor.living_room_temp`` -> ``home_assistant_living_room_temp``."""
    tail = entity_id.split(".", 1)[-1] if "." in entity_id else entity_id
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in tail).strip("_").lower()
    return f"{NAMESPACE}{cleaned}" if cleaned else f"{NAMESPACE}unknown"


def _normalise_timestamp(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _numeric_state(raw: Any) -> float | None:
    """Coerce a Home Assistant state to a number, or None if it is not a reading."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)

    text = str(raw).strip().lower()
    if text in UNAVAILABLE_STATES:
        return None
    if text in BOOLEAN_STATES:
        return BOOLEAN_STATES[text]
    try:
        return float(text)
    except ValueError:
        return None


def transform(
    records: list[dict[str, Any]], tenant_id: str, source_id: str
) -> list[dict[str, Any]]:
    """One event per state change that carries a numeric reading."""
    events: list[dict[str, Any]] = []

    for record in records:
        timestamp = _normalise_timestamp(
            record.get("last_changed")
            or record.get("last_updated")
            or record.get("timestamp")
        )
        if timestamp is None:
            continue

        value = _numeric_state(record.get("state", record.get("value")))
        if value is None:
            continue

        entity_id = str(record.get("entity_id") or "")
        # An explicit metric_type on the row is a name from outside, so it is checked
        # against the registry: either it is a catalogued metric or it sits under a
        # namespace. Anything else is dropped rather than stored uninterpretable.
        try:
            metric = canonical_metric_type(
                str(record.get("metric_type") or metric_name(entity_id))
            )
        except UnknownMetricTypeError:
            logger.warning(
                "Skipping unregistered metric_type %r for entity %r; prefix it with %r "
                "to store it as a Home Assistant metric",
                record.get("metric_type"),
                entity_id,
                NAMESPACE,
            )
            continue

        attributes = record.get("attributes") or {}

        events.append(
            {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "source_type": SOURCE_TYPE,
                "metric_type": metric,
                "timestamp": timestamp,
                "value": value,
                "metadata": {
                    "source_type": SOURCE_TYPE,
                    "entity_id": entity_id,
                    "unit": attributes.get("unit_of_measurement"),
                    "friendly_name": attributes.get("friendly_name"),
                },
                "idempotency_key": generate_idempotency_key(
                    tenant_id, source_id, metric, timestamp
                ),
            }
        )

    return events
