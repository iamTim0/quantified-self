"""Authentication, tenant binding, and streaming tests for the AI chat API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import analysis.chat_api as chat_module
import analysis.mcp_server as mcp_module
import jwt
import pytest
from analysis.codex_app_server import ToolContext
from analysis.config import settings
from analysis.main import app
from fastapi.testclient import TestClient

TENANT_A = "22222222-2222-2222-2222-222222222222"
TENANT_B = "33333333-3333-3333-3333-333333333333"
USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "44444444-4444-4444-4444-444444444444"


class FakeCoreClient:
    def __init__(self, valid: bool = True) -> None:
        self.valid = valid
        self.calls: list[tuple[str, str]] = []

    async def validate_user_session(
        self, tenant_id: str, *, request_id: str, **kwargs: Any
    ) -> tuple[bool, str]:
        del kwargs
        self.calls.append((tenant_id, request_id))
        return self.valid, "VALID" if self.valid else "TOKEN_REVOKED"


class FakeMcpBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def list_dynamic_tools(
        self, authorization: str, request_id: str
    ) -> list[dict[str, Any]]:
        self.calls.append((authorization, request_id))
        return [
            {
                "type": "function",
                "name": "list_metrics",
                "description": "List metrics",
                "inputSchema": {"type": "object"},
            }
        ]


class FakeCodex:
    available = True

    def __init__(self, account_type: str | None = "chatgpt") -> None:
        self.account_type = account_type
        self.persisted = False
        self.tools: list[dict[str, Any]] = []
        self.contexts: list[ToolContext] = []

    async def account(self) -> dict[str, Any]:
        return {
            "requires_openai_auth": True,
            "account_type": self.account_type,
            "plan_type": "plus" if self.account_type == "chatgpt" else None,
        }

    async def persist_auth(self) -> bool:
        self.persisted = True
        return True

    async def start_device_login(self) -> dict[str, str]:
        return {
            "login_id": "login-1",
            "user_code": "ABCD-EFGH",
            "verification_url": "https://auth.openai.com/device",
        }

    async def start_thread(self, tools: list[dict[str, Any]]) -> str:
        self.tools = tools
        return "thread-a"

    async def stream_turn(self, thread_id: str, message: str, context: ToolContext):
        assert thread_id == "thread-a"
        assert message
        self.contexts.append(context)
        yield {"type": "delta", "delta": "Your average is 7.5 hours."}
        yield {"type": "done"}


def _token(
    tenant_id: str = TENANT_A,
    user_id: str = USER_A,
    *,
    role: str = "owner",
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "role": role,
            "iss": "qs-core",
            "aud": "qs-api",
            "token_type": "access",
            "jti": f"session-{user_id}",
            "iat": now,
            "exp": now + timedelta(minutes=30),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def _headers(token: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token or _token()}",
        "X-Request-ID": "req_chat_test",
    }


@pytest.fixture(autouse=True)
def _chat_fakes(monkeypatch):
    core = FakeCoreClient()
    codex = FakeCodex()
    mcp = FakeMcpBridge()
    monkeypatch.setattr(chat_module, "core_client", core)
    monkeypatch.setattr(chat_module, "codex", codex)
    monkeypatch.setattr(chat_module, "mcp_bridge", mcp)
    return core, codex, mcp


def test_chat_streams_a_tenant_bound_thread(_chat_fakes) -> None:
    """Verifies Fizzbee Invariants: ThreadBoundToPlatformPrincipal, ChatRequestIdReachesCore"""
    core, codex, mcp = _chat_fakes
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/v1/chat/turn",
            headers=_headers(),
            json={"message": "How has my sleep changed?"},
        )

    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["thread", "delta", "done"]
    assert events[1]["delta"] == "Your average is 7.5 hours."
    assert codex.tools[0]["name"] == "list_metrics"
    assert codex.contexts[0].request_id == "req_chat_test"
    assert mcp.calls[0][1] == "req_chat_test"
    assert core.calls[0] == (TENANT_A, "req_chat_test")


def test_foreign_principal_cannot_continue_thread(_chat_fakes) -> None:
    """Verifies Fizzbee Invariant: ThreadBoundToPlatformPrincipal"""
    with TestClient(app, base_url="http://localhost") as client:
        first = client.post(
            "/api/v1/chat/turn",
            headers=_headers(),
            json={"message": "Start a chat"},
        )
        thread_token = json.loads(first.text.splitlines()[0])["thread_token"]
        rejected = client.post(
            "/api/v1/chat/turn",
            headers=_headers(_token(TENANT_B, USER_B)),
            json={"message": "Continue it", "thread_token": thread_token},
        )

    assert rejected.status_code == 403


def test_revoked_session_is_rejected_before_codex(monkeypatch, _chat_fakes) -> None:
    """Verifies Fizzbee Invariant: ChatRequiresValidPlatformSession"""
    monkeypatch.setattr(chat_module, "core_client", FakeCoreClient(valid=False))
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/chat/status", headers=_headers())
    assert response.status_code == 401


def test_non_configured_role_cannot_use_operator_subscription() -> None:
    """Verifies Fizzbee Invariant: ChatRequiresValidPlatformSession"""
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get(
            "/api/v1/chat/status", headers=_headers(_token(role="member"))
        )
    assert response.status_code == 403


def test_status_exposes_plan_but_not_account_identity(_chat_fakes) -> None:
    """An authenticated account check snapshots the opaque Codex auth cache."""
    _, codex, _ = _chat_fakes
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/chat/status", headers=_headers())
    assert response.json() == {
        "available": True,
        "authenticated": True,
        "plan_type": "plus",
        "code": "READY",
    }
    assert codex.persisted is True


def test_device_login_uses_subscription_flow() -> None:
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/v1/chat/login", headers=_headers())
    assert response.status_code == 200
    assert response.json()["user_code"] == "ABCD-EFGH"


@pytest.mark.asyncio
async def test_dynamic_tool_uses_request_platform_credential(monkeypatch) -> None:
    """Verifies Fizzbee Invariants: ToolCallUsesPlatformPrincipal, ChatToolsAreReadOnly"""
    bridge = chat_module.StatelessMcpBridge()
    seen: dict[str, Any] = {}

    async def fake_request(
        method: str,
        authorization: str,
        request_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        seen.update(
            method=method,
            authorization=authorization,
            request_id=request_id,
            name=kwargs.get("name"),
            params=kwargs.get("params"),
        )
        return {"structuredContent": {"metrics": []}, "isError": False}

    monkeypatch.setattr(bridge, "_request", fake_request)
    result = await bridge.execute(
        "list_metrics",
        {},
        ToolContext(authorization="Bearer platform-token", request_id="req_tool"),
    )

    assert seen == {
        "method": "tools/call",
        "authorization": "Bearer platform-token",
        "request_id": "req_tool",
        "name": "list_metrics",
        "params": {"name": "list_metrics", "arguments": {}},
    }
    assert result["success"] is True


@pytest.mark.asyncio
async def test_chat_discovers_real_sessionless_mcp_tools(monkeypatch) -> None:
    """Verifies Fizzbee Invariants: ChatToolsAreReadOnly, ToolCallUsesPlatformPrincipal"""
    monkeypatch.setattr(mcp_module, "core_client", FakeCoreClient())
    bridge = chat_module.StatelessMcpBridge()

    async with mcp_module.mcp_asgi_app.lifespan():
        tools = await bridge.list_dynamic_tools(
            f"Bearer {_token()}", "req_tool_discovery"
        )

    assert {tool["name"] for tool in tools} == {
        "list_metrics",
        "query_metric_series",
        "analyze_metrics",
        "get_data_quality",
    }
    for tool in tools:
        properties = tool["inputSchema"].get("properties", {})
        assert "tenant_id" not in properties
        assert "user_id" not in properties


@pytest.mark.asyncio
async def test_a_refused_tool_call_reaches_the_model_as_its_own_code(
    monkeypatch,
) -> None:
    """The model must be told what to fix, not that something went wrong.

    A refusal travels as HTTP 400 *with* a JSON-RPC error body, and this bridge
    checked the status before reading that body — so every reason was replaced by
    `MCP_TOOL_FAILED` on the way to the model and logged nowhere at all. A model
    given only that cannot shorten a window or correct a metric name, so it stops
    asking; from the outside the chat simply says it cannot reach the data, and
    the service logs show a turn that looks completely healthy.
    """
    monkeypatch.setattr(mcp_module, "core_client", FakeCoreClient())
    bridge = chat_module.StatelessMcpBridge()

    async with mcp_module.mcp_asgi_app.lifespan():
        result = await bridge.execute(
            "list_metrics",
            {"start": "2020-01-01T00:00:00Z", "end": "2026-08-01T00:00:00Z"},
            ToolContext(authorization=f"Bearer {_token()}", request_id="req_refused"),
        )

    assert result["success"] is False
    payload = json.loads(result["contentItems"][0]["text"])
    assert payload["code"] == "TIME_RANGE_TOO_LARGE"
    assert payload["message"]
