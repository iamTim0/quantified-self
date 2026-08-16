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
from shared_schemas import health_payload
from shared_schemas.field_report import FieldReportCollector

from streak_importer.auth import extract_presented_key, resolve_api_key
from streak_importer.client import (
    close_sync_run,
    open_sync_run,
    report_sync_progress,
    send_field_report,
)
from streak_importer.config import settings
from streak_importer.transformer import transform_streak_export_json

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-streak] [%(levelname)s] %(message)s",
)

nc_client: nats.NATS | None = None
PUBLISH_CONCURRENCY = 32


async def _publish_events(js, events: list[dict], *, req_id: str, sync_run_id: str | None) -> int:
    """Publish bounded batches concurrently; JetStream acks still apply backpressure."""
    published = 0
    for offset in range(0, len(events), PUBLISH_CONCURRENCY):
        batch = events[offset : offset + PUBLISH_CONCURRENCY]
        tasks = []
        for event in batch:
            event["request_id"] = req_id
            if sync_run_id:
                event["sync_run_id"] = sync_run_id
            tasks.append(js.publish("qs.ingest.streak", json.dumps(event).encode("utf-8")))
        await asyncio.gather(*tasks)
        published += len(batch)
    return published


@asynccontextmanager
async def lifespan(app: FastAPI):
    global nc_client
    logger.info("Connecting to NATS...")
    try:
        nc_client = await nats.connect(settings.NATS_URL)
        logger.info("Connected to NATS JetStream successfully.")
    except Exception as exc:  # noqa: BLE001 - service starts degraded and retries by deployment
        logger.warning("Could not connect to NATS on startup (%s)", type(exc).__name__)

    yield

    if nc_client and not nc_client.is_closed:
        await nc_client.close()
        logger.info("NATS connection closed.")


app = FastAPI(
    title="Streak Gym Log Importer Service",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check(response: Response):
    nats_connected = nc_client is not None and nc_client.is_connected
    response.status_code = 200 if nats_connected else 503
    response.headers["Cache-Control"] = "no-store"
    return health_payload(
        settings.SERVICE_NAME,
        status="ok" if nats_connected else "degraded",
        nats_connected=nats_connected,
    )


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
    except Exception:  # noqa: BLE001 - malformed request bodies have one public response
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
    if (
        (nc_client is None or not nc_client.is_connected)
        and not getattr(request.app.state, "testing", False)
    ):
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message="NATS event broker unavailable; the request was rejected.",
        )
        logger.error(
            "[req_id=%s] NATS connection offline. Rejecting payload with 503.",
            x_request_id,
        )
        raise HTTPException(
            status_code=503,
            detail="NATS event broker unavailable. Please retry later.",
        )

    workout_count = len(payload.get("workouts") or [])

    published_count = 0
    field_report = FieldReportCollector()
    try:
        events = transform_streak_export_json(
            payload, tenant_id=tenant_id, source_id=source_id, report=field_report
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
            published_count = await _publish_events(
                js, events, req_id=x_request_id, sync_run_id=sync_run_id
            )
        else:
            published_count = len(events)
    except Exception as exc:  # noqa: BLE001 - provider payload failures need a safe response
        logger.error(
            "[req_id=%s] Streak import failed after %d events (%s).",
            x_request_id,
            published_count,
            type(exc).__name__,
        )
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=(
                f"Streak import failed after {published_count} event(s) "
                f"({type(exc).__name__})."
            ),
            points_received=published_count,
        )
        raise HTTPException(status_code=500, detail="The Streak import failed.") from None

    # Filed after the events, and before the run is closed: a report that named
    # fields for an import that then failed would describe a payload nothing stored.
    await send_field_report(
        tenant_id,
        source_id,
        field_report.build(),
        req_id=x_request_id,
        sync_run_id=sync_run_id,
    )

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
