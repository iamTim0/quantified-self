from fastapi import FastAPI, Depends, Request, Response
from fastapi.responses import StreamingResponse
import httpx
from gateway.config import settings
from gateway.auth import get_tenant_id_from_token

app = FastAPI(title=settings.SERVICE_NAME)

client = httpx.AsyncClient()

@app.on_event("shutdown")
async def shutdown_event():
    await client.aclose()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

async def proxy_request(request: Request, base_url: str, tenant_id: str):
    url = httpx.URL(path=request.url.path, query=request.url.query.encode("utf-8"))
    
    headers = dict(request.headers)
    headers["X-Tenant-ID"] = tenant_id
    # Remove host header to avoid conflicts
    headers.pop("host", None)
    
    req = client.build_request(
        request.method,
        f"{base_url}{url}",
        headers=headers,
        content=request.stream()
    )
    
    resp = await client.send(req, stream=True)
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers=resp.headers
    )

@app.api_route("/api/v1/data/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_core(request: Request, path: str, tenant_id: str = Depends(get_tenant_id_from_token)):
    return await proxy_request(request, settings.CORE_SERVICE_URL, tenant_id)

@app.api_route("/api/v1/analysis/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy_analysis(request: Request, path: str, tenant_id: str = Depends(get_tenant_id_from_token)):
    return await proxy_request(request, settings.ANALYSIS_SERVICE_URL, tenant_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
