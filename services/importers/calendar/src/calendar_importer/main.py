"""Request-driven calendar importer publishing exclusively through JetStream.

Reads real iCalendar feeds. A public ``.ics`` URL needs no credential; see
``client.infer_auth_mode`` for how the three supported modes are distinguished.
"""

import asyncio
import json
import logging
from typing import Any

import httpx
import nats

from calendar_importer.client import (
    CalendarAuthError,
    CalendarFetchError,
    build_feed_config,
    fetch_feed,
)
from calendar_importer.config import settings
from calendar_importer.ics import IcsParseError, parse_ics
from calendar_importer.internal_auth import internal_headers
from calendar_importer.sync_task import SyncTask, parse_sync_task, resolve_window
from calendar_importer.transformer import transform_events

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-calendar] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# In-process guard against two tasks for the same tenant overlapping *inside this
# worker*. It is not the distributed lock it may look like: a second replica has
# its own copy and knows nothing about this one.
#
# Correctness no longer rests on it. Core refuses to enqueue a connector that
# already has a queued or running SyncRun (see core/scheduler.py:has_in_flight_run),
# so the duplicate task is never published in the first place. This stays as a
# cheap local backstop for a redelivered message.
active_syncs: set[str] = set()


async def credentials(
    tenant_id: str, request_id: str, source_ref: str | None = None
) -> dict[str, Any] | None:
    """Fetch this connector's credential from Core.

    Addressed by connector id when the sync task carries one: a tenant may hold
    several connectors of this type, and the type alone would hand back an
    arbitrary one of them.
    """
    reference = source_ref or "calendar"
    headers = internal_headers(request_id, tenant_id)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/token",
                headers=headers,
            )
            return response.json() if response.status_code == 200 else None
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning(
                "[req_id=%s] Failed to fetch credentials for tenant %s (%s)",
                request_id,
                tenant_id,
                type(exc).__name__,
            )
            return None


async def report_sync_result_to_core(
    task: SyncTask, *, status: str, message: str, points_received: int | None = None
) -> None:
    """Close out the sync run in Core so the next window can adapt."""
    url = (
        f"{settings.CORE_SERVICE_URL}"
        f"/api/v1/internal/data/sources/{task.source_id or task.source_type}/status"
    )
    payload: dict[str, Any] = {
        "sync_status": status,
        "last_sync_message": message,
        "sync_run_id": task.sync_run_id,
    }
    if points_received is not None:
        payload["points_received"] = points_received

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                url, headers=internal_headers(task.request_id, task.tenant_id), json=payload
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning(
                "Could not report sync result to Core (%s)", type(exc).__name__
            )


async def sync_calendar(task: SyncTask, connection: Any) -> int:
    """Fetch, parse and publish one tenant's calendar. Returns points published."""
    secret = await credentials(task.tenant_id, task.request_id, task.source_id)
    if not secret or secret.get("status") != "active":
        logger.info(
            "[req_id=%s] No active calendar connector for tenant %s; staying idle.",
            task.request_id,
            task.tenant_id,
        )
        return 0

    config = secret.get("config") or {}
    # No token is read at all: a calendar is an ICS feed, and the only credential
    # one can carry is inside its own URL.
    source_id = secret.get("source_id")
    if not source_id:
        logger.warning("[req_id=%s] Connector has no source_id; skipping.", task.request_id)
        return 0

    feed = build_feed_config(config)
    window_start, window_end = resolve_window(task, config)

    logger.info(
        "[req_id=%s] Reading calendar for tenant=%s mode=%s auth=%s window=%s..%s",
        task.request_id,
        task.tenant_id,
        task.mode,
        feed.auth_mode,
        window_start.isoformat(),
        window_end.isoformat(),
    )

    body = await fetch_feed(feed)
    events = parse_ics(
        body,
        window_start=window_start,
        window_end=window_end,
        display_timezone=feed.display_timezone,
    )
    points = transform_events(events, task.tenant_id, source_id)

    stream = connection.jetstream()
    published = 0
    for point in points:
        point["request_id"] = task.request_id
        if task.sync_run_id:
            point["sync_run_id"] = task.sync_run_id
        await stream.publish("qs.ingest.calendar", json.dumps(point).encode())
        published += 1

    logger.info(
        "[req_id=%s] Published %d calendar data points from %d occurrences.",
        task.request_id,
        published,
        len(events),
    )
    return published


async def process(message: Any, connection: Any) -> None:
    task = None
    try:
        task = parse_sync_task(json.loads(message.data))
        if task is None:
            logger.warning("Missing tenant_id in calendar task payload; dropping.")
            return

        # Keyed on the connector instance, not the tenant. Keyed on the tenant, a
        # user with a work calendar and a family calendar had the second task
        # discarded as a "duplicate" whenever the first was still running.
        lock_key = f"{task.tenant_id}:{task.source_id or task.source_type}"
        if lock_key in active_syncs:
            logger.info("Calendar sync already running for this connector; skipping duplicate.")
            return

        active_syncs.add(lock_key)
        try:
            published = await sync_calendar(task, connection)
            await report_sync_result_to_core(
                task,
                status="idle",
                message=f"{published} calendar data point(s) published.",
                points_received=published,
            )
        finally:
            active_syncs.discard(lock_key)

    except CalendarAuthError as e:
        logger.error("[req_id=%s] Calendar authentication failed: %s", task.request_id, e)
        await report_sync_result_to_core(task, status="error", message=str(e)[:500])
    except (CalendarFetchError, IcsParseError) as e:
        logger.error("[req_id=%s] Calendar sync failed: %s", task.request_id, e)
        await report_sync_result_to_core(task, status="error", message=str(e)[:500])
    except Exception as exc:  # noqa: BLE001 - task failures must be acknowledged
        logger.error("Error processing calendar task (%s)", type(exc).__name__)
        if task is not None:
            await report_sync_result_to_core(
                task, status="error", message=f"Unexpected error: {type(exc).__name__}"
            )
    finally:
        await message.ack()


async def main() -> None:
    logger.info("Starting Calendar Importer Service...")
    connection = await nats.connect(settings.NATS_URL)
    stream = connection.jetstream()
    try:
        await stream.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except (nats.errors.Error, nats.js.errors.Error, asyncio.TimeoutError) as exc:
        logger.debug(
            "Could not create the task stream; it may already exist (%s)",
            type(exc).__name__,
        )
    await stream.subscribe(
        "qs.task.sync.calendar",
        queue="calendar_importer_task_group",
        cb=lambda msg: process(msg, connection),
    )
    logger.info("Subscribed to NATS subject 'qs.task.sync.calendar'")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
