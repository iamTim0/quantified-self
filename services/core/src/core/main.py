from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from core.config import settings
from core.events.consumer import start_consumer
from core.db.tenant import extract_tenant_id_middleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect to NATS JetStream and subscribe
    nc = await start_consumer()
    yield
    await nc.close()

app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)

@app.middleware("http")
async def tenant_middleware(request: Request, call_next):
    extract_tenant_id_middleware(request)
    response = await call_next(request)
    return response

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/v1/data")
async def get_data():
    # Placeholder for data queries
    return {"message": "Data will be served here."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
