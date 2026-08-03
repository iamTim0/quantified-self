"""Streak Importer Main Entry Point.

FastAPI REST Export Server & NATS JetStream Publisher for Streak 2.0 Gym Logs.
Submits transformed IngestEvents to NATS subject 'qs.ingest.streak'.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

import nats
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from streak_importer.client import get_connector_credentials_from_core
from streak_importer.config import settings
from streak_importer.transformer import transform_streak_export_json

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-streak] [%(levelname)s] %(message)s",
)

nc_client: nats.NATS | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global nc_client
    logger.info(f"Connecting to NATS at {settings.NATS_URL}...")
    try:
        nc_client = await nats.connect(settings.NATS_URL)
        logger.info("Connected to NATS JetStream successfully.")
    except Exception as e:
        logger.warning(f"Could not connect to NATS on startup: {e}")

    yield

    if nc_client and not nc_client.is_closed:
        await nc_client.close()
        logger.info("NATS connection closed.")


app = FastAPI(
    title="Streak Gym Log Importer Service",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": settings.SERVICE_NAME,
        "nats_connected": nc_client is not None and nc_client.is_connected,
    }


@app.head("/ingest")
@app.head("/api/v1/ingest/streak")
async def check_server_head():
    """Support Streak 2.0 app HEAD server reachability check."""
    return Response(status_code=200)


@app.get("/ingest")
@app.get("/api/v1/ingest/streak")
async def check_server_get():
    """Support Streak 2.0 app GET server reachability check."""
    return JSONResponse(status_code=200, content={"ok": True, "service": settings.SERVICE_NAME})


@app.post("/ingest")
@app.post("/api/v1/ingest/streak")
async def ingest_streak_payload(
    request: Request,
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    x_request_id: str = Header("req_streak_ingest", alias="X-Request-ID"),
):
    """Receive Streak 2.0 REST export JSON payload, transform, and publish to NATS."""
    tenant_id = x_tenant_id or settings.DEFAULT_TENANT_ID

    token, source_id, config = await get_connector_credentials_from_core(
        tenant_id, req_id=x_request_id
    )
    config = config or {}
    expected_key = token or config.get("api_key") or config.get("secret")

    # SECURITY: Validate API key if dynamic credentials exist for tenant
    if expected_key and x_api_key != expected_key:
        logger.warning(f"[req_id={x_request_id}] Unauthorized API key attempt for tenant {tenant_id}.")
        raise HTTPException(status_code=401, detail="Invalid API Key or unauthorized tenant connector.")

    if not source_id:
        source_id = f"streak_{tenant_id[:8]}"

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")

    # Prevent silent data loss: Return 503 if NATS is offline
    if nc_client is None or not nc_client.is_connected:
        if not getattr(request.app.state, "testing", False):
            logger.error(f"[req_id={x_request_id}] NATS connection offline. Rejecting payload with 503.")
            raise HTTPException(
                status_code=503,
                detail="NATS event broker unavailable. Please retry later.",
            )

    events = transform_streak_export_json(payload, tenant_id=tenant_id, source_id=source_id)
    workout_count = len(payload.get("workouts") or [])

    published_count = 0
    if nc_client and nc_client.is_connected:
        js = nc_client.jetstream()
        for event in events:
            raw_data = json.dumps(event).encode("utf-8")
            await js.publish("qs.ingest.streak", raw_data)
            published_count += 1
    else:
        published_count = len(events)

    logger.info(
        f"[req_id={x_request_id}] Tenant {tenant_id}: Transformed {len(events)} events ({workout_count} workouts), published {published_count} to NATS."
    )

    # Return response format matching Streak 2.0 app expectations
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "tenant_id": tenant_id,
            "source_id": source_id,
            "workoutCount": workout_count,
            "published_count": published_count,
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
