"""Authenticated AI chat API backed by Codex and stateless MCP tools."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from analysis.auth import McpPrincipal, resolve_principal
from analysis.codex_app_server import (
    CodexAppServer,
    CodexProtocolError,
    CodexUnavailable,
    ToolContext,
)
from analysis.config import settings
from analysis.core_client import CoreClient, CoreUnavailable
from analysis.mcp_server import MCP_PATH, PROTOCOL_VERSION, mcp_asgi_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])
core_client = CoreClient()

THREAD_ISSUER = "qs-analysis"
THREAD_AUDIENCE = "qs-chat"
THREAD_TOKEN_TYPE = "chat_thread"


class McpCallFailed(CodexProtocolError):
    """An MCP request this service made on the model's behalf was refused.

    Carries the server's machine-readable `code` rather than only its prose, so
    the failure can be logged as one thing and handed to the model as another.
    """

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or "MCP_TOOL_FAILED"
        self.message = message


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatTurnRequest(StrictModel):
    message: str = Field(min_length=1, max_length=settings.CHAT_MAX_MESSAGE_CHARS)
    thread_token: str | None = Field(default=None, max_length=4_096)


class ChatStatus(StrictModel):
    available: bool
    authenticated: bool
    plan_type: str | None
    code: Literal[
        "READY",
        "LOGIN_REQUIRED",
        "CODEX_UNAVAILABLE",
        "SUBSCRIPTION_REQUIRED",
    ]


class DeviceLogin(StrictModel):
    login_id: str
    user_code: str
    verification_url: str


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"


def _authorization(request: Request) -> str:
    value = request.headers.get("Authorization") or ""
    if not value.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer credential")
    return value


async def _authorize(request: Request, principal: McpPrincipal) -> str:
    """Validate role and revocation state for every chat HTTP request."""
    if principal.role not in settings.chat_allowed_roles:
        raise HTTPException(status_code=403, detail="Chat is restricted to configured roles")
    request_id = _request_id(request)
    try:
        valid, code = await core_client.validate_user_session(
            principal.tenant_id,
            user_id=principal.user_id,
            jti=principal.jti,
            issued_at=principal.issued_at,
            request_id=request_id,
        )
    except CoreUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Session validation is temporarily unavailable"
        ) from exc
    if not valid:
        raise HTTPException(status_code=401, detail=code)
    return request_id


class StatelessMcpBridge:
    """Call the mounted MCP endpoint as a fresh 2026-07-28 request each time."""

    def __init__(self) -> None:
        self._next_id = 0

    async def list_dynamic_tools(
        self, authorization: str, request_id: str
    ) -> list[dict[str, Any]]:
        result = await self._request("tools/list", authorization, request_id)
        tools = result.get("tools")
        if not isinstance(tools, list):
            raise CodexProtocolError("MCP returned no tool catalog")
        dynamic: list[dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = tool.get("name")
            description = tool.get("description")
            input_schema = tool.get("inputSchema")
            if isinstance(name, str) and isinstance(description, str) and isinstance(
                input_schema, dict
            ):
                dynamic.append(
                    {
                        "type": "function",
                        "name": name,
                        "description": description,
                        "inputSchema": input_schema,
                    }
                )
        return dynamic

    async def execute(
        self, tool: str, arguments: dict[str, Any], context: ToolContext
    ) -> dict[str, Any]:
        try:
            result = await self._request(
                "tools/call",
                context.authorization,
                context.request_id,
                name=tool,
                params={"name": tool, "arguments": arguments},
            )
            failed = bool(result.get("isError", result.get("is_error", False)))
            payload = result.get("structuredContent", result.get("content", result))
            text = json.dumps(payload, separators=(",", ":"), default=str)
            if failed:
                logger.warning(
                    "[req_id=%s] MCP tool %s returned an error result: %s",
                    context.request_id,
                    tool,
                    text,
                )
            return {
                "success": not failed,
                "contentItems": [{"type": "inputText", "text": text}],
            }
        except (CodexProtocolError, httpx.HTTPError) as exc:
            # Tell the model what was wrong with its call, and tell the operator
            # that it happened. Returning a bare `MCP_TOOL_FAILED` and logging
            # nothing meant a model could not correct a metric name or shorten a
            # window, and an operator reading the logs saw a turn that looked
            # entirely healthy.
            code = getattr(exc, "code", "MCP_TOOL_FAILED")
            message = getattr(exc, "message", str(exc))
            logger.warning(
                "[req_id=%s] MCP tool %s failed: code=%s %s",
                context.request_id,
                tool,
                code,
                message,
            )
            return {
                "success": False,
                "contentItems": [
                    {
                        "type": "inputText",
                        "text": json.dumps(
                            {"code": code, "message": message},
                            separators=(",", ":"),
                        ),
                    }
                ],
            }

    async def _request(
        self,
        method: str,
        authorization: str,
        request_id: str,
        *,
        name: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._next_id += 1
        call_params = dict(params or {})
        call_params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": {
                "name": "quantified-self-chat",
                "version": "1.0.0",
            },
        }
        headers = {
            "Authorization": authorization,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": method,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        if name is not None:
            headers["Mcp-Name"] = name
        transport = httpx.ASGITransport(app=mcp_asgi_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost", timeout=60
        ) as client:
            response = await client.post(
                MCP_PATH,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": self._next_id,
                    "method": method,
                    "params": call_params,
                },
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise CodexProtocolError("MCP returned an invalid response") from exc
        # The error body first, and only then the status. A refused tool call is
        # answered with HTTP 400 *and* a JSON-RPC error carrying the reason, so
        # checking the status first threw the reason away every time -- which is
        # the path every real refusal took.
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            data = error.get("data")
            code = data.get("code") if isinstance(data, dict) else None
            raise McpCallFailed(
                str(error.get("message") or "MCP request failed"),
                code if isinstance(code, str) else None,
            )
        if response.status_code != 200 or not isinstance(body, dict):
            raise CodexProtocolError("MCP request was rejected")
        result = body.get("result")
        if not isinstance(result, dict):
            raise CodexProtocolError("MCP returned no result")
        return result


mcp_bridge = StatelessMcpBridge()
codex = CodexAppServer(mcp_bridge.execute)


def _encode_thread(principal: McpPrincipal, thread_id: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": principal.user_id,
            "tenant_id": principal.tenant_id,
            "thread_id": thread_id,
            "token_type": THREAD_TOKEN_TYPE,
            "iss": THREAD_ISSUER,
            "aud": THREAD_AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=settings.CHAT_THREAD_TTL_MINUTES),
        },
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def _decode_thread(token: str, principal: McpPrincipal) -> str:
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            issuer=THREAD_ISSUER,
            audience=THREAD_AUDIENCE,
            options={
                "require": ["sub", "tenant_id", "thread_id", "token_type", "exp"]
            },
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired chat thread") from exc
    if (
        claims.get("token_type") != THREAD_TOKEN_TYPE
        or claims.get("sub") != principal.user_id
        or claims.get("tenant_id") != principal.tenant_id
    ):
        raise HTTPException(status_code=403, detail="Chat thread belongs to another principal")
    thread_id = claims.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        raise HTTPException(status_code=400, detail="Chat thread has no identifier")
    return thread_id


async def _account_status() -> ChatStatus:
    if not codex.available:
        return ChatStatus(
            available=False,
            authenticated=False,
            plan_type=None,
            code="CODEX_UNAVAILABLE",
        )
    try:
        account = await codex.account()
    except (CodexProtocolError, CodexUnavailable):
        return ChatStatus(
            available=False,
            authenticated=False,
            plan_type=None,
            code="CODEX_UNAVAILABLE",
        )
    account_type = account.get("account_type")
    if account_type is None:
        return ChatStatus(
            available=True,
            authenticated=False,
            plan_type=None,
            code="LOGIN_REQUIRED",
        )
    if account_type != "chatgpt":
        return ChatStatus(
            available=True,
            authenticated=False,
            plan_type=None,
            code="SUBSCRIPTION_REQUIRED",
        )
    persist_auth = getattr(codex, "persist_auth", None)
    if callable(persist_auth):
        await persist_auth()
    return ChatStatus(
        available=True,
        authenticated=True,
        plan_type=str(account.get("plan_type") or "unknown"),
        code="READY",
    )


@router.get("/status", response_model=ChatStatus)
async def get_chat_status(
    request: Request,
    principal: Annotated[McpPrincipal, Depends(resolve_principal)],
) -> ChatStatus:
    """Report Codex availability without disclosing account identity."""
    await _authorize(request, principal)
    return await _account_status()


@router.post("/login", response_model=DeviceLogin)
async def start_chat_login(
    request: Request,
    principal: Annotated[McpPrincipal, Depends(resolve_principal)],
) -> DeviceLogin:
    """Start a ChatGPT subscription device login through Codex."""
    await _authorize(request, principal)
    try:
        return DeviceLogin.model_validate(await codex.start_device_login())
    except (CodexProtocolError, CodexUnavailable) as exc:
        raise HTTPException(status_code=503, detail="ChatGPT login is unavailable") from exc


@router.post("/turn")
async def chat_turn(
    payload: ChatTurnRequest,
    request: Request,
    principal: Annotated[McpPrincipal, Depends(resolve_principal)],
) -> StreamingResponse:
    """Stream one Codex turn whose data reads use the stateless MCP contract.

    Verifies Fizzbee Invariants: ChatRequiresValidPlatformSession,
    ThreadBoundToPlatformPrincipal, ToolCallUsesPlatformPrincipal,
    ChatToolsAreReadOnly, ChatRequestIdReachesCore
    """
    request_id = await _authorize(request, principal)
    status = await _account_status()
    if not status.authenticated:
        raise HTTPException(status_code=409, detail=status.code)
    authorization = _authorization(request)
    try:
        if payload.thread_token is None:
            tools = await mcp_bridge.list_dynamic_tools(authorization, request_id)
            thread_id = await codex.start_thread(tools)
        else:
            thread_id = _decode_thread(payload.thread_token, principal)
    except (CodexProtocolError, CodexUnavailable, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail="Chat could not be started") from exc
    thread_token = _encode_thread(principal, thread_id)

    async def events() -> AsyncIterator[bytes]:
        yield _event({"type": "thread", "thread_token": thread_token})
        try:
            async for event in codex.stream_turn(
                thread_id,
                payload.message.strip(),
                ToolContext(authorization=authorization, request_id=request_id),
            ):
                yield _event(event)
        except (CodexProtocolError, CodexUnavailable):
            yield _event({"type": "error", "code": "CHAT_UNAVAILABLE"})

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


def _event(payload: dict[str, str]) -> bytes:
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()
