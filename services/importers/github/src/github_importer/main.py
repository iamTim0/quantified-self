"""Request-driven GitHub importer publishing exclusively through JetStream.

Reads the authenticated account's own contribution activity with a fine-grained
personal access token the user stored in the dashboard. The token is fetched from
Core per run and never written to disk or `.env` (rule 8), and never appears in a
published event or a log line (rule 12).
"""

import asyncio
import json
import logging
from typing import Any

import httpx
import nats
from shared_schemas import HealthServer, health_payload
from shared_schemas.field_report import FieldReport, FieldReportCollector

from github_importer.client import (
    GitHubApiError,
    GitHubClient,
    GitHubRateLimitError,
    GitHubUnauthorizedError,
)
from github_importer.config import settings
from github_importer.internal_auth import internal_headers
from github_importer.sync_task import SyncTask, parse_sync_task, resolve_window
from github_importer.transformer import transform_window

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-github] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)
nc_client: nats.NATS | None = None


def _health_payload() -> dict[str, Any]:
    """Broker connectivity only.

    Never GitHub reachability and never the token: a healthcheck that needed a
    credential would report a workspace with no connector as unhealthy, and one
    that called GitHub would turn their outage into our restart loop (rule 20).
    """
    connected = nc_client is not None and nc_client.is_connected
    return health_payload(
        settings.SERVICE_NAME,
        status="ok" if connected else "degraded",
        nats_connected=connected,
    )


# In-process guard against two tasks for one connector overlapping inside this
# worker. Not a distributed lock: Core refuses to enqueue a connector that already
# has a queued or running SyncRun, and this is the local backstop for a redelivery.
active_syncs: set[str] = set()


async def credentials(
    tenant_id: str, request_id: str, source_ref: str | None = None
) -> dict[str, Any] | None:
    """Fetch this connector's credential from Core."""
    reference = source_ref or "github"
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
    task: SyncTask,
    *,
    status: str,
    message: str,
    points_received: int | None = None,
    unsupported_fields: int | None = None,
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
    if unsupported_fields is not None:
        payload["unsupported_fields"] = unsupported_fields

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                url, headers=internal_headers(task.request_id, task.tenant_id), json=payload
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Could not report sync result to Core (%s)", type(exc).__name__)


async def publish_field_report(task: SyncTask, report: FieldReport) -> None:
    """Tell Core which payload paths were stored and which were only seen.

    Shape only, never values (rule 19). This is what the Data Quality Center reads
    to say "this arrives and we do not keep it".

    Takes the built `FieldReport` rather than the collector, and serialises it with
    `model_dump()` — `json=` wants something the JSON encoder accepts, and handing
    it the model raised a `TypeError` that this very `except` then swallowed as a
    warning. Every GitHub run filed an empty report and said so once, quietly.
    """
    reference = task.source_id or task.source_type
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/field-report"
    payload = report.model_dump(mode="json")
    payload["sync_run_id"] = task.sync_run_id
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                url,
                headers=internal_headers(task.request_id, task.tenant_id),
                json=payload,
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Could not publish the field report (%s)", type(exc).__name__)


async def sync_github(task: SyncTask, connection: Any) -> tuple[int, int]:
    """Fetch, transform and publish one account's window.

    Returns `(points published, unsupported field count)`.
    """
    secret = await credentials(task.tenant_id, task.request_id, task.source_id)
    if not secret or secret.get("status") != "active":
        logger.info(
            "[req_id=%s] No active GitHub connector for tenant %s; staying idle.",
            task.request_id,
            task.tenant_id,
        )
        return 0, 0

    token = secret.get("access_token")
    source_id = secret.get("source_id")
    if not token:
        # Idle rather than inventing anything (rule 9). A connector with no usable
        # credential is a configuration state, not an error to retry into.
        logger.info("[req_id=%s] GitHub connector has no token; staying idle.", task.request_id)
        return 0, 0
    if not source_id:
        logger.warning("[req_id=%s] Connector has no source_id; skipping.", task.request_id)
        return 0, 0

    config = secret.get("config") or {}
    window_start, window_end = resolve_window(task, config)

    logger.info(
        "[req_id=%s] Reading GitHub for tenant=%s mode=%s window=%s..%s",
        task.request_id,
        task.tenant_id,
        task.mode,
        window_start.isoformat(),
        window_end.isoformat(),
    )

    report = FieldReportCollector()
    client = GitHubClient(token)
    contributions = await client.fetch_window(
        start=window_start, end=window_end, request_id=task.request_id
    )
    points = transform_window(
        contributions,
        task.tenant_id,
        source_id,
        start=window_start,
        end=window_end,
        report=report,
        per_repository=bool(config.get("per_repository", True)),
    )

    stream = connection.jetstream()
    published = 0
    for point in points:
        point["request_id"] = task.request_id
        if task.sync_run_id:
            point["sync_run_id"] = task.sync_run_id
        await stream.publish("qs.ingest.github", json.dumps(point).encode())
        published += 1

    built = report.build()
    await publish_field_report(task, built)
    unsupported = len(built.unmapped)

    logger.info(
        "[req_id=%s] Published %d GitHub data points across %d repositories.",
        task.request_id,
        published,
        len(contributions.repositories),
    )
    return published, unsupported


async def process(message: Any, connection: Any) -> None:
    task = None
    try:
        task = parse_sync_task(json.loads(message.data))
        if task is None:
            logger.warning("Missing tenant_id in GitHub task payload; dropping.")
            return

        lock_key = f"{task.tenant_id}:{task.source_id or task.source_type}"
        if lock_key in active_syncs:
            logger.info("GitHub sync already running for this connector; skipping duplicate.")
            return

        active_syncs.add(lock_key)
        try:
            published, unsupported = await sync_github(task, connection)
            await report_sync_result_to_core(
                task,
                status="idle",
                message=f"{published} GitHub data point(s) published.",
                points_received=published,
                unsupported_fields=unsupported,
            )
        finally:
            active_syncs.discard(lock_key)

    except GitHubUnauthorizedError as exc:
        logger.error("[req_id=%s] GitHub rejected the token: %s", task.request_id, exc)
        await report_sync_result_to_core(task, status="error", message=str(exc)[:500])
    except GitHubRateLimitError as exc:
        # Not an error the operator can act on, and the next scheduled run is inside
        # the reset window. Reported as such rather than as a failure.
        logger.warning("[req_id=%s] GitHub rate limit reached: %s", task.request_id, exc)
        await report_sync_result_to_core(task, status="idle", message=str(exc)[:500])
    except GitHubApiError as exc:
        logger.error("[req_id=%s] GitHub sync failed: %s", task.request_id, exc)
        await report_sync_result_to_core(task, status="error", message=str(exc)[:500])
    except Exception as exc:  # noqa: BLE001 - task failures must be acknowledged
        logger.error("Error processing GitHub task (%s)", type(exc).__name__)
        if task is not None:
            await report_sync_result_to_core(
                task, status="error", message=f"Unexpected error: {type(exc).__name__}"
            )
    finally:
        await message.ack()


async def main() -> None:
    global nc_client
    logger.info("Starting GitHub Importer Service...")
    health_server = HealthServer(settings.HEALTH_PORT, _health_payload)
    await health_server.start()
    nc_client = await nats.connect(settings.NATS_URL)
    try:
        stream = nc_client.jetstream()
        try:
            await stream.add_stream(name="tasks", subjects=["qs.task.sync.>"])
        except (nats.errors.Error, nats.js.errors.Error, asyncio.TimeoutError) as exc:
            logger.debug(
                "Could not create the task stream; it may already exist (%s)",
                type(exc).__name__,
            )
        await stream.subscribe(
            "qs.task.sync.github",
            queue="github_importer_task_group",
            cb=lambda msg: process(msg, nc_client),
        )
        logger.info("Subscribed to NATS subject 'qs.task.sync.github'")
        await asyncio.Event().wait()
    finally:
        if nc_client is not None and not nc_client.is_closed:
            await nc_client.close()
        nc_client = None
        await health_server.close()


if __name__ == "__main__":
    asyncio.run(main())
