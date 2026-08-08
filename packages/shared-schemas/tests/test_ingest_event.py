"""Tests for the metric validation on IngestEvent."""

import pytest
from pydantic import ValidationError
from shared_schemas.events import IngestEvent

TENANT = "00000000-0000-0000-0000-000000000001"


def _event(metric_type: str) -> IngestEvent:
    return IngestEvent(
        tenant_id=TENANT,
        source_id="src",
        metric_type=metric_type,
        timestamp="2026-08-08T12:00:00Z",
        value=1.0,
        idempotency_key="a" * 64,
        source_type="whoop",
    )


def test_a_canonical_metric_is_accepted():
    assert _event("heart_rate_resting").metric_type == "heart_rate_resting"


def test_a_namespaced_metric_is_accepted():
    assert _event("home_assistant_kitchen_temp").metric_type == "home_assistant_kitchen_temp"


def test_an_unknown_metric_is_rejected():
    with pytest.raises(ValidationError, match="Unknown metric_type"):
        _event("puls")


def test_an_alias_is_rejected_rather_than_rewritten():
    """The transformer already hashed the name into the idempotency key.

    Rewriting `resting_heart_rate` to `heart_rate_resting` here would store the point
    under a name its key does not describe, so the same reading re-imported through a
    corrected transformer would land a second time instead of deduplicating.
    """
    with pytest.raises(ValidationError, match="legacy alias"):
        _event("resting_heart_rate")
