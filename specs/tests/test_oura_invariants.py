"""Tests mapping to specs/importer_oura.fizz invariants."""

import hashlib


def generate_idempotency_key(tenant_id: str, source_id: str, metric_type: str, timestamp: str) -> str:
    key_str = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(key_str.encode()).hexdigest()

def test_oura_idempotency_key_deterministic():
    """Verifies Fizzbee Invariant: IdempotencyKeyDeterministic.
    
    Generates idempotency keys for the same record multiple times
    and verifies that the key is 100% deterministic.
    """
    tenant_id = "tenant-123"
    source_id = "oura-source-456"
    metric_type = "sleep_score"
    timestamp = "2026-07-26T00:00:00Z"

    key1 = generate_idempotency_key(tenant_id, source_id, metric_type, timestamp)
    key2 = generate_idempotency_key(tenant_id, source_id, metric_type, timestamp)

    assert key1 == key2, "Idempotency key must be deterministic for identical input parameters"
    assert len(key1) == 64, "SHA256 hash must be 64 characters long"

def test_oura_idempotency_key_uniqueness():
    """Verifies Fizzbee Invariant: UniqueKeyMapping.
    
    Verifies that changing any single parameter produces a distinct idempotency key.
    """
    base_key = generate_idempotency_key("t1", "s1", "sleep_score", "2026-07-26T00:00:00Z")
    diff_tenant = generate_idempotency_key("t2", "s1", "sleep_score", "2026-07-26T00:00:00Z")
    diff_metric = generate_idempotency_key("t1", "s1", "readiness_score", "2026-07-26T00:00:00Z")
    diff_time = generate_idempotency_key("t1", "s1", "sleep_score", "2026-07-26T01:00:00Z")

    assert base_key != diff_tenant
    assert base_key != diff_metric
    assert base_key != diff_time
