from calendar_importer.transformer import transform


def test_transform() -> None:
    """Verifies Fizzbee Invariant: NoDuplicateRecords."""
    row={"duration_minutes": 21.5, "start": "2026-08-03T00:00:00+00:00"}
    first=transform([row],"tenant","source")[0]; second=transform([row],"tenant","source")[0]
    assert first["tenant_id"] == "tenant" and first["idempotency_key"] == second["idempotency_key"]
