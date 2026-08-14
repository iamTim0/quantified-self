"""Executable checks for the tenant-isolation model in ``tenant_isolation.fizz``."""


def query(
    records: list[dict[str, str]],
    *,
    caller_tenant_id: str | None,
    target_tenant_id: str,
    shares: set[tuple[str, str]],
) -> list[dict[str, str]]:
    """Apply the same authorization order as a tenant-scoped Core query."""
    if not caller_tenant_id:
        raise ValueError("tenant_id is required")
    if caller_tenant_id != target_tenant_id and (
        caller_tenant_id,
        target_tenant_id,
    ) not in shares:
        return []
    return [row for row in records if row.get("tenant_id") == target_tenant_id]


def test_query_returns_only_own_data():
    """Verifies Fizzbee Invariant: NoUnauthorizedAccess."""
    records = [
        {"tenant_id": "tenant_a", "value": "1"},
        {"tenant_id": "tenant_b", "value": "2"},
    ]

    assert query(
        records,
        caller_tenant_id="tenant_a",
        target_tenant_id="tenant_b",
        shares=set(),
    ) == []


def test_shared_data_accessible():
    """Verifies Fizzbee Invariant: ExplicitShareRequired."""
    records = [{"tenant_id": "tenant_b", "value": "2"}]

    assert query(
        records,
        caller_tenant_id="tenant_a",
        target_tenant_id="tenant_b",
        shares={("tenant_a", "tenant_b")},
    ) == records


def test_share_revocation_blocks_access():
    """Verifies Fizzbee Invariant: ShareRevocationImmediate."""
    records = [{"tenant_id": "tenant_b", "value": "2"}]
    shares = {("tenant_a", "tenant_b")}
    assert query(
        records,
        caller_tenant_id="tenant_a",
        target_tenant_id="tenant_b",
        shares=shares,
    ) == records

    shares.remove(("tenant_a", "tenant_b"))
    assert query(
        records,
        caller_tenant_id="tenant_a",
        target_tenant_id="tenant_b",
        shares=shares,
    ) == []


def test_query_without_tenant_id_fails():
    """Verifies Fizzbee Invariant: TenantIdAlwaysPresent."""
    try:
        query([], caller_tenant_id=None, target_tenant_id="tenant_a", shares=set())
    except ValueError as exc:
        assert str(exc) == "tenant_id is required"
    else:
        raise AssertionError("tenantless query must be rejected")
