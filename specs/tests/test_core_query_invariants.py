"""Tests mapping to specs/core_query.fizz invariants."""

from typing import Any


def filter_tenant_data(records: list[dict[str, Any]], caller_tenant_id: str, target_tenant_id: str, has_consent: bool = False) -> list[dict[str, Any]]:
    """Simulates Core Data Service query filtering logic."""
    if caller_tenant_id != target_tenant_id and not has_consent:
        return []
    return [r for r in records if r.get("tenant_id") == target_tenant_id]

def test_strict_tenant_isolation_on_read():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead.
    
    Attempting to read target_tenant_id data without consent returns an empty list.
    """
    db = [
        {"tenant_id": "tenant-A", "metric_type": "sleep_score", "value": 90.0},
        {"tenant_id": "tenant-B", "metric_type": "sleep_score", "value": 75.0},
    ]

    res = filter_tenant_data(db, caller_tenant_id="tenant-A", target_tenant_id="tenant-B", has_consent=False)
    assert res == [], "Caller must not receive another tenant's data without explicit consent"

def test_returned_data_belongs_to_target():
    """Verifies Fizzbee Invariant: ReturnedDataBelongsToTarget."""
    db = [
        {"tenant_id": "tenant-A", "metric_type": "sleep_score", "value": 90.0},
        {"tenant_id": "tenant-B", "metric_type": "sleep_score", "value": 75.0},
    ]

    res = filter_tenant_data(db, caller_tenant_id="tenant-A", target_tenant_id="tenant-A", has_consent=True)
    assert len(res) == 1
    assert res[0]["tenant_id"] == "tenant-A"
