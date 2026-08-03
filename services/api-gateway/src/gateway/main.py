"""API Gateway Service Entry Point.

Acts as the entry point for all external client traffic.
Validates JWT tokens, injects X-Tenant-ID and X-Request-ID headers, and proxies HTTP requests
to downstream microservices (Core Data Service, Analysis Service).

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
- RequestCorrelationTracing
"""

import logging

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.auth import create_dev_jwt, decode_jwt
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


@app.get("/api/v1/auth/dev-token")
async def get_dev_token(tenant_id: str = Query("00000000-0000-0000-0000-000000000001")):
    """Dev utility endpoint to generate signed JWT tokens for dev tenants.

    SECURITY L1: Only available in dev mode.
    """
    if settings.ENVIRONMENT.lower() != "dev":
        raise HTTPException(
            status_code=403,
            detail="Dev token endpoint is disabled in production.",
        )
    token = create_dev_jwt(tenant_id=tenant_id)
    return {"access_token": token, "token_type": "bearer", "tenant_id": tenant_id}


@app.api_route("/api/v1/auth/{path:path}", methods=["POST"])
async def proxy_auth_service(
    path: str,
    request: Request,
):
    """Proxy HTTP requests to Core Auth Service."""
    if path == "dev-token":
        return await get_dev_token()

    target_url = f"{settings.CORE_SERVICE_URL}/api/v1/auth/{path}"

    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS
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


@app.api_route("/api/v1/internal/data/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
@app.api_route("/api/v1/data/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_core_service(
    path: str,
    request: Request,
):
    """Proxy HTTP requests to Core Data Service with X-Tenant-ID & X-Request-ID injection."""
    tenant_id = request.headers.get("X-Tenant-ID")
    auth_header = request.headers.get("Authorization")

    if not tenant_id:
        if not auth_header or not auth_header.startswith("Bearer "):
            if settings.ENVIRONMENT.lower() == "dev":
                tenant_id = "00000000-0000-0000-0000-000000000001"
            else:
                return JSONResponse(status_code=401, content={"detail": "Missing Authorization Bearer header"})
        else:
            token = auth_header.split(" ", 1)[1]
            try:
                claims = decode_jwt(token)
                tenant_id = claims["tenant_id"]
            except HTTPException as e:
                return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    prefix = "internal/data" if request.url.path.startswith("/api/v1/internal/data") else "data"
    target_url = f"{settings.CORE_SERVICE_URL}/api/v1/{prefix}/{path}"

    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS
    }
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
