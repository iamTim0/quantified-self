from weather_importer.transformer import transform


def test_transform() -> None:
    """Verifies Fizzbee Invariant: NoDuplicateRecords."""
    row={"temperature_2m": 21.5, "time": "2026-08-03T00:00:00+00:00"}
    first=transform([row],"tenant","source")[0]; second=transform([row],"tenant","source")[0]
    assert first["tenant_id"] == "tenant" and first["idempotency_key"] == second["idempotency_key"]
