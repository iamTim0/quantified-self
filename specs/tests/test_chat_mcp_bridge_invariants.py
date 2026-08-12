"""Executable mappings for invariants in specs/chat_mcp_bridge.fizz."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatResult:
    principal: str | None
    thread_principal: str | None
    accepted: bool
    tool_principal: str | None
    request_id: str
    core_request_id: str | None
    writes: int


def serve_chat(
    *,
    principal: str | None,
    thread_principal: str | None,
    session_valid: bool,
    invoke_tool: bool,
    request_id: str,
) -> ChatResult:
    accepted = bool(
        principal
        and session_valid
        and (thread_principal is None or thread_principal == principal)
    )
    tool_called = accepted and invoke_tool
    return ChatResult(
        principal=principal,
        thread_principal=thread_principal or (principal if accepted else None),
        accepted=accepted,
        tool_principal=principal if tool_called else None,
        request_id=request_id,
        core_request_id=request_id if tool_called else None,
        writes=0,
    )


def test_chat_requires_valid_platform_session() -> None:
    """Verifies Fizzbee Invariant: ChatRequiresValidPlatformSession"""
    result = serve_chat(
        principal="tenant_a:user_a",
        thread_principal=None,
        session_valid=False,
        invoke_tool=False,
        request_id="req_1",
    )
    assert result.accepted is False


def test_thread_is_bound_to_platform_principal() -> None:
    """Verifies Fizzbee Invariant: ThreadBoundToPlatformPrincipal"""
    result = serve_chat(
        principal="tenant_b:user_b",
        thread_principal="tenant_a:user_a",
        session_valid=True,
        invoke_tool=False,
        request_id="req_1",
    )
    assert result.accepted is False


def test_tool_call_uses_platform_principal() -> None:
    """Verifies Fizzbee Invariant: ToolCallUsesPlatformPrincipal"""
    result = serve_chat(
        principal="tenant_a:user_a",
        thread_principal="tenant_a:user_a",
        session_valid=True,
        invoke_tool=True,
        request_id="req_1",
    )
    assert result.tool_principal == result.principal


def test_chat_tools_are_read_only() -> None:
    """Verifies Fizzbee Invariant: ChatToolsAreReadOnly"""
    result = serve_chat(
        principal="tenant_a:user_a",
        thread_principal=None,
        session_valid=True,
        invoke_tool=True,
        request_id="req_1",
    )
    assert result.writes == 0


def test_chat_request_id_reaches_core() -> None:
    """Verifies Fizzbee Invariant: ChatRequestIdReachesCore"""
    result = serve_chat(
        principal="tenant_a:user_a",
        thread_principal=None,
        session_valid=True,
        invoke_tool=True,
        request_id="req_2",
    )
    assert result.core_request_id == result.request_id
