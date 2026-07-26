"""API Gateway Service Entry Point.

Acts as the entry point for all external client traffic.
Validates JWT tokens, injects X-Tenant-ID headers, and proxies HTTP requests
to downstream microservices (Core Data Service, Analysis Service).

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
"""

import logging

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.auth import create_dev_jwt, decode_jwt
from gateway.config import settings

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.SERVICE_NAME)

# SECURITY H1: Configure CORS with explicit allowed origins
_allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-ID"],
)

# SECURITY C3: Log warning if running in dev mode
if settings.ENVIRONMENT.lower() == "dev":
    logger.warning(
        "⚠️  Gateway running in DEVELOPMENT mode — auth is relaxed. "
        "Set ENVIRONMENT=production for strict JWT enforcement."
    )

# SECURITY: Warn if JWT secret looks ephemeral
if settings.JWT_SECRET.startswith("INSECURE-EPHEMERAL-"):
    logger.warning(
        "⚠️  JWT_SECRET is auto-generated and ephemeral. "
        "Tokens will NOT survive restarts. Set JWT_SECRET env var."
    )

# SECURITY M5: Only forward safe headers to downstream services
_SAFE_FORWARD_HEADERS = {
    "content-type",
    "accept",
    "accept-encoding",
    "accept-language",
    "user-agent",
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
        raise HTTPException(status_code=404, detail="Not found")
    token = create_dev_jwt(tenant_id=tenant_id)
    return {
        "tenant_id": tenant_id,
        "token": token,
        "token_type": "Bearer",
    }


@app.api_route("/api/v1/data/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_core_service(
    path: str,
    request: Request,
):
    """Proxy HTTP requests to Core Data Service with X-Tenant-ID injection."""
    auth_header = request.headers.get("Authorization")
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

    target_url = f"{settings.CORE_SERVICE_URL}/api/v1/data/{path}"

    # SECURITY M5: Whitelist headers — don't blindly forward cookies, auth, X-Forwarded-*
    forwarded_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() in _SAFE_FORWARD_HEADERS
    }
    forwarded_headers["X-Tenant-ID"] = tenant_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.request(
                method=request.method,
                url=target_url,
                headers=forwarded_headers,
                params=request.query_params,
                content=await request.body(),
            )
            # Don't forward hop-by-hop or server-internal headers back
            safe_response_headers = {
                k: v for k, v in response.headers.items()
                if k.lower() not in {"transfer-encoding", "connection", "server"}
            }
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
