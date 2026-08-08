"""API Gateway Service Entry Point.

Acts as the entry point for all external client traffic.
Validates JWT tokens, injects X-Tenant-ID and X-Request-ID headers, and proxies HTTP requests
to downstream microservices (Core Data Service, Analysis Service).

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
- RequestCorrelationTracing
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from gateway.auth import decode_jwt
from gateway.config import settings
from gateway.tracing import (
    RequestTracingMiddleware,
    get_current_request_id,
    setup_tracing_logger,
)

setup_tracing_logger("api-gateway")
logger = logging.getLogger(__name__)


# The Gateway verifies the same tokens Core signs, so it holds the same secret
# and inherits the same problem: the deployment compose file used to default it
# to a value printed in this repository, so forgetting to set it did not fail --
# it silently verified real sessions against a value anyone can read.
#
# Duplicated rather than imported from Core: the two services share no code by
# design (AGENTS.md rule 6), and the check is a dozen lines.
PUBLISHED_DEFAULTS = {
    "dev-secret-key-quantified-self-2026",
    "dev-secret-shared-encryption-key-qs-2026",
    "dev-encryption-key-quantified-self-2026",
}
PRODUCTION_ENVIRONMENTS = {"production", "prod", "staging"}


def audit_secrets() -> None:
    """Refuse to serve in production with a published JWT_SECRET; warn otherwise.

    Raises:
        RuntimeError: in a production-like ENVIRONMENT.
    """
    if settings.JWT_SECRET and settings.JWT_SECRET not in PUBLISHED_DEFAULTS:
        return

    detail = (
        "JWT_SECRET is unset or a value published in this repository. Generate "
        'one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
    )
    if settings.ENVIRONMENT.strip().lower() in PRODUCTION_ENVIRONMENTS:
        raise RuntimeError(f"api-gateway refuses to start: {detail}")
    logger.warning("[api-gateway] insecure default in use: %s", detail)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Checked at startup, not at import.

    ENVIRONMENT defaults to production here, deliberately -- this is the edge and
    it should be strict by default. Running the check at import time would
    therefore refuse to even load the module in the test suite, which imports it
    and never starts it.
    """
    audit_secrets()
    yield


app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)

app.add_middleware(RequestTracingMiddleware)

# SECURITY H1: Configure CORS with explicit allowed origins + trycloudflare dev tunnels
_allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.trycloudflare\.com",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Tenant-ID",
        "X-Request-ID",
        "X-Api-Key",
        # Sent by the dashboard on every state-changing request; without it in
        # this list the browser's preflight fails before the request is made.
        "X-CSRF-Token",
    ],
)

# SECURITY C3: Log warning if running in dev mode
if settings.ENVIRONMENT.lower() == "dev":
    logger.warning(
        "[WARN] Gateway running in DEVELOPMENT mode -- auth is relaxed. "
        "Set ENVIRONMENT=production for strict JWT enforcement."
    )

# SECURITY: Warn if JWT secret looks ephemeral
if settings.JWT_SECRET.startswith("INSECURE-EPHEMERAL-"):
    logger.warning(
        "[WARN] JWT_SECRET is auto-generated and ephemeral. "
        "Tokens will NOT survive restarts. Set JWT_SECRET env var."
    )

# SECURITY M5: Only forward safe headers to downstream services
_SAFE_FORWARD_HEADERS = {
    "content-type",
    "accept",
    "accept-encoding",
    "accept-language",
    "user-agent",
    "x-request-id",
    # Browser sessions live in httpOnly cookies, so Core needs the Cookie header
    # and the CSRF header that pairs with it. Without these the Gateway would
    # strip the credential and every browser request would 401.
    "cookie",
    "x-csrf-token",
}

# Name of the access-token cookie set by Core. Duplicated rather than imported:
# the Gateway shares no code with Core by design (AGENTS.md rule 6). Keep in step
# with core.security.cookies.ACCESS_COOKIE.
ACCESS_COOKIE = "qs_access"

# Response headers that belong to the hop, not the payload.
_HOP_BY_HOP_HEADERS = {"transfer-encoding", "connection", "server", "content-encoding"}


def _session_credential(request: Request) -> str | None:
    """The caller's access token, from the Authorization header or session cookie.

    The header takes precedence: it is how services, scripts and tests
    authenticate. The cookie is the browser path.
    """
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            return token
    return request.cookies.get(ACCESS_COOKIE)


def _relay_response(upstream: httpx.Response) -> Response:
    """Copy an upstream response through, preserving *every* Set-Cookie header.

    Building the header dict with a comprehension silently collapses repeated
    keys, and a login sets three cookies -- so two of them were being dropped.
    Set-Cookie is therefore re-appended one value at a time.
    """
    headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS and k.lower() != "set-cookie"
    }
    headers["X-Request-ID"] = get_current_request_id()

    out = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=headers,
    )
    for cookie in upstream.headers.get_list("set-cookie"):
        out.headers.append("set-cookie", cookie)
    return out


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.get("/api/v1/auth/config")
async def get_auth_config():
    """Return auth configuration flags such as allow_registration."""
    return {"allow_registration": settings.ALLOW_REGISTRATION}


@app.api_route("/api/v1/auth/{path:path}", methods=["GET", "POST", "PUT"])
async def proxy_auth_service(
    path: str,
    request: Request,
):
    """Proxy HTTP requests to Core Auth Service."""
    if path == "signup" and not settings.ALLOW_REGISTRATION:
        raise HTTPException(
            status_code=403,
            detail="Registration is currently disabled by system administrator.",
        )

    target_url = f"{settings.CORE_SERVICE_URL}/api/v1/auth/{path}"

    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS
    }
    # /logout, /me and /change-password authenticate against the caller's own
    # token, so Core needs to see it. (The Cookie header rides along via
    # _SAFE_FORWARD_HEADERS for browser sessions.)
    if auth_header := request.headers.get("Authorization"):
        forwarded_headers["Authorization"] = auth_header
    forwarded_headers["X-Request-ID"] = get_current_request_id()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forwarded_headers,
                params=request.query_params,
                content=await request.body(),
            )
            return _relay_response(response)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Core Data Service unavailable: {e!s}",
            )


@app.api_route("/api/v1/ingest/apple-health", methods=["POST"])
async def proxy_apple_health_ingest(request: Request):
    """Proxy Apple Health Push / Webhook ingest requests to Apple Health Importer microservice."""
    target_url = f"{settings.APPLE_HEALTH_IMPORTER_URL}/ingest"
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS or k.lower() in {"x-tenant-id", "x-api-key"}
    }
    forwarded_headers["X-Request-ID"] = get_current_request_id()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forwarded_headers,
                params=request.query_params,
                content=await request.body(),
            )
            safe_response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in {"transfer-encoding", "connection", "server"}
            }
            safe_response_headers["X-Request-ID"] = get_current_request_id()
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=safe_response_headers,
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Apple Health Importer Service unavailable: {e!s}",
            )


@app.api_route("/api/v1/ingest/streak", methods=["HEAD", "GET", "POST"])
async def proxy_streak_ingest(request: Request):
    """Proxy Streak 2.0 REST Export ingest & server check requests to Streak Importer microservice."""
    target_url = f"{settings.STREAK_IMPORTER_URL}/ingest"
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS or k.lower() in {"x-tenant-id", "x-api-key"}
    }
    forwarded_headers["X-Request-ID"] = get_current_request_id()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forwarded_headers,
                params=request.query_params,
                content=await request.body(),
            )
            safe_response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in {"transfer-encoding", "connection", "server"}
            }
            safe_response_headers["X-Request-ID"] = get_current_request_id()
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=safe_response_headers,
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Streak Importer Service unavailable: {e!s}",
            )


@app.api_route("/api/v1/analysis/{path:path}", methods=["GET"])
async def proxy_analysis_service(path: str, request: Request):
    """Proxy read-only analysis requests to the Analysis Service.

    The analyses used to live in Core and be served from `/api/v1/data/analysis/*`.
    They now run in their own service which reads through Core's gRPC API, so the
    edge has to route to it (AGENTS.md rule 3).

    GET only: everything the Analysis Service exposes is a computation over data
    it does not own, so there is nothing here to POST to.
    """
    token = _session_credential(request)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing session cookie or Authorization Bearer header"},
        )

    try:
        claims = decode_jwt(token)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    header_tenant = request.headers.get("X-Tenant-ID")
    if header_tenant and header_tenant != claims["tenant_id"]:
        return JSONResponse(
            status_code=403,
            content={"detail": "X-Tenant-ID does not match authenticated tenant"},
        )

    forwarded_headers = {
        k: v for k, v in request.headers.items() if k.lower() in _SAFE_FORWARD_HEADERS
    }
    # The Analysis Service re-validates this itself and derives the tenant from
    # it. A cookie-authenticated browser sends no Authorization header, so the
    # token is forwarded explicitly here -- unlike the Core proxy, where doing so
    # would make a cookie request look header-authenticated and skip CSRF. This
    # route is GET-only, so there is no CSRF decision to get wrong.
    forwarded_headers["Authorization"] = f"Bearer {token}"
    forwarded_headers["X-Tenant-ID"] = claims["tenant_id"]
    forwarded_headers["X-Request-ID"] = get_current_request_id()

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=f"{settings.ANALYSIS_SERVICE_URL}/api/v1/analysis/{path}",
                headers=forwarded_headers,
                params=request.query_params,
            )
            return _relay_response(response)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Analysis Service unavailable: {e!s}",
            )


@app.api_route("/api/v1/data/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_core_service(
    path: str,
    request: Request,
):
    """Proxy HTTP requests to Core Data Service with X-Tenant-ID & X-Request-ID injection.

    ``/api/v1/internal/*`` is deliberately **not** proxied. Those endpoints hand out
    decrypted connector credentials and resolve API keys; exposing them through the
    public edge let any logged-in user read their provider secrets in cleartext.
    Importers reach Core directly over the internal network with a service credential.
    """
    tenant_id = request.headers.get("X-Tenant-ID")
    token = _session_credential(request)

    if not token:
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing session cookie or Authorization Bearer header"},
        )

    try:
        claims = decode_jwt(token)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    claim_tenant_id = claims["tenant_id"]
    if tenant_id and tenant_id != claim_tenant_id:
        return JSONResponse(status_code=403, content={"detail": "X-Tenant-ID does not match authenticated tenant"})
    tenant_id = claim_tenant_id

    target_url = f"{settings.CORE_SERVICE_URL}/api/v1/data/{path}"

    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS
    }
    # Core re-validates the credential itself; the Gateway is no longer the only
    # guard. Pass the Authorization header on when there was one -- but do not
    # synthesise one from the cookie, or a cookie-authenticated request would
    # arrive at Core looking header-authenticated and skip its CSRF check.
    if auth_header := request.headers.get("Authorization"):
        forwarded_headers["Authorization"] = auth_header
    forwarded_headers["X-Tenant-ID"] = tenant_id
    forwarded_headers["X-Request-ID"] = get_current_request_id()

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forwarded_headers,
                params=request.query_params,
                content=await request.body(),
            )
            return _relay_response(response)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=503,
                detail=f"Core Data Service unavailable: {e!s}",
            )


@app.websocket("/_next/{path:path}")
async def proxy_next_websocket(websocket: WebSocket, path: str):
    """Proxy Next.js dev server WebSockets (HMR) to Dashboard UI."""
    await websocket.accept()
    candidate_bases = ["ws://dashboard:3000", "ws://host.docker.internal:3000", "ws://127.0.0.1:3000"]
    query_str = f"?{websocket.query_params}" if websocket.query_params else ""

    for base in candidate_bases:
        target_ws_url = f"{base}/_next/{path}{query_str}"
        try:
            async with websockets.connect(target_ws_url) as client_ws:
                async def forward_to_client():
                    try:
                        async for msg in client_ws:
                            await websocket.send_text(msg)
                    except Exception:
                        pass

                async def forward_to_target():
                    try:
                        while True:
                            msg = await websocket.receive_text()
                            await client_ws.send(msg)
                    except Exception:
                        pass

                await asyncio.gather(forward_to_client(), forward_to_target())
                return
        except Exception:
            continue

    await websocket.close()


# The UI proxy holds a response open for as long as the page takes to finish, so
# it cannot share the 10s budget the API calls use. Connecting still has to be
# quick -- that is what the fallback loop below depends on to move on to the next
# candidate host -- but reading has no deadline: a streamed document legitimately
# trickles, and a first-request compile in `next dev` takes as long as it takes.
_UI_TIMEOUT = httpx.Timeout(10.0, read=None)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_dashboard_ui(path: str, request: Request):
    """Proxy non-API web traffic (e.g. /, /connectors, /_next/*) to Next.js Dashboard UI.

    Streamed through rather than buffered. Reading the whole upstream response
    before sending any of it defeats streaming SSR — the browser gets a complete
    document in one piece rather than progressively — and holds every response in
    memory here in full.

    It does *not* fix `next dev` behind this proxy, which was the reason the
    change was attempted. Measured afterwards: the proxied document is byte-
    identical to the direct one, every chunk is byte-identical, and the HMR socket
    connects — and the page still never hydrates, with nothing logged. So
    buffering was not the cause. Whatever is, it is not in the bytes, and the
    browser tests continue to run against a production build.
    """
    subpath = f"/{path}" if path else "/"
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"connection", "content-length"}
    }
    if "host" in request.headers:
        forwarded_headers["x-forwarded-host"] = request.headers["host"]
        forwarded_headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto", "https")

    body = await request.body()

    candidate_bases = [settings.DASHBOARD_URL]
    for fallback in ["http://dashboard:3000", "http://host.docker.internal:3000", "http://127.0.0.1:3000"]:
        if fallback not in candidate_bases:
            candidate_bases.append(fallback)

    # Not `async with`: the client has to outlive this function, because the
    # response body is still being read from it while Starlette sends it on.
    # Closing it here would truncate every response to whatever had arrived.
    client = httpx.AsyncClient(timeout=_UI_TIMEOUT)
    last_error: Exception | None = None

    for base in candidate_bases:
        target_url = f"{base.rstrip('/')}{subpath}"
        upstream_request = client.build_request(
            method=request.method,
            url=target_url,
            headers=forwarded_headers,
            params=request.query_params,
            content=body,
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.RequestError as e:
            # Nothing has been sent to the browser yet, so trying the next
            # candidate host is still safe. Once bytes are flowing it would not be.
            last_error = e
            continue

        # `aiter_bytes` yields decoded bytes, so the upstream's own
        # Content-Encoding and Content-Length no longer describe what we send.
        safe_response_headers = {
            k: v for k, v in upstream.headers.items()
            if k.lower() not in {"transfer-encoding", "connection", "server", "content-encoding", "content-length"}
        }
        return StreamingResponse(
            upstream.aiter_bytes(),
            status_code=upstream.status_code,
            headers=safe_response_headers,
            # Runs after the last byte reaches the client, whether the response
            # completed or the client went away.
            background=BackgroundTask(_close_upstream, upstream, client),
        )

    await client.aclose()
    raise HTTPException(
        status_code=503,
        detail=f"Dashboard UI unavailable: {last_error!s}",
    )


async def _close_upstream(upstream: httpx.Response, client: httpx.AsyncClient) -> None:
    """Release the streamed response and the client that owns its connection."""
    try:
        await upstream.aclose()
    finally:
        await client.aclose()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
