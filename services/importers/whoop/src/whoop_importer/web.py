"""HTTP surface of the WHOOP importer: uploading the emailed export.

Whoop mails an account's whole history as a ZIP of CSVs, which is the only way in
that needs no OAuth application. Parsing it belongs here rather than in Core for the
same reason polling does: what a provider's columns mean is this service's knowledge,
and Core owns the database, not the vendors (AGENTS.md rules 1 and 3). The points it
produces travel the ordinary way, over NATS.

The connection to the broker is opened by ``main``; this module reads it off
``app.state`` so that the service is one process with one NATS client rather than two
halves that each hold their own.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from shared_schemas import FieldReportCollector

from whoop_importer.config import settings
from whoop_importer.core_client import (
    bearer_token,
    close_sync_run,
    open_sync_run,
    resolve_session,
    resolve_upload_target,
    send_field_report,
)
from whoop_importer.export_archive import (
    EXPORT_METRICS,
    MAX_ARCHIVE_BYTES,
    ArchiveTooLarge,
    ArchiveUnreadable,
    read_export,
)
from whoop_importer.transformer import transform_whoop_records

logger = logging.getLogger(__name__)

app = FastAPI(title="WHOOP Importer Service", version="0.1.0")

#: Imports still publishing after their response went out. See the comment where
#: they are added: an unreferenced task can be collected while it runs.
_running_imports: set[asyncio.Task] = set()


@app.get("/health")
async def health_check():
    nc = getattr(app.state, "nats_client", None)
    return {
        "status": "ok",
        "service": settings.SERVICE_NAME,
        "nats_connected": nc is not None and nc.is_connected,
    }


async def _read_capped_body(request: Request, limit: int) -> bytes:
    """The request body, refused as soon as it exceeds ``limit``.

    Counted while it arrives rather than checked afterwards: `Content-Length` is a
    claim by the sender, and reading the whole thing to find out it was too big is
    the cost the limit exists to avoid.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"The upload is larger than {limit // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_export(data: bytes, tenant_id: str, source_id: str) -> tuple[list[dict[str, Any]], FieldReportCollector]:
    """Every data point in an export archive, plus what its columns turned into.

    Synchronous on purpose — it is CPU work over a decompressing stream, and the
    caller runs it in a worker thread so a large archive does not stall the event
    loop for every other request.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for kind, record in read_export(data):
        grouped.setdefault(kind, []).append(record)

    report = FieldReportCollector()
    events: list[dict[str, Any]] = []
    for kind, records in grouped.items():
        events.extend(
            transform_whoop_records(
                kind,
                records,
                tenant_id,
                source_id,
                require_scored=False,
                mappings=EXPORT_METRICS,
                report=report,
            )
        )
    return events, report


async def _publish(
    events: list[dict[str, Any]],
    *,
    nc: Any,
    tenant_id: str,
    source_id: str,
    sync_run_id: str | None,
    req_id: str,
    report: FieldReportCollector,
) -> None:
    """Hand the points to NATS and close the run out.

    Runs after the response, because publishing tens of thousands of points takes
    longer than a browser should be asked to hold a connection open. The run is what
    the dashboard watches instead: it was opened before the response went out, so
    there is no window in which the upload has been accepted and nothing says so.
    """
    published = 0
    try:
        js = nc.jetstream()
        for event in events:
            event["request_id"] = req_id
            if sync_run_id:
                event["sync_run_id"] = sync_run_id
            await js.publish("qs.ingest.whoop", json.dumps(event).encode("utf-8"))
            published += 1
    except Exception as exc:
        logger.error("[req_id=%s] Publishing the export failed after %d points: %s", req_id, published, exc)
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message=f"Publishing the export failed after {published} data point(s): {exc}",
            points_received=published,
        )
        return

    await send_field_report(tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id)
    await close_sync_run(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=req_id,
        status="idle",
        message=f"Export read: {published} data point(s) published.",
        points_received=published,
    )
    logger.info("[req_id=%s] Export upload finished: %d data point(s) published.", req_id, published)


@app.post("/upload")
@app.post("/api/v1/import/whoop/upload")
async def upload_export(
    request: Request,
    source_id: str = Query(..., description="The connector this export belongs to"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_whoop_upload", alias="X-Request-ID"),
):
    """Accept a Whoop export archive, publish what it contains, and report progress.

    The connector id is required rather than derived from the type: a workspace may
    hold several WHOOP connectors, and that id is the second component of every
    idempotency key derived here. Uploading the same file twice into the same
    connector therefore writes nothing the second time, while uploading it into a
    different one is a deliberate second series.
    """
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)
    target = await resolve_upload_target(tenant_id, source_id, req_id=x_request_id)

    data = await _read_capped_body(request, MAX_ARCHIVE_BYTES)
    if not data:
        raise HTTPException(status_code=400, detail="The upload was empty.")

    try:
        events, report = await asyncio.to_thread(_parse_export, data, tenant_id, target.source_id)
    except ArchiveTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ArchiveUnreadable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    if not events:
        raise HTTPException(
            status_code=400,
            detail="The archive was read but held no measurements this platform stores.",
        )

    nc = getattr(request.app.state, "nats_client", None)
    if nc is None or not nc.is_connected:
        if not getattr(request.app.state, "testing", False):
            raise HTTPException(
                status_code=503,
                detail="NATS event broker unavailable. Please retry later.",
            )

    sync_run_id = await open_sync_run(
        tenant_id,
        target.source_id,
        req_id=x_request_id,
        points_expected=len(events),
        message=f"Export upload: {len(events)} data point(s) to publish.",
    )

    if nc is not None and nc.is_connected:
        # Held in a set until it finishes: the event loop keeps only a weak
        # reference to a task, so one that nothing else names can be collected
        # mid-publish — and the import would then simply stop, with the run left
        # open and no error anywhere.
        task = asyncio.create_task(
            _publish(
                events,
                nc=nc,
                tenant_id=tenant_id,
                source_id=target.source_id,
                sync_run_id=sync_run_id,
                req_id=x_request_id,
                report=report,
            )
        )
        _running_imports.add(task)
        task.add_done_callback(_running_imports.discard)

    logger.info(
        "[req_id=%s] Tenant %s: accepted a WHOOP export with %d data point(s) for connector %s.",
        x_request_id,
        tenant_id,
        len(events),
        target.source_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "sync_run_id": sync_run_id,
            "source_id": target.source_id,
            "source_type": target.source_type,
            "points_expected": len(events),
        },
    )
