"""Apple Health Importer Main Entry Point.

FastAPI Webhook Server & NATS JetStream Publisher for Health Auto Export JSON.
Submits transformed IngestEvents to NATS subject 'qs.ingest.apple_health'.
"""

import asyncio
import json
import logging
import tempfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import nats
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from shared_schemas import FieldReportCollector

from apple_health_importer.auth import extract_presented_key, resolve_api_key
from apple_health_importer.client import (
    bearer_token,
    close_sync_run,
    open_sync_run,
    resolve_session,
    resolve_upload_target,
    send_field_report,
)
from apple_health_importer.config import settings
from apple_health_importer.export_archive import (
    MAX_ARCHIVE_BYTES,
    ArchiveTooLarge,
    ArchiveUnreadable,
    read_export,
)
from apple_health_importer.transformer import transform_health_auto_export_json

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-apple-health] [%(levelname)s] %(message)s",
)

nc_client: nats.NATS | None = None

#: Archive reads still running after their response went out. Held here because the
#: event loop keeps only a weak reference to a task: one that nothing else names can
#: be collected mid-import, which would stop it with the run left open and no error
#: anywhere.
_running_imports: set[asyncio.Task] = set()


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

    # The key names the connector instance. No synthetic fallback: a guessed id
    # would be the second component of every idempotency key derived here, so two
    # phones pushing under different keys would merge into one series.
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

    field_report = FieldReportCollector()
    events = transform_health_auto_export_json(
        payload, tenant_id=tenant_id, source_id=source_id, report=field_report
    )

    # A pushed import used to leave no trace at all: no run, so `_tally` never
    # counted anything and the whole thing was invisible in the history while it
    # happened and afterwards. The count is known here, before publishing, which
    # is what lets the dashboard show real progress rather than a guess.
    sync_run_id = await open_sync_run(
        tenant_id,
        source_id,
        req_id=x_request_id,
        trigger="push",
        points_expected=len(events),
        message=f"Health Auto Export pushed {len(events)} data point(s).",
    )

    published_count = 0
    if nc_client and nc_client.is_connected:
        js = nc_client.jetstream()
        for event in events:
            # AGENTS.md rule 13: correlation id travels with the event, not just the log.
            event["request_id"] = x_request_id
            if sync_run_id:
                event["sync_run_id"] = sync_run_id
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

    # Concurrently: both are post-publish bookkeeping, independent of each other,
    # and the phone is waiting on this response. Sequentially they added two full
    # round trips to every push.
    await asyncio.gather(
        send_field_report(
            tenant_id,
            source_id,
            field_report.build(),
            req_id=x_request_id,
            sync_run_id=sync_run_id,
        ),
        close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="idle",
            message=f"{published_count} data point(s) received from Health Auto Export.",
            points_received=published_count,
        ),
    )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "tenant_id": tenant_id,
            "source_id": source_id,
            "sync_run_id": sync_run_id,
            "total_transformed": len(events),
            "published_count": published_count,
        },
    )


async def _spool_upload(request: Request, limit: int) -> str:
    """Write the uploaded archive to a temporary file, refusing it past ``limit``.

    To disk rather than to memory: an Apple export is a decade of readings and can run
    to gigabytes, and `zipfile` reads a member at a time from a file without ever
    holding the whole archive. Counted while it arrives, because `Content-Length` is a
    claim by the sender.
    """
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"The upload is larger than {limit // (1024 * 1024)} MB.",
                )
            handle.write(chunk)
    except BaseException:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise
    handle.close()

    if total == 0:
        Path(handle.name).unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="The upload was empty.")
    return handle.name


def _drain(points: Iterator[dict], size: int) -> list[dict]:
    """Up to ``size`` more points, parsed in a worker thread rather than on the loop."""
    batch: list[dict] = []
    for _ in range(size):
        try:
            batch.append(next(points))
        except StopIteration:
            break
    return batch


async def _import_archive(
    path: str,
    *,
    tenant_id: str,
    source_id: str,
    sync_run_id: str | None,
    req_id: str,
) -> None:
    """Read the archive, publish what it holds, and close the run out.

    Runs after the response. A whole-history archive takes minutes to read, which is
    longer than a browser should hold a connection open — and the run, opened before
    the response went out, is what the dashboard watches instead. Points go out in
    batches so the parse never stalls the event loop and the count in the interface
    keeps moving while it works.
    """
    report = FieldReportCollector()
    published = 0
    points = read_export(path, tenant_id=tenant_id, source_id=source_id, report=report)
    try:
        js = nc_client.jetstream() if nc_client else None
        while True:
            batch = await asyncio.to_thread(_drain, points, 1000)
            if not batch:
                break
            for event in batch:
                event["request_id"] = req_id
                if sync_run_id:
                    event["sync_run_id"] = sync_run_id
                if js is not None:
                    await js.publish("qs.ingest.apple_health", json.dumps(event).encode("utf-8"))
                published += 1
    except (ArchiveTooLarge, ArchiveUnreadable) as exc:
        await close_sync_run(
            tenant_id, source_id, sync_run_id, req_id=req_id, status="error",
            message=str(exc), points_received=published,
        )
        return
    except Exception as exc:
        logger.error("[req_id=%s] Reading the archive failed after %d points: %s", req_id, published, exc)
        await close_sync_run(
            tenant_id, source_id, sync_run_id, req_id=req_id, status="error",
            message=f"Reading the archive failed after {published} data point(s): {exc}",
            points_received=published,
        )
        return
    finally:
        # The archive is somebody's entire medical history. It exists on this disk
        # only for as long as it takes to read, whatever the outcome — and closing the
        # reader first is what makes the deletion possible at all: a half-consumed
        # generator still holds the ZIP open, and an open file cannot be unlinked on
        # Windows.
        points.close()
        Path(path).unlink(missing_ok=True)

    await send_field_report(tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id)
    await close_sync_run(
        tenant_id, source_id, sync_run_id, req_id=req_id, status="idle",
        message=f"Archive read: {published} data point(s) published.",
        points_received=published,
    )
    logger.info("[req_id=%s] Archive upload finished: %d data point(s) published.", req_id, published)


@app.post("/upload")
@app.post("/api/v1/import/apple-health/upload")
async def upload_export_archive(
    request: Request,
    source_id: str = Query(..., description="The connector this archive belongs to"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_apple_health_upload", alias="X-Request-ID"),
):
    """Accept an `export.zip` from the Health app and publish what it contains.

    The connector id is required rather than derived from the type: a workspace may
    hold several Apple Health connectors, and that id is the second component of every
    idempotency key derived here. Uploading the same archive twice into the same
    connector therefore writes nothing the second time, while uploading it into a
    different one is a deliberate second series.
    """
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)
    target = await resolve_upload_target(tenant_id, source_id, req_id=x_request_id)

    if (nc_client is None or not nc_client.is_connected) and not getattr(
        request.app.state, "testing", False
    ):
        raise HTTPException(
            status_code=503, detail="NATS event broker unavailable. Please retry later."
        )

    path = await _spool_upload(request, MAX_ARCHIVE_BYTES)

    # No `points_expected`: how much an archive holds is not known until it has been
    # read, and the interface counts rather than showing a percentage it invented.
    sync_run_id = await open_sync_run(
        tenant_id,
        target.source_id,
        req_id=x_request_id,
        trigger="upload",
        message="Reading the uploaded Apple Health archive.",
    )

    task = asyncio.create_task(
        _import_archive(
            path,
            tenant_id=tenant_id,
            source_id=target.source_id,
            sync_run_id=sync_run_id,
            req_id=x_request_id,
        )
    )
    _running_imports.add(task)
    task.add_done_callback(_running_imports.discard)

    logger.info(
        "[req_id=%s] Tenant %s: accepted an Apple Health archive for connector %s.",
        x_request_id,
        tenant_id,
        target.source_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "sync_run_id": sync_run_id,
            "source_id": target.source_id,
            "source_type": target.source_type,
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
