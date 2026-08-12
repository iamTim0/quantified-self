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
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from shared_schemas import (
    FieldReportCollector,
    OffsetMismatch,
    SpoolTooLarge,
    UnknownUpload,
    UploadSpool,
)

from whoop_importer.config import settings
from whoop_importer.core_client import (
    UploadTarget,
    bearer_token,
    close_sync_run,
    open_sync_run,
    report_sync_progress,
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

#: Archives arriving in parts, because the hops between a browser and this service
#: refuse a body of the size an export can reach — Cloudflare at 100 MB, answered at
#: the edge before three of them have been sent. See `shared_schemas.upload_spool`.
_uploads = UploadSpool(
    Path(tempfile.gettempdir()) / "qs-whoop-uploads",
    max_bytes=MAX_ARCHIVE_BYTES,
)

#: How often the spool is checked for uploads nobody came back to finish.
_SWEEP_INTERVAL_SECONDS = 300


async def _sweep_uploads_forever() -> None:
    """Delete abandoned upload parts for as long as the service runs.

    A failure to sweep is logged and the loop continues: giving up would turn one bad
    sweep into a spool that grows for the life of the process.
    """
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)
        try:
            discarded = _uploads.sweep()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sweeping unfinished uploads failed: %s", exc)
            continue
        if discarded:
            logger.info("Discarded %d unfinished upload(s).", discarded)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Runs the spool sweeper alongside the upload endpoints.

    The NATS client is attached to `app.state` by `main`, which owns it — this service
    is one process with one connection, and the web half borrows it rather than opening
    a second one.
    """
    sweeper = asyncio.create_task(_sweep_uploads_forever())
    yield
    sweeper.cancel()


app = FastAPI(title="WHOOP Importer Service", version="0.1.0", lifespan=lifespan)

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
    except Exception as exc:  # noqa: BLE001
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


async def _accept_export(
    data: bytes,
    *,
    state: Any,
    tenant_id: str,
    target: UploadTarget,
    sync_run_id: str | None,
    x_request_id: str,
) -> JSONResponse:
    """Parse an export archive, start publishing it, and answer the caller.

    Shared by the two ways an archive reaches this service — one request, or a session
    of parts (the upload session routes at the bottom of this module) — because
    everything from "the bytes are all here" onwards is the same work, down to which
    failure closes the run out with which message. ``x_request_id`` keeps the header's
    name because that is what it is.
    """
    try:
        if not data:
            raise HTTPException(status_code=400, detail="The upload was empty.")
        events, report = await asyncio.to_thread(_parse_export, data, tenant_id, target.source_id)
        if not events:
            raise HTTPException(
                status_code=400,
                detail="The archive was read but held no measurements this platform stores.",
            )
    except ArchiveTooLarge as exc:
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=str(exc),
        )
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except ArchiveUnreadable as exc:
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except HTTPException as exc:
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=str(exc.detail),
        )
        raise
    except Exception as exc:  # noqa: BLE001
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=f"Could not read the archive: {type(exc).__name__}: {exc}",
        )
        raise HTTPException(status_code=400, detail="Could not read the archive.") from None

    await report_sync_progress(
        tenant_id,
        target.source_id,
        sync_run_id,
        req_id=x_request_id,
        points_expected=len(events),
        message=f"WHOOP archive contains {len(events)} data point(s) to publish.",
    )

    nc = getattr(state, "nats_client", None)
    if nc is None or not nc.is_connected:  # noqa: SIM102
        if not getattr(state, "testing", False):
            await close_sync_run(
                tenant_id,
                target.source_id,
                sync_run_id,
                req_id=x_request_id,
                status="error",
                message="NATS event broker unavailable; the upload was rejected.",
            )
            raise HTTPException(
                status_code=503,
                detail="NATS event broker unavailable. Please retry later.",
            )

    # The exact count is now known, but the run is already open so every earlier
    # failure has a durable history row. The current count is reported in the
    # response and final status as the importer publishes.

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
    else:
        # Test/dry-run mode has no broker task to finish the run, so close it here.
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="success",
            message=f"Export parsed: {len(events)} data point(s) ready.",
            points_received=len(events),
        )

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


@app.post("/upload")
@app.post("/api/v1/import/whoop/upload")
async def upload_export(
    request: Request,
    source_id: str = Query(..., description="The connector this export belongs to"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_whoop_upload", alias="X-Request-ID"),
):
    """Accept a Whoop export archive in one request, publish it, and report progress.

    The connector id is required rather than derived from the type: a workspace may
    hold several WHOOP connectors, and that id is the second component of every
    idempotency key derived here. Uploading the same file twice into the same
    connector therefore writes nothing the second time, while uploading it into a
    different one is a deliberate second series.

    One request suits a script, a test and a small export. A browser uses the session
    routes below, because a proxy on the way refuses a body this size.
    """
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)
    target = await resolve_upload_target(tenant_id, source_id, req_id=x_request_id)

    # Open before consuming the body so an empty or oversized upload is visible as
    # a failed run on the connector detail page.
    sync_run_id = await open_sync_run(
        tenant_id,
        target.source_id,
        req_id=x_request_id,
        points_expected=None,
        message="Receiving the WHOOP archive.",
    )

    try:
        data = await _read_capped_body(request, MAX_ARCHIVE_BYTES)
    except HTTPException as exc:
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=str(exc.detail),
        )
        raise
    except Exception as exc:  # noqa: BLE001
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=f"Could not receive the archive: {type(exc).__name__}: {exc}",
        )
        raise HTTPException(status_code=400, detail="Could not receive the archive.") from None

    return await _accept_export(
        data,
        state=request.app.state,
        tenant_id=tenant_id,
        target=target,
        sync_run_id=sync_run_id,
        x_request_id=x_request_id,
    )


# --------------------------------------------------------------------------------
# The same archive, in parts. Why this exists rather than a larger body limit: the
# limits are not ours. Cloudflare refuses a request body over 100 MB on every plan
# below Enterprise and refuses it at the edge, so a large export failed before any
# service in this repository ran. Parts that fit through anything, reassembled here,
# are what make a whole-history export uploadable from a browser at all.
# --------------------------------------------------------------------------------


def _upload_failure(exc: Exception) -> JSONResponse:
    """Turn a spool refusal into the response that tells a client what to do next.

    409 carries the offset the spool wants, which is the resume mechanism: a client
    that lost a response, or a connection, learns where to continue rather than
    starting the upload again.
    """
    if isinstance(exc, OffsetMismatch):
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "expected_offset": exc.expected},
        )
    if isinstance(exc, SpoolTooLarge):
        return JSONResponse(status_code=413, content={"detail": str(exc)})
    if isinstance(exc, UnknownUpload):
        return JSONResponse(status_code=404, content={"detail": str(exc)})
    raise exc


@app.post("/upload/begin")
@app.post("/api/v1/import/whoop/upload/begin")
async def begin_chunked_upload(
    source_id: str = Query(..., description="The connector this export belongs to"),
    total_bytes: int | None = Query(
        None, ge=0, description="Size of the archive, so an impossible one fails now"
    ),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_whoop_upload", alias="X-Request-ID"),
):
    """Open an upload session and say how large a part may be.

    The part size comes from the server, so the limit lives in one place instead of in
    every client. The connector is resolved before any bytes are sent, so an upload is
    never spent on a connector that turns out not to exist.
    """
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)
    target = await resolve_upload_target(tenant_id, source_id, req_id=x_request_id)

    try:
        session = _uploads.begin(tenant_id, target.source_id, total_bytes=total_bytes)
    except (OffsetMismatch, SpoolTooLarge, UnknownUpload) as exc:
        return _upload_failure(exc)

    logger.info(
        "[req_id=%s] Tenant %s: upload session opened for connector %s (%s byte(s) announced).",
        x_request_id,
        tenant_id,
        target.source_id,
        total_bytes if total_bytes is not None else "unknown",
    )
    return JSONResponse(
        status_code=201,
        content={
            "upload_id": session.id,
            "chunk_bytes": _uploads.chunk_bytes,
            "max_bytes": _uploads.max_bytes,
            "received": session.received,
            "source_id": target.source_id,
            "source_type": target.source_type,
        },
    )


@app.post("/upload/chunk")
@app.post("/api/v1/import/whoop/upload/chunk")
async def append_chunked_upload(
    request: Request,
    upload_id: str = Query(..., description="The session this part belongs to"),
    offset: int = Query(..., ge=0, description="Where this part starts in the archive"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_whoop_upload", alias="X-Request-ID"),
):
    """Append one part at ``offset``, streamed into the spool file as it arrives."""
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)

    try:
        session = await _uploads.append(
            upload_id, tenant_id, offset=offset, chunks=request.stream()
        )
    except (OffsetMismatch, SpoolTooLarge, UnknownUpload) as exc:
        return _upload_failure(exc)

    return JSONResponse(
        status_code=200,
        content={"received": session.received, "chunk_bytes": _uploads.chunk_bytes},
    )


@app.post("/upload/complete")
@app.post("/api/v1/import/whoop/upload/complete")
async def complete_chunked_upload(
    request: Request,
    upload_id: str = Query(..., description="The session that is now complete"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_whoop_upload", alias="X-Request-ID"),
):
    """Read the assembled archive, exactly as if it had arrived in one request.

    The run is opened here rather than when the session was: a run open for the minutes
    a browser spends uploading would show an import that is importing nothing, and
    Core's scheduler treats a connector with an open run as busy, so an abandoned
    upload would have suppressed that connector's scheduled imports until the run went
    stale hours later.
    """
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)

    try:
        session = _uploads.session(upload_id, tenant_id)
        if not session.complete:
            raise OffsetMismatch(session.received)
        if session.received == 0:
            _uploads.abort(upload_id, tenant_id)
            raise HTTPException(status_code=400, detail="The upload was empty.")
        session = _uploads.finish(upload_id, tenant_id)
    except (OffsetMismatch, SpoolTooLarge, UnknownUpload) as exc:
        return _upload_failure(exc)

    target = await resolve_upload_target(tenant_id, session.source_id, req_id=x_request_id)

    try:
        # In a worker thread: the archive is read from disk in one go because that is
        # what this importer's parser takes, and reading it on the event loop would
        # stall every other request for as long as it takes.
        data = await asyncio.to_thread(session.path.read_bytes)
    finally:
        # The export is somebody's history. It exists on this disk only for as long as
        # it takes to read, whatever the outcome.
        session.path.unlink(missing_ok=True)

    sync_run_id = await open_sync_run(
        tenant_id,
        target.source_id,
        req_id=x_request_id,
        points_expected=None,
        message=f"WHOOP archive received ({session.received} byte(s)).",
    )

    return await _accept_export(
        data,
        state=request.app.state,
        tenant_id=tenant_id,
        target=target,
        sync_run_id=sync_run_id,
        x_request_id=x_request_id,
    )


@app.post("/upload/abort")
@app.post("/api/v1/import/whoop/upload/abort")
async def abort_chunked_upload(
    upload_id: str = Query(..., description="The session to give up on"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_whoop_upload", alias="X-Request-ID"),
):
    """Give up on a session and delete the parts that arrived."""
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)

    try:
        _uploads.abort(upload_id, tenant_id)
    except UnknownUpload:
        # Nothing to give up on: the session already ended, or never existed. The
        # caller's intent holds either way, so this is not an error to hand back.
        pass

    return JSONResponse(status_code=200, content={"status": "aborted"})
