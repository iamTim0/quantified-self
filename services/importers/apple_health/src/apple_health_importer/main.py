"""Apple Health Importer Main Entry Point.

FastAPI Webhook Server & NATS JetStream Publisher for Health Auto Export JSON.
Submits transformed IngestEvents to NATS subject 'qs.ingest.apple_health'.
"""

import asyncio
import hashlib
import json
import logging
import tempfile
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats
import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from shared_schemas import (
    FieldReportCollector,
    OffsetMismatch,
    SpoolTooLarge,
    UnknownUpload,
    UploadSpool,
    health_payload,
)

from apple_health_importer.auth import extract_presented_key, resolve_api_key
from apple_health_importer.client import (
    bearer_token,
    close_sync_run,
    get_ingest_policies,
    open_sync_run,
    report_sync_progress,
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
from apple_health_importer.transformer import (
    AppleHealthPayloadError,
    transform_health_auto_export_json,
    validate_health_auto_export_payload,
)

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

#: Archives arriving in parts. An export can be hundreds of megabytes and the proxies
#: between a browser and this service refuse a body that large — Cloudflare at 100 MB,
#: before three of them have been sent — so the dashboard sends parts and this
#: reassembles them. See `shared_schemas.upload_spool`.
_uploads = UploadSpool(
    Path(tempfile.gettempdir()) / "qs-apple-health-uploads",
    max_bytes=MAX_ARCHIVE_BYTES,
)

#: Attempts for one event before an import gives up on it. A whole-history archive is
#: millions of publishes and takes hours, and every one of them waits for a JetStream ack:
#: a single ack that does not arrive in time used to end the import, with the archive then
#: deleted and 195 MB to upload again for a broker that was merely busy. Measured once at
#: 47,432 points in, against a broker whose consumer was wedged.
PUBLISH_ATTEMPTS = 5

#: Doubling from here, so the last wait is 1.6s and one event costs at most ~3s of
#: retries. Long enough to outlast a busy broker, short enough that a genuinely broken one
#: still fails the import rather than stalling it for hours.
PUBLISH_RETRY_DELAY = 0.1
PUBLISH_BATCH_SIZE = 1_000
PUBLISH_BATCH_BYTES = 512 * 1024

#: How often the spool is checked for uploads nobody came back to finish.
_SWEEP_INTERVAL_SECONDS = 300

_PAYLOAD_ERROR_DETAILS: dict[str, str] = {
    "invalid_json": "The request body is not valid JSON.",
    "payload_not_object": "The Apple Health payload must be a JSON object.",
    "payload_empty": "The Apple Health payload is empty.",
    "payload_data_not_object": "The Apple Health payload has an invalid data envelope.",
    "payload_unrecognized": "The JSON document is not a Health Auto Export payload.",
    "payload_missing_sections": "The Health Auto Export payload has no supported data sections.",
    "payload_section_not_array": "A Health Auto Export data section must be an array.",
    "payload_metric_invalid": "A Health Auto Export metric entry has an invalid shape.",
    "payload_metric_data_invalid": "A Health Auto Export metric data section has an invalid shape.",
    "payload_workout_invalid": "A Health Auto Export workout entry has an invalid shape.",
    "payload_transform_failed": "The Apple Health payload could not be transformed.",
    "broker_unavailable": "The event broker is unavailable; the request was rejected.",
    "broker_publish_failed": "The event broker did not accept the Apple Health data.",
}


def _payload_error_response(
    code: str,
    *,
    params: dict[str, str | int | float | bool] | None = None,
    status_code: int = 422,
) -> JSONResponse:
    """Return a stable safe error without reflecting provider payload data."""
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "params": params or {},
            "detail": _PAYLOAD_ERROR_DETAILS.get(code, "The Apple Health payload was rejected."),
        },
    )


def _field_report_count(report: FieldReportCollector) -> int:
    """Count provider field occurrences that arrived but were not stored."""
    return sum(sighting.occurrences for sighting in report.build().unmapped)


def _event_window(events: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Return the normalized provider coverage window without retaining payloads."""
    timestamps: list[datetime] = []
    for event in events:
        try:
            value = datetime.fromisoformat(str(event["timestamp"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        timestamps.append(value.astimezone(timezone.utc))
    if not timestamps:
        return None, None
    return min(timestamps).isoformat(), max(timestamps).isoformat()


async def _sweep_uploads_forever() -> None:
    """Delete abandoned upload parts for as long as the service runs.

    An unfinished upload is a piece of somebody's medical history in a temporary
    file. A failure to sweep is logged and the loop continues: giving up would turn
    one bad sweep into a spool that grows forever.
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
async def lifespan(app: FastAPI):
    global nc_client
    logger.info(f"Connecting to NATS at {settings.NATS_URL}...")
    try:
        nc_client = await nats.connect(settings.NATS_URL)
        logger.info("Connected to NATS JetStream successfully.")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Could not connect to NATS on startup: {e}")

    sweeper = asyncio.create_task(_sweep_uploads_forever())

    yield

    sweeper.cancel()

    if nc_client and not nc_client.is_closed:
        await nc_client.close()
        logger.info("NATS connection closed.")


app = FastAPI(
    title="Apple Health Importer Service",
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

    # Open before parsing so malformed JSON and broker outages are recorded for the
    # authenticated connector instead of disappearing into the access log.
    sync_run_id = await open_sync_run(
        tenant_id,
        source_id,
        req_id=x_request_id,
        trigger="push",
        message="Health Auto Export request received.",
    )

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=_PAYLOAD_ERROR_DETAILS["invalid_json"],
            code="invalid_json",
        )
        return _payload_error_response("invalid_json", status_code=400)

    try:
        validate_health_auto_export_payload(payload)
    except AppleHealthPayloadError as exc:
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=_PAYLOAD_ERROR_DETAILS.get(exc.code, "The Apple Health payload was rejected."),
            code=exc.code,
            params=exc.params,
        )
        return _payload_error_response(exc.code, params=exc.params)

    # Prevent silent data loss: Return 503 if NATS is unavailable so webhook client retries delivery
    if nc_client is None or not nc_client.is_connected:  # noqa: SIM102
        # Check if running in test environment where NATS is mocked/disabled
        if not getattr(request.app.state, "testing", False):
            await close_sync_run(
                tenant_id,
                source_id,
                sync_run_id,
                req_id=x_request_id,
                status="error",
                message=_PAYLOAD_ERROR_DETAILS["broker_unavailable"],
                code="broker_unavailable",
                params={},
            )
            logger.error(f"[req_id={x_request_id}] NATS connection offline. Rejecting payload with 503.")
            return _payload_error_response("broker_unavailable", status_code=503)

    field_report = FieldReportCollector()
    try:
        ingest_policies = (
            await get_ingest_policies(tenant_id, source_id, req_id=x_request_id)
            if nc_client and nc_client.is_connected
            else {}
        )
        events = transform_health_auto_export_json(
            payload,
            tenant_id=tenant_id,
            source_id=source_id,
            report=field_report,
            ingest_policies=ingest_policies,
        )
    except Exception:  # noqa: BLE001
        await close_sync_run(
            tenant_id,
            source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message=_PAYLOAD_ERROR_DETAILS["payload_transform_failed"],
            code="payload_transform_failed",
        )
        return _payload_error_response("payload_transform_failed")

    provider_window_start, provider_window_end = _event_window(events)
    unsupported_fields = _field_report_count(field_report)
    await report_sync_progress(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=x_request_id,
        points_expected=len(events),
        unsupported_fields=unsupported_fields,
        provider_window_start=provider_window_start,
        provider_window_end=provider_window_end,
        message=f"Health Auto Export transformed {len(events)} data point(s).",
    )

    published_count = 0
    if nc_client and nc_client.is_connected:
        js = nc_client.jetstream()
        try:
            published_count = await _publish_events(
                js, events, req_id=x_request_id, sync_run_id=sync_run_id
            )
        except TimeoutError:
            await close_sync_run(
                tenant_id,
                source_id,
                sync_run_id,
                req_id=x_request_id,
                status="error",
                message=_PAYLOAD_ERROR_DETAILS["broker_publish_failed"],
                code="broker_publish_failed",
                params={"published": published_count},
            )
            return _payload_error_response("broker_publish_failed", status_code=503)
        except Exception:  # noqa: BLE001 - do not reflect event/provider data
            await close_sync_run(
                tenant_id,
                source_id,
                sync_run_id,
                req_id=x_request_id,
                status="error",
                message=_PAYLOAD_ERROR_DETAILS["broker_publish_failed"],
                code="broker_publish_failed",
                params={"published": published_count},
            )
            return _payload_error_response("broker_publish_failed", status_code=503)
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
            unsupported_fields=unsupported_fields,
            provider_window_start=provider_window_start,
            provider_window_end=provider_window_end,
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
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
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


async def _publish_with_retry(js, payload: bytes, req_id: str) -> None:
    """Publish one event, retrying an ack that does not arrive.

    A JetStream publish waits for the server to confirm the write, and a broker under
    load answers late rather than not at all. Retrying is safe precisely because of the
    `idempotency_key` (AGENTS.md rule 4): if the first attempt did land and only its ack
    was lost, the duplicate is discarded by Core rather than stored twice.

    Raises `TimeoutError` once the attempts are spent, which ends the import — a broker
    that has not answered five times over three seconds is not busy, it is broken.
    """
    delay = PUBLISH_RETRY_DELAY
    for attempt in range(1, PUBLISH_ATTEMPTS + 1):
        try:
            await js.publish("qs.ingest.apple_health", payload)
            return
        except TimeoutError:
            if attempt == PUBLISH_ATTEMPTS:
                raise
            logger.warning(
                "[req_id=%s] No ack from the broker (attempt %d/%d); retrying in %.1fs",
                req_id, attempt, PUBLISH_ATTEMPTS, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2


async def _publish_events(
    js,
    events: list[dict],
    *,
    req_id: str,
    sync_run_id: str | None,
) -> int:
    """Publish bounded versioned envelopes while retaining broker backpressure."""
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
        raise ValueError("An Apple Health ingest batch must contain one tenant and connector")

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
    for event in events:
        candidate = [*current, event]
        encoded = encode_batch(candidate)
        if len(encoded) > PUBLISH_BATCH_BYTES and current:
            await _publish_with_retry(js, encode_batch(current), req_id)
            published += len(current)
            current = [event]
            encoded = encode_batch(current)
        if len(encoded) > PUBLISH_BATCH_BYTES:
            raise ValueError("An Apple Health event exceeds the bounded NATS batch size")
        current.append(event)
        if len(current) >= PUBLISH_BATCH_SIZE:
            await _publish_with_retry(js, encode_batch(current), req_id)
            published += len(current)
            current = []
    if current:
        await _publish_with_retry(js, encode_batch(current), req_id)
        published += len(current)
    return published


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
    provider_window_start: str | None = None
    provider_window_end: str | None = None
    ingest_policies = (
        await get_ingest_policies(tenant_id, source_id, req_id=req_id)
        if nc_client and nc_client.is_connected
        else {}
    )
    points = read_export(
        path,
        tenant_id=tenant_id,
        source_id=source_id,
        report=report,
        ingest_policies=ingest_policies,
    )
    try:
        js = nc_client.jetstream() if nc_client else None
        while True:
            batch = await asyncio.to_thread(_drain, points, 1000)
            if not batch:
                break
            batch_start, batch_end = _event_window(batch)
            if batch_start and (provider_window_start is None or batch_start < provider_window_start):
                provider_window_start = batch_start
            if batch_end and (provider_window_end is None or batch_end > provider_window_end):
                provider_window_end = batch_end
            if js is not None:
                published += await _publish_events(
                    js, batch, req_id=req_id, sync_run_id=sync_run_id
                )
            else:
                published += len(batch)
    except TimeoutError as exc:
        # Distinguished from the generic failure below because the cause is elsewhere and
        # the remedy is not the user's: the archive was read fine, the broker did not
        # acknowledge. Says how far it got, because that much is stored and a re-import
        # deduplicates on the idempotency key rather than doubling it.
        logger.error(
            "[req_id=%s] The broker stopped acknowledging after %d point(s): %s",
            req_id, published, exc,
        )
        await close_sync_run(
            tenant_id, source_id, sync_run_id, req_id=req_id, status="error",
            message=(
                f"The event broker stopped acknowledging after {published} data point(s). "
                f"The points already sent are stored; uploading the file again resumes "
                f"rather than duplicating."
            ),
            points_received=published,
            unsupported_fields=_field_report_count(report),
            provider_window_start=provider_window_start,
            provider_window_end=provider_window_end,
        )
        return
    except (ArchiveTooLarge, ArchiveUnreadable) as exc:
        # Logged as well as recorded on the run: a rejection that exists only in the
        # database looks, in the log, like an upload that completed and then stopped
        # mattering. The message names the file's shape, never its contents.
        logger.warning(
            "[req_id=%s] Archive refused after %d point(s): %s", req_id, published, exc
        )
        await close_sync_run(
            tenant_id, source_id, sync_run_id, req_id=req_id, status="error",
            message=str(exc), points_received=published,
            unsupported_fields=_field_report_count(report),
            provider_window_start=provider_window_start,
            provider_window_end=provider_window_end,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.error("[req_id=%s] Reading the archive failed after %d points: %s", req_id, published, exc)
        await close_sync_run(
            tenant_id, source_id, sync_run_id, req_id=req_id, status="error",
            message=f"Reading the archive failed after {published} data point(s): {exc}",
            points_received=published,
            unsupported_fields=_field_report_count(report),
            provider_window_start=provider_window_start,
            provider_window_end=provider_window_end,
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

    unsupported_fields = _field_report_count(report)
    await report_sync_progress(
        tenant_id,
        source_id,
        sync_run_id,
        req_id=req_id,
        points_received=published,
        unsupported_fields=unsupported_fields,
        provider_window_start=provider_window_start,
        provider_window_end=provider_window_end,
        message=f"Archive parsed: {published} data point(s) published so far.",
    )
    await send_field_report(tenant_id, source_id, report.build(), req_id=req_id, sync_run_id=sync_run_id)
    await close_sync_run(
        tenant_id, source_id, sync_run_id, req_id=req_id, status="idle",
        message=f"Archive read: {published} data point(s) published.",
        points_received=published,
        unsupported_fields=unsupported_fields,
        provider_window_start=provider_window_start,
        provider_window_end=provider_window_end,
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

    # Open the run before reading the body so rejected archives (empty, oversized
    # or unreadable) remain visible in the connector history as failed requests.
    sync_run_id = await open_sync_run(
        tenant_id,
        target.source_id,
        req_id=x_request_id,
        trigger="upload",
        message="Receiving the Apple Health archive.",
    )

    if (nc_client is None or not nc_client.is_connected) and not getattr(
        request.app.state, "testing", False
    ):
        await close_sync_run(
            tenant_id,
            target.source_id,
            sync_run_id,
            req_id=x_request_id,
            status="error",
            message="NATS event broker unavailable; the upload was rejected.",
        )
        raise HTTPException(
            status_code=503, detail="NATS event broker unavailable. Please retry later."
        )

    try:
        path = await _spool_upload(request, MAX_ARCHIVE_BYTES)
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


# --------------------------------------------------------------------------------
# The same archive, in parts.
#
# `/upload` above is one request, which is the right shape for a script, a test or a
# small export and the wrong shape for the browser path: the hops in between refuse a
# body of that size. Cloudflare answers 413 at the edge on every plan below Enterprise
# once a body passes 100 MB, and it answers after roughly three megabytes have been
# pushed — a 200 MB export therefore failed at "2 %" with nothing here ever running.
#
# So the dashboard asks for a session, sends parts that fit through anything, and then
# says it is done. The three steps are separate requests rather than one clever route
# because each answers a different question: where do I send, here is more, that was
# everything.
# --------------------------------------------------------------------------------


def _upload_failure(exc: Exception) -> JSONResponse:
    """Turn a spool refusal into the response that tells a client what to do next.

    409 carries the offset the spool wants, which is the whole resume mechanism: a
    client that lost a response, or a connection, learns where to continue instead of
    starting a 200 MB upload again.
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
@app.post("/api/v1/import/apple-health/upload/begin")
async def begin_chunked_upload(
    source_id: str = Query(..., description="The connector this archive belongs to"),
    total_bytes: int | None = Query(
        None, ge=0, description="Size of the archive, so an impossible one fails now"
    ),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_apple_health_upload", alias="X-Request-ID"),
):
    """Open an upload session and say how large a part may be.

    The part size comes from the server so that the limit lives in one place. A
    dashboard that hardcoded it would have to be redeployed to follow a proxy.

    The connector is resolved here, before any bytes are sent: an archive uploaded for
    a quarter of an hour and then rejected for naming an unknown connector is a quarter
    of an hour of somebody's evening.
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
@app.post("/api/v1/import/apple-health/upload/chunk")
async def append_chunked_upload(
    request: Request,
    upload_id: str = Query(..., description="The session this part belongs to"),
    offset: int = Query(..., ge=0, description="Where this part starts in the archive"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_apple_health_upload", alias="X-Request-ID"),
):
    """Append one part at ``offset``.

    Streamed into the spool file as it arrives: a part is never held in memory here,
    for the same reason the single-request route never held an archive.
    """
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
@app.post("/api/v1/import/apple-health/upload/complete")
async def complete_chunked_upload(
    upload_id: str = Query(..., description="The session that is now complete"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_apple_health_upload", alias="X-Request-ID"),
):
    """Read the assembled archive, exactly as if it had arrived in one request.

    The run is opened here rather than when the session was, deliberately. A run open
    for the twenty minutes a browser spends uploading would show the dashboard an
    import that is importing nothing, and Core's scheduler treats a connector with an
    open run as busy — an upload someone abandoned would have suppressed that
    connector's scheduled imports until the run went stale six hours later. The upload
    itself is visible in the dashboard while it happens; a run describes the import.
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
    try:
        target = await resolve_upload_target(tenant_id, session.source_id, req_id=x_request_id)

        if (nc_client is None or not nc_client.is_connected) and not getattr(
            app.state, "testing", False
        ):
            raise HTTPException(
                status_code=503, detail="NATS event broker unavailable. Please retry later."
            )

        sync_run_id = await open_sync_run(
            tenant_id,
            target.source_id,
            req_id=x_request_id,
            trigger="upload",
            message=f"Apple Health archive received ({received} byte(s)).",
        )

        task = asyncio.create_task(
            _import_archive(
                str(session.path),
                tenant_id=tenant_id,
                source_id=target.source_id,
                sync_run_id=sync_run_id,
                req_id=x_request_id,
            )
        )
        # The task owns the path from this point. Its finally block removes it after
        # the parser has released the ZIP; failures before task creation are cleaned
        # up by the outer finally below.
        session = None
        _running_imports.add(task)
        task.add_done_callback(_running_imports.discard)
    finally:
        if session is not None:
            session.path.unlink(missing_ok=True)

    logger.info(
        "[req_id=%s] Tenant %s: assembled a %d byte Apple Health archive for connector %s.",
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
        },
    )


@app.post("/upload/abort")
@app.post("/api/v1/import/apple-health/upload/abort")
async def abort_chunked_upload(
    upload_id: str = Query(..., description="The session to give up on"),
    authorization: str | None = Header(None, alias="Authorization"),
    x_request_id: str = Header("req_apple_health_upload", alias="X-Request-ID"),
):
    """Give up on a session and delete the parts that arrived.

    A cancelled upload deletes health data now instead of at the next sweep, which is
    the difference between a user's decision being carried out and being scheduled.
    """
    tenant_id = await resolve_session(bearer_token(authorization), req_id=x_request_id)

    try:
        _uploads.abort(upload_id, tenant_id)
    except UnknownUpload:
        # Nothing to give up on: the session already ended, or never existed. Either
        # way the caller's intent holds, so this is not an error it needs to handle.
        pass

    return JSONResponse(status_code=200, content={"status": "aborted"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.PORT)
