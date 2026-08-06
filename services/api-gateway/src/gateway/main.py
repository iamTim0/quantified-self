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

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.auth import decode_jwt
from gateway.config import settings
from gateway.tracing import (
    RequestTracingMiddleware,
    get_current_request_id,
    setup_tracing_logger,
)

setup_tracing_logger("api-gateway")
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.SERVICE_NAME)

app.add_middleware(RequestTracingMiddleware)

# SECURITY H1: Configure CORS with explicit allowed origins + trycloudflare dev tunnels
_allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=r"https://.*\.trycloudflare\.com",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-ID", "X-Request-ID", "X-Api-Key"],
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
}


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
    # token, so Core needs to see it.
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
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Missing Authorization Bearer header"})

    token = auth_header.split(" ", 1)[1]
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
    # Core re-validates the token itself; the Gateway is no longer the only guard.
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


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_dashboard_ui(path: str, request: Request):
    """Proxy non-API web traffic (e.g. /, /connectors, /_next/*) to Next.js Dashboard UI."""
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

    last_error = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        for base in candidate_bases:
            target_url = f"{base.rstrip('/')}{subpath}"
            try:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=forwarded_headers,
                    params=request.query_params,
                    content=body,
                )
                safe_response_headers = {
                    k: v for k, v in response.headers.items()
                    if k.lower() not in {"transfer-encoding", "connection", "server", "content-encoding", "content-length"}
                }
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=safe_response_headers,
                )
            except httpx.RequestError as e:
                last_error = e
                continue

    raise HTTPException(
        status_code=503,
        detail=f"Dashboard UI unavailable: {last_error!s}",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
