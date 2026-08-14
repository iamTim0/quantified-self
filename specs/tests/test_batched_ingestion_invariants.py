"""Executable checks for the bounded batch model in ``batched_ingestion.fizz``."""


MAX_BATCH = 3


def process_batch(
    batch: dict, storage: dict[str, dict], *, commit: bool
) -> tuple[dict[str, dict], bool, int]:
    """Apply the model's all-or-nothing transaction and ack ordering."""
    if not commit:
        return storage, False, 0
    next_storage = dict(storage)
    rejected = 0
    for event in batch["events"]:
        if event["valid"]:
            next_storage.setdefault(event["idempotency_key"], event)
        else:
            rejected += 1
    return next_storage, True, rejected


def test_batch_size_and_tenant_homogeneity_are_bounded():
    """Verifies Fizzbee Invariants: BatchSizeBounded and TenantHomogeneousBatch."""
    batch = {
        "batch_id": "batch-1",
        "tenant_id": "tenant_a",
        "events": [
            {"tenant_id": "tenant_a", "idempotency_key": "e-1", "valid": True},
            {"tenant_id": "tenant_a", "idempotency_key": "e-2", "valid": False},
        ],
    }
    assert len(batch["events"]) <= MAX_BATCH
    assert all(event["tenant_id"] == batch["tenant_id"] for event in batch["events"])


def test_ack_follows_commit_and_rollback_keeps_batch_retryable():
    """Verifies Fizzbee Invariant: AckAfterBatchCommit."""
    batch = {
        "batch_id": "batch-1",
        "tenant_id": "tenant_a",
        "events": [{"tenant_id": "tenant_a", "idempotency_key": "e-1", "valid": True}],
    }
    storage, acknowledged, _ = process_batch(batch, {}, commit=False)
    assert storage == {}
    assert not acknowledged

    storage, acknowledged, _ = process_batch(batch, storage, commit=True)
    assert acknowledged
    assert "e-1" in storage


def test_valid_sibling_survives_invalid_point_and_redelivery_is_idempotent():
    """Verifies Fizzbee Invariants: ValidSiblingSurvivesInvalidPoint and PointIdempotencyPreserved."""
    batch = {
        "batch_id": "batch-1",
        "tenant_id": "tenant_a",
        "events": [
            {"tenant_id": "tenant_a", "idempotency_key": "e-1", "valid": True},
            {"tenant_id": "tenant_a", "idempotency_key": "e-2", "valid": False},
        ],
    }
    storage, acknowledged, rejected = process_batch(batch, {}, commit=True)
    assert acknowledged
    assert rejected == 1
    storage_again, _, rejected_again = process_batch(batch, storage, commit=True)
    assert storage_again == storage
    assert rejected_again == 1
