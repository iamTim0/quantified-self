"""Tests mapping to specs/auth_gateway.fizz invariants."""

from typing import Any


def process_gateway_request(headers: dict[str, str], jwt_validator) -> dict[str, Any]:
    """Simulates API Gateway auth & proxy pipeline."""
    auth_header = headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"status_code": 401, "detail": "Missing Bearer token"}

    token = auth_header.split(" ")[1]
    claims = jwt_validator(token)
    if not claims or not claims.get("tenant_id"):
        return {"status_code": 401, "detail": "Invalid or expired JWT token"}

    forwarded_headers = dict(headers)
    forwarded_headers["X-Tenant-ID"] = claims["tenant_id"]

    return {
        "status_code": 200,
        "forwarded_headers": forwarded_headers,
        "tenant_id": claims["tenant_id"],
    }

def test_unauthenticated_requests_blocked():
    """Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked.
    
    Requests without Bearer token or with invalid JWT are blocked at Gateway with 401.
    """
    def mock_validator(token: str) -> dict[str, str] | None:
        if token == "valid_jwt":
            return {"tenant_id": "tenant-123"}
        return None

    # Test 1: No auth header
    res1 = process_gateway_request({}, mock_validator)
    assert res1["status_code"] == 401

    # Test 2: Invalid JWT
    res2 = process_gateway_request({"Authorization": "Bearer bad_token"}, mock_validator)
    assert res2["status_code"] == 401

def test_tenant_header_always_injected():
    """Verifies Fizzbee Invariant: TenantHeaderAlwaysInjected.
    
    Valid requests get X-Tenant-ID header injected prior to downstream routing.
    """
    def mock_validator(token: str) -> dict[str, str] | None:
        if token == "valid_jwt":
            return {"tenant_id": "tenant-789"}
        return None

    res = process_gateway_request({"Authorization": "Bearer valid_jwt"}, mock_validator)
    assert res["status_code"] == 200
    assert "X-Tenant-ID" in res["forwarded_headers"]
    assert res["forwarded_headers"]["X-Tenant-ID"] == "tenant-789"
