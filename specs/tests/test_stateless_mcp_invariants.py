"""Executable mappings for invariants in specs/stateless_mcp.fizz."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RequestResult:
    authenticated: bool
    token_tenant: str | None
    effective_tenant: str | None
    result_tenant: str | None
    request_id: str
    core_request_id: str | None
    writes: int
    session_id: str | None


def serve_read(
    *,
    token_tenant: str | None,
    model_tenant: str | None,
    request_id: str,
    session_valid: bool = True,
) -> RequestResult:
    """Small executable model of the MCP principal boundary."""
    del model_tenant
    if token_tenant is None:
        return RequestResult(False, None, None, None, request_id, None, 0, None)
    if not session_valid:
        return RequestResult(
            True, token_tenant, token_tenant, None, request_id, None, 0, None
        )
    return RequestResult(
        True,
        token_tenant,
        token_tenant,
        token_tenant,
        request_id,
        request_id,
        0,
        None,
    )


def test_every_request_authenticates_independently() -> None:
    """Verifies Fizzbee Invariant: EveryRequestAuthenticatesIndependently"""
    first = serve_read(token_tenant="tenant_a", model_tenant=None, request_id="req_1")
    second = serve_read(token_tenant=None, model_tenant=None, request_id="req_2")
    assert first.authenticated is True
    assert second.authenticated is False


def test_principal_is_never_model_supplied() -> None:
    """Verifies Fizzbee Invariant: PrincipalIsNeverModelSupplied"""
    result = serve_read(
        token_tenant="tenant_a", model_tenant="tenant_b", request_id="req_1"
    )
    assert result.effective_tenant == "tenant_a"


def test_no_cross_tenant_results() -> None:
    """Verifies Fizzbee Invariant: NoCrossTenantResults"""
    result = serve_read(
        token_tenant="tenant_a", model_tenant="tenant_b", request_id="req_1"
    )
    assert result.result_tenant == result.token_tenant


def test_all_tools_are_read_only() -> None:
    """Verifies Fizzbee Invariant: AllToolsAreReadOnly"""
    result = serve_read(token_tenant="tenant_a", model_tenant=None, request_id="req_1")
    assert result.writes == 0


def test_no_protocol_session_state() -> None:
    """Verifies Fizzbee Invariant: NoProtocolSessionState"""
    result = serve_read(token_tenant="tenant_a", model_tenant=None, request_id="req_1")
    assert result.session_id is None


def test_request_id_reaches_core() -> None:
    """Verifies Fizzbee Invariant: RequestIdReachesCore"""
    result = serve_read(token_tenant="tenant_a", model_tenant=None, request_id="req_1")
    assert result.core_request_id == result.request_id


def test_revoked_mcp_session_is_rejected_immediately() -> None:
    """Verifies Fizzbee Invariant: RevokedMcpSessionRejectedImmediately"""
    result = serve_read(
        token_tenant="tenant_a",
        model_tenant=None,
        request_id="req_1",
        session_valid=False,
    )
    assert result.authenticated is True
    assert result.result_tenant is None
