"""Apple Health Importer Main Entry Point.

FastAPI Webhook Server & NATS JetStream Publisher for Health Auto Export JSON.
Submits transformed IngestEvents to NATS subject 'qs.ingest.apple_health'.
"""

import json
import logging
import uuid
from contextlib import asynccontextmanager

import nats
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from apple_health_importer.auth import extract_presented_key, resolve_api_key
from apple_health_importer.config import settings
from apple_health_importer.transformer import transform_health_auto_export_json

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-apple-health] [%(levelname)s] %(message)s",
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
    title="Apple Health Importer Service",
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


@app.post("/ingest")
@app.post("/api/v1/ingest/apple-health")
async def ingest_health_auto_export_payload(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_request_id: str = Header("req_apple_health_ingest", alias="X-Request-ID"),
):
    """Receive Health Auto Export JSON push payload, transform, and publish to NATS.

    The tenant is derived from the API key alone. ``X-Tenant-ID`` is accepted only
    to be checked for contradiction — a caller that names a different tenant than
    its key owns is rejected rather than silently corrected.
    """
    identity = await resolve_api_key(
        extract_presented_key(authorization, x_api_key), req_id=x_request_id
    )
    tenant_id = identity.tenant_id

    if x_tenant_id and x_tenant_id != tenant_id:
        logger.warning(
            "[req_id=%s] Rejected ingest: X-Tenant-ID contradicts API key %s.",
            x_request_id,
            identity.key_prefix,
        )
        raise HTTPException(
            status_code=403, detail="X-Tenant-ID does not match the authenticated API key."
        )

    source_id = identity.source_id or str(
        uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:{settings.SOURCE_TYPE}")
    )

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")

    # Prevent silent data loss: Return 503 if NATS is unavailable so webhook client retries delivery
    if nc_client is None or not nc_client.is_connected:
        # Check if running in test environment where NATS is mocked/disabled
        if not getattr(request.app.state, "testing", False):
            logger.error(f"[req_id={x_request_id}] NATS connection offline. Rejecting payload with 503.")
            raise HTTPException(
                status_code=503,
                detail="NATS event broker unavailable. Please retry later.",
            )

    events = transform_health_auto_export_json(payload, tenant_id=tenant_id, source_id=source_id)

    published_count = 0
    if nc_client and nc_client.is_connected:
        js = nc_client.jetstream()
        for event in events:
            # AGENTS.md rule 13: correlation id travels with the event, not just the log.
            event["request_id"] = x_request_id
            raw_data = json.dumps(event).encode("utf-8")
            await js.publish("qs.ingest.apple_health", raw_data)
            published_count += 1
    else:
        # Testing dry-run mode
        published_count = len(events)

    logger.info(
        "[req_id=%s] Tenant %s (key %s): transformed %d events, published %d to NATS.",
        x_request_id,
        tenant_id,
        identity.key_prefix,
        len(events),
        published_count,
    )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "tenant_id": tenant_id,
            "source_id": source_id,
            "total_transformed": len(events),
            "published_count": published_count,
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
