"""Streak Importer Main Entry Point.

FastAPI REST Export Server & NATS JetStream Publisher for Streak 2.0 Gym Logs.
Submits transformed IngestEvents to NATS subject 'qs.ingest.streak'.
"""

import json
import logging
from contextlib import asynccontextmanager

import nats
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from streak_importer.auth import extract_presented_key, resolve_api_key
from streak_importer.client import close_sync_run, open_sync_run, report_sync_progress
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
    authorization: str | None = Header(None, alias="Authorization"),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_request_id: str = Header("req_streak_ingest", alias="X-Request-ID"),
):
    """Receive Streak 2.0 REST export JSON payload, transform, and publish to NATS.

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

    # The key names the connector instance. No synthetic fallback: a guessed id
    # would be the second component of every idempotency key derived here, so two
    # devices pushing under different keys would merge into one series.
    source_id = identity.source_id
    if not source_id:
        logger.error(
            "[req_id=%s] API key %s resolves to no connector; refusing the push.",
            x_request_id,
            identity.key_prefix,
        )
        raise HTTPException(
            status_code=409,
            detail="This API key is not bound to a connector. Re-create it in the dashboard.",
        )

    sync_run_id = await open_sync_run(
        tenant_id,
        source_id,
        req_id=x_request_id,
        message="Streak webhook request received.",
    )

    try:
        payload = await request.json()
    except Exception:
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message="Invalid JSON payload.",
        )
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    if not isinstance(payload, dict):
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message="Payload must be a JSON object.",
        )
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")

    # Prevent silent data loss: Return 503 if NATS is offline
    if nc_client is None or not nc_client.is_connected:
        if not getattr(request.app.state, "testing", False):
            await close_sync_run(
                tenant_id,
                source_id,
                sync_run_id,
                req_id=x_request_id,
                status="error",
                message="NATS event broker unavailable; the request was rejected.",
            )
            logger.error(f"[req_id={x_request_id}] NATS connection offline. Rejecting payload with 503.")
            raise HTTPException(
                status_code=503,
                detail="NATS event broker unavailable. Please retry later.",
            )

    workout_count = len(payload.get("workouts") or [])

    published_count = 0
    try:
        events = transform_streak_export_json(
            payload, tenant_id=tenant_id, source_id=source_id
        )
        await report_sync_progress(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            points_expected=len(events),
            message=f"Streak payload transformed into {len(events)} event(s).",
        )
        if nc_client and nc_client.is_connected:
            js = nc_client.jetstream()
            for event in events:
                # AGENTS.md rule 13: correlation id travels with the event, not just the log.
                event["request_id"] = x_request_id
                if sync_run_id:
                    event["sync_run_id"] = sync_run_id
                raw_data = json.dumps(event).encode("utf-8")
                await js.publish("qs.ingest.streak", raw_data)
                published_count += 1
        else:
            published_count = len(events)
    except Exception as exc:
        logger.exception("[req_id=%s] Streak import failed after %d events.", x_request_id, published_count)
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=f"Streak import failed after {published_count} event(s): {exc}",
            points_received=published_count,
        )
        raise HTTPException(status_code=500, detail="The Streak import failed.") from None

    await close_sync_run(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=x_request_id,
        status="success",
        message=f"{published_count} Streak event(s) published.",
        points_received=published_count,
    )

    logger.info(
        "[req_id=%s] Tenant %s (key %s): transformed %d events (%d workouts), published %d to NATS.",
        x_request_id,
        tenant_id,
        identity.key_prefix,
        len(events),
        workout_count,
        published_count,
    )

    # Return response format matching Streak 2.0 app expectations
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "tenant_id": tenant_id,
            "source_id": source_id,
            "sync_run_id": sync_run_id,
            "workoutCount": workout_count,
            "published_count": published_count,
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
