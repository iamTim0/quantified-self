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
import hashlib
import json
import logging
import tempfile
from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from shared_schemas import (
    FieldReportCollector,
    OffsetMismatch,
    SpoolTooLarge,
    UnknownUpload,
    UploadSession,
    UploadSpool,
    health_payload,
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


app = FastAPI(
    title="WHOOP Importer Service",
    lifespan=lifespan,
)

#: Imports still publishing after their response went out. See the comment where
#: they are added: an unreferenced task can be collected while it runs.
_running_imports: set[asyncio.Task] = set()

# A batch is the largest collection of transformed events this process retains. The
# archive reader and transformer are both lazy, so increasing the archive size does
# not increase the importer's resident set beyond this bound and one CSV row.
PUBLISH_BATCH_SIZE = 1_000
PUBLISH_BATCH_BYTES = 512 * 1024
PUBLISH_ATTEMPTS = 5
PUBLISH_RETRY_DELAY = 0.1
PROGRESS_INTERVAL_POINTS = 10_000


@app.get("/health")
async def health_check(response: Response):
    response.headers["Cache-Control"] = "no-store"
    nc = getattr(app.state, "nats_client", None)
    nats_connected = nc is not None and nc.is_connected
    response.status_code = 200 if nats_connected else 503
    return health_payload(
        settings.SERVICE_NAME,
        status="ok" if nats_connected else "degraded",
        nats_connected=nats_connected,
    )


async def _spool_request(
    request: Request, tenant_id: str, source_id: str
) -> UploadSession:
    """Stream one request body into the same private spool used by chunked uploads."""
    session = _uploads.begin(tenant_id, source_id)
    try:
        session = await _uploads.append(
            session.id,
            tenant_id,
            offset=0,
            chunks=request.stream(),
        )
        if session.received == 0:
            raise HTTPException(status_code=400, detail="The upload was empty.")
        return _uploads.finish(session.id, tenant_id)
    except BaseException:
        try:
            _uploads.abort(session.id, tenant_id)
        except UnknownUpload:
            pass
        raise


def _drain(points: Iterator[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Read at most ``size`` transformed points from the lazy archive iterator."""
    batch: list[dict[str, Any]] = []
    for _ in range(size):
        try:
            batch.append(next(points))
        except StopIteration:
            break
    return batch


async def _drain_batch(
    points: Iterator[dict[str, Any]],
    size: int,
    on_cancel: Callable[[], None],
) -> list[dict[str, Any]]:
    """Drain in a worker and let that worker finish before a cancelled import closes it."""
    worker = asyncio.create_task(asyncio.to_thread(_drain, points, size))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # The executor thread cannot be interrupted safely while csv.DictReader is
        # inside the ZIP generator. Cleanup is therefore attached to its completion;
        # closing ``points`` in this task would race the worker and corrupt cleanup.
        worker.add_done_callback(lambda _done: on_cancel())
        raise


def _transformed_events(
    path: str | Path,
    tenant_id: str,
    source_id: str,
    report: FieldReportCollector,
) -> Iterator[dict[str, Any]]:
    """Transform one CSV row at a time without retaining the archive's events."""
    records = read_export(path)
    try:
        for kind, record in records:
            # A single WHOOP row produces a bounded number of metric points. Passing
            # one row at a time avoids the transformer's list becoming archive-sized.
            yield from transform_whoop_records(
                kind,
                [record],
                tenant_id,
                source_id,
                require_scored=False,
                mappings=EXPORT_METRICS,
                report=report,
            )
    finally:
        close = getattr(records, "close", None)
        if close is not None:
            close()


class _PublishFailure(RuntimeError):
    """A bounded publish batch failed after some events were accepted."""

    def __init__(self, published: int, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.published = published
        self.cause = cause


async def _publish_with_retry(js: Any, payload: bytes, req_id: str) -> None:
    """Publish one event and retry lost acknowledgements safely."""
    delay = PUBLISH_RETRY_DELAY
    for attempt in range(1, PUBLISH_ATTEMPTS + 1):
        try:
            await js.publish("qs.ingest.whoop", payload)
            return
        except TimeoutError:
            if attempt == PUBLISH_ATTEMPTS:
                raise
            logger.warning(
                "[req_id=%s] No acknowledgement from the broker (attempt %d/%d); retrying in %.1fs",
                req_id,
                attempt,
                PUBLISH_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
            delay *= 2


async def _publish_events(
    js: Any,
    events: list[dict[str, Any]],
    *,
    req_id: str,
    sync_run_id: str | None,
) -> int:
    """Publish bounded versioned envelopes after all child fields are attached."""
    if not events:
        return 0

    for event in events:
        event["request_id"] = req_id
        if sync_run_id:
            event["sync_run_id"] = sync_run_id

    first = events[0]
    identity = (first.get("tenant_id"), first.get("source_id"), first.get("source_type"))
    if any(
        (event.get("tenant_id"), event.get("source_id"), event.get("source_type"))
        != identity
        for event in events
    ):
        raise ValueError("A WHOOP ingest batch must contain one tenant and connector")

    def encode_batch(batch: list[dict[str, Any]]) -> bytes:
        batch_id = hashlib.sha256(
            "|".join(str(event.get("idempotency_key", "")) for event in batch).encode()
        ).hexdigest()
        return json.dumps(
            {
                "schema_version": 2,
                "batch_id": batch_id,
                "tenant_id": identity[0],
                "source_id": identity[1],
                "source_type": identity[2],
                "request_id": req_id,
                "sync_run_id": sync_run_id,
                "events": batch,
            },
            separators=(",", ":"),
        ).encode("utf-8")

    published = 0
    current: list[dict[str, Any]] = []
    try:
        for event in events:
            candidate = [*current, event]
            encoded = encode_batch(candidate)
            if len(encoded) > PUBLISH_BATCH_BYTES and current:
                await _publish_with_retry(js, encode_batch(current), req_id)
                published += len(current)
                current = [event]
                encoded = encode_batch(current)
            if len(encoded) > PUBLISH_BATCH_BYTES:
                raise ValueError("A WHOOP event exceeds the bounded NATS batch size")
            current.append(event)
            if len(current) >= PUBLISH_BATCH_SIZE:
                await _publish_with_retry(js, encode_batch(current), req_id)
                published += len(current)
                current = []
        if current:
            await _publish_with_retry(js, encode_batch(current), req_id)
            published += len(current)
    except BaseException as exc:
        raise _PublishFailure(published, exc) from exc
    return published


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
    """Publish an already bounded batch for callers that use the old helper."""
    published = 0
    try:
        published = await _publish_events(
            nc.jetstream(), events, req_id=req_id, sync_run_id=sync_run_id
        )
    except _PublishFailure as exc:
        published = exc.published
        logger.error(
            "[req_id=%s] Publishing the WHOOP export failed after %d point(s): %s",
            req_id,
            published,
            exc.cause,
        )
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message=f"Publishing the export failed after {published} data point(s).",
            points_received=published,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[req_id=%s] Publishing the WHOOP export failed after %d point(s): %s",
            req_id,
            published,
            exc,
        )
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message=f"Publishing the export failed after {published} data point(s).",
            points_received=published,
        )
        return

    await send_field_report(
        tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id
    )
    await close_sync_run(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=req_id,
        status="idle",
        message=f"WHOOP archive read: {published} data point(s) published.",
        points_received=published,
    )


async def _import_archive(
    path: str | Path,
    *,
    nc: Any | None,
    testing: bool = False,
    tenant_id: str,
    source_id: str,
    sync_run_id: str | None,
    req_id: str,
) -> None:
    """Read, transform and publish a spooled archive with bounded memory."""
    report = FieldReportCollector()
    points = _transformed_events(path, tenant_id, source_id, report)
    published = 0
    saw_event = False
    last_reported = 0
    cleanup_deferred = False

    def cleanup_archive() -> None:
        close = getattr(points, "close", None)
        if close is not None:
            try:
                close()
            except ValueError:
                # The executor may still be unwinding the generator when the event
                # loop cancels its wrapper task. The worker owns the final close;
                # removing the path here still prevents a private archive from
                # surviving the request.
                pass
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            # Never raise from here. This runs both in a `finally` — where a throw
            # would replace whatever the import was already failing with — and from
            # a task's done-callback, where it becomes an unraisable nobody reads.
            # A spool file left behind is a disk-space problem and gets swept; an
            # error swallowed on the way out is a debugging problem forever.
            logger.warning(
                "[req_id=%s] Could not remove the spooled archive %s: %s",
                req_id,
                path,
                exc,
            )

    try:
        if nc is None or not nc.is_connected:
            if not testing:
                raise RuntimeError("NATS event broker unavailable while importing the archive.")
            js = None
        else:
            js = nc.jetstream()
        while True:
            try:
                batch = await _drain_batch(
                    points, PUBLISH_BATCH_SIZE, on_cancel=cleanup_archive
                )
            except asyncio.CancelledError:
                cleanup_deferred = True
                raise
            if not batch:
                break
            saw_event = True
            try:
                sent = (
                    await _publish_events(
                        js,
                        batch,
                        req_id=req_id,
                        sync_run_id=sync_run_id,
                    )
                    if js is not None
                    else len(batch)
                )
            except _PublishFailure as exc:
                published += exc.published
                raise
            published += sent

            if published - last_reported >= PROGRESS_INTERVAL_POINTS:
                await report_sync_progress(
                    tenant_id,
                    source_id,
                    sync_run_id,
                    req_id=req_id,
                    points_received=published,
                    message=f"WHOOP archive publishing: {published} data point(s) sent.",
                )
                last_reported = published
    except _PublishFailure as exc:
        logger.error(
            "[req_id=%s] Publishing the WHOOP export failed after %d point(s): %s",
            req_id,
            published,
            exc.cause,
        )
        await send_field_report(
            tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id
        )
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message=f"Publishing the export failed after {published} data point(s).",
            points_received=published,
        )
        return
    except (ArchiveTooLarge, ArchiveUnreadable) as exc:
        logger.warning(
            "[req_id=%s] WHOOP archive refused after %d point(s): %s",
            req_id,
            published,
            exc,
        )
        await send_field_report(
            tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id
        )
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message=str(exc),
            points_received=published,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[req_id=%s] Reading the WHOOP archive failed after %d point(s): %s",
            req_id,
            published,
            exc,
        )
        await send_field_report(
            tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id
        )
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message=f"Reading the archive failed after {published} data point(s).",
            points_received=published,
        )
        return
    finally:
        if not cleanup_deferred:
            cleanup_archive()

    await report_sync_progress(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=req_id,
        points_received=published,
        message=f"WHOOP archive publishing: {published} data point(s) sent.",
    )
    await send_field_report(
        tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id
    )
    if not saw_event:
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=req_id,
            status="error",
            message="The archive held no measurements this platform stores.",
            points_received=0,
        )
        return

    await close_sync_run(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=req_id,
        status="idle",
        message=f"WHOOP archive read: {published} data point(s) published.",
        points_received=published,
    )
    logger.info(
        "[req_id=%s] WHOOP archive upload finished: %d data point(s) published.",
        req_id,
        published,
    )


async def _accept_export(
    path: str | Path,
    *,
    state: Any,
    received: int,
    tenant_id: str,
    target: UploadTarget,
    sync_run_id: str | None,
    x_request_id: str,
) -> JSONResponse:
    """Start a background import that owns and deletes the spooled archive."""
    nc = getattr(state, "nats_client", None)
    if (nc is None or not nc.is_connected) and not getattr(state, "testing", False):
        Path(path).unlink(missing_ok=True)
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

    try:
        task = asyncio.create_task(
            _import_archive(
                path,
                nc=nc,
                testing=getattr(state, "testing", False),
                tenant_id=tenant_id,
                source_id=target.source_id,
                sync_run_id=sync_run_id,
                req_id=x_request_id,
            )
        )
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise

    _running_imports.add(task)
    task.add_done_callback(_running_imports.discard)
    logger.info(
        "[req_id=%s] Tenant %s: accepted a %d byte WHOOP export for connector %s.",
        x_request_id,
        tenant_id,
        received,
        target.source_id,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "sync_run_id": sync_run_id,
            "source_id": target.source_id,
            "source_type": target.source_type,
            "received": received,
            "points_expected": None,
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
        session = await _spool_request(request, tenant_id, target.source_id)
    except SpoolTooLarge as exc:
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=str(exc),
        )
        raise HTTPException(status_code=413, detail=str(exc)) from None
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
        session.path,
        state=request.app.state,
        received=session.received,
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

    received = session.received
    archive_path = session.path
    try:
        target = await resolve_upload_target(tenant_id, session.source_id, req_id=x_request_id)
        sync_run_id = await open_sync_run(
            tenant_id,
            target.source_id,
            req_id=x_request_id,
            points_expected=None,
            message=f"WHOOP archive received ({received} byte(s)).",
        )
        return await _accept_export(
            archive_path,
            state=request.app.state,
            received=received,
            tenant_id=tenant_id,
            target=target,
            sync_run_id=sync_run_id,
            x_request_id=x_request_id,
        )
    except BaseException:
        # ``_accept_export`` transfers ownership only after its task is created. All
        # earlier failures must remove the assembled archive here.
        archive_path.unlink(missing_ok=True)
        raise


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
