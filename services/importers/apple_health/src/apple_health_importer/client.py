"""Core Service Integration Client for Apple Health Importer.

Fetches dynamic connector credentials/token and source_id from Core Data Service DB
per Rule 8 (Stateless Importers & Connector Credentials), and opens and closes the
``SyncRun`` that makes a pushed or uploaded import visible in the history.

The two ways in authenticate differently, on purpose. A **push** presents an API key
bound to a connector, and `auth.resolve_api_key` turns it into a tenant. An **upload**
comes from a signed-in browser, so the credential is the user's session token — and
this service deliberately cannot check one: Core keeps ``JWT_SECRET`` apart from
``INTERNAL_SERVICE_SECRET`` so a compromised importer cannot mint user tokens, and
handing importers the signing key to save an HTTP call would undo exactly that. The
token therefore goes back to Core, which answers with the workspace it belongs to.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from apple_health_importer.auth import internal_headers
from apple_health_importer.config import settings

logger = logging.getLogger(__name__)

STATUS_REPORT_ATTEMPTS = 4
STATUS_REPORT_DELAYS = (0.1, 0.5, 1.5)


@dataclass(frozen=True)
class UploadTarget:
    """The connector an upload was accepted for."""

    tenant_id: str
    source_id: str
    source_type: str


def bearer_token(authorization: str | None) -> str:
    """The token from an ``Authorization: Bearer`` header, or a 401."""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token:
            return token
    raise HTTPException(status_code=401, detail="An upload requires a signed-in session.")


async def resolve_session(token: str, *, req_id: str) -> str:
    """The workspace a session token belongs to, as Core sees it."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/auth/me"
    headers = {"Authorization": f"Bearer {token}", "X-Request-ID": req_id}

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
        except httpx.RequestError as exc:
            logger.warning("[req_id=%s] Could not reach Core to resolve the session: %s", req_id, exc)
            raise HTTPException(status_code=503, detail="Core Data Service unavailable.") from None

    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Session is not valid.")

    tenant_id = res.json().get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Session names no workspace.")
    return str(tenant_id)


async def resolve_upload_target(tenant_id: str, source_id: str, *, req_id: str) -> UploadTarget:
    """Confirm the connector exists, belongs to this workspace, and is an Apple Health one."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/token"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=internal_headers(req_id, tenant_id))
        except httpx.RequestError as exc:
            logger.warning("[req_id=%s] Could not reach Core to resolve the connector: %s", req_id, exc)
            raise HTTPException(status_code=503, detail="Core Data Service unavailable.") from None

    if res.status_code != 200:
        # Core resolves a connector inside one tenant, so another workspace's id is a
        # 404 here. Repeating that verdict keeps this endpoint from becoming a way to
        # find out which connector ids exist.
        raise HTTPException(status_code=404, detail="Connector not found.")

    data = res.json()
    source_type = str(data.get("source_type") or "")
    if source_type != settings.SOURCE_TYPE:
        raise HTTPException(
            status_code=409,
            detail=f"That connector is a {source_type} connector, not an Apple Health one.",
        )
    return UploadTarget(tenant_id=tenant_id, source_id=str(data["source_id"]), source_type=source_type)


async def get_ingest_policies(
    tenant_id: str, source_id: str, *, req_id: str
) -> dict[str, dict[str, Any]]:
    """Fetch tenant metric policies; registry defaults remain a safe fallback."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/ingest-policy"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url, headers=internal_headers(req_id, tenant_id))
        if response.status_code == 200:
            payload = response.json()
            policies = payload.get("policies")
            if isinstance(policies, dict):
                return policies
        logger.warning(
            "[req_id=%s] Core did not return ingest policies (status=%s); using registry defaults.",
            req_id,
            response.status_code,
        )
    except Exception as exc:  # noqa: BLE001 - defaults keep import availability intact
        logger.warning(
            "[req_id=%s] Could not fetch ingest policies (%s); using registry defaults.",
            req_id,
            type(exc).__name__,
        )
    return {}


async def get_connector_credentials_from_core(
    tenant_id: str,
    req_id: str = "req_apple_health_auth",
    source_ref: str | None = None,
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted token & source_id for an Apple Health connector.

    Addressed by connector id when the caller knows one — a tenant may hold several
    Apple Health connectors, and the bare type would return an arbitrary one.
    """
    reference = source_ref or settings.SOURCE_TYPE
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{reference}/token"
    headers = internal_headers(req_id, tenant_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active":
                    # No synthetic fallback. It used to be
                    # `uuid5(NAMESPACE_DNS, f"{tenant_id}:{source_type}")`, which
                    # collapsed every instance of a type onto one id — and that id
                    # is the second component of every idempotency key, so two
                    # phones would have written one indistinguishable series.
                    source_id = data.get("source_id")
                    if not source_id:
                        logger.warning(
                            "Core returned no source_id for tenant %s; refusing to guess one.",
                            tenant_id,
                        )
                        return None, None, None
                    return data.get("access_token"), source_id, data.get("config", {})
            return None, None, None
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None


async def open_sync_run(
    tenant_id: str,
    source_id: str,
    *,
    req_id: str,
    trigger: str = "push",
    points_expected: int | None = None,
    message: str | None = None,
) -> str | None:
    """Open a run so a pushed import is visible while it is happening.

    Returns the run id, or ``None`` when Core cannot be reached — the import then
    proceeds unrecorded rather than being refused, because the data has already
    been handed to us and dropping it would be worse than losing its audit row.
    """
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/sync-runs"
    payload: dict[str, Any] = {"trigger": trigger, "request_id": req_id}
    if points_expected is not None:
        payload["points_expected"] = points_expected
    if message:
        payload["message"] = message

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.post(url, headers=internal_headers(req_id, tenant_id), json=payload)
            if res.status_code == 201:
                return res.json().get("sync_run_id")
            logger.warning("Could not open a sync run: Core returned %s", res.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not open a sync run: {exc}")
    return None


async def close_sync_run(
    tenant_id: str,
    source_id: str,
    sync_run_id: str | None,
    *,
    req_id: str,
    status: str,
    message: str,
    points_received: int | None = None,
    points_rejected: int | None = None,
    unsupported_fields: int | None = None,
    backlog: int | None = None,
    provider_window_start: str | None = None,
    provider_window_end: str | None = None,
    provider_exported_at: str | None = None,
    code: str | None = None,
    params: dict[str, str | int | float | bool] | None = None,
) -> bool:
    """Close the run out so the history shows what happened.

    A final status is the only thing that turns an open run into a terminal audit
    record. Treating a dropped HTTP response as success left the dashboard loading
    forever, so transient transport and 5xx failures are retried and every response
    is checked. Four client errors are not retried: the tenant/source/run boundary is
    wrong and repeating it cannot repair that request.
    """
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/status"
    payload: dict[str, Any] = {
        "sync_status": status,
        "last_sync_message": message[:512],
        "sync_run_id": sync_run_id,
    }
    if points_received is not None:
        payload["points_received"] = points_received
    if points_rejected is not None:
        payload["points_rejected"] = points_rejected
    if unsupported_fields is not None:
        payload["unsupported_fields"] = unsupported_fields
    if backlog is not None:
        payload["backlog"] = backlog
    if provider_window_start is not None:
        payload["provider_window_start"] = provider_window_start
    if provider_window_end is not None:
        payload["provider_window_end"] = provider_window_end
    if provider_exported_at is not None:
        payload["provider_exported_at"] = provider_exported_at
    if code is not None:
        payload["code"] = code
    if params is not None:
        payload["params"] = params

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(1, STATUS_REPORT_ATTEMPTS + 1):
            try:
                response = await client.post(
                    url, headers=internal_headers(req_id, tenant_id), json=payload
                )
            except Exception as exc:  # noqa: BLE001 - final status must not crash the worker
                if attempt == STATUS_REPORT_ATTEMPTS:
                    logger.warning(
                        "[req_id=%s] Could not report final sync result to Core after %d attempts (%s).",
                        req_id,
                        attempt,
                        type(exc).__name__,
                    )
                    return False
            else:
                if 200 <= response.status_code < 300:
                    return True
                if response.status_code < 500 or attempt == STATUS_REPORT_ATTEMPTS:
                    logger.warning(
                        "[req_id=%s] Core rejected final sync result (status=%s).",
                        req_id,
                        response.status_code,
                    )
                    return False
            await asyncio.sleep(STATUS_REPORT_DELAYS[min(attempt - 1, len(STATUS_REPORT_DELAYS) - 1)])
    return False


async def report_sync_progress(
    tenant_id: str,
    source_id: str,
    sync_run_id: str | None,
    *,
    req_id: str,
    points_expected: int | None = None,
    points_received: int | None = None,
    points_rejected: int | None = None,
    unsupported_fields: int | None = None,
    backlog: int | None = None,
    provider_window_start: str | None = None,
    provider_window_end: str | None = None,
    provider_exported_at: str | None = None,
    message: str | None = None,
) -> None:
    """Tell Core a known total without closing the still-running import."""
    if not sync_run_id:
        return
    url = (
        f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/"
        f"{source_id}/sync-runs/{sync_run_id}/progress"
    )
    payload: dict[str, Any] = {}
    if points_expected is not None:
        payload["points_expected"] = points_expected
    if points_received is not None:
        payload["points_received"] = points_received
    if points_rejected is not None:
        payload["points_rejected"] = points_rejected
    if unsupported_fields is not None:
        payload["unsupported_fields"] = unsupported_fields
    if backlog is not None:
        payload["backlog"] = backlog
    if provider_window_start is not None:
        payload["provider_window_start"] = provider_window_start
    if provider_window_end is not None:
        payload["provider_window_end"] = provider_window_end
    if provider_exported_at is not None:
        payload["provider_exported_at"] = provider_exported_at
    if message:
        payload["message"] = message[:512]

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=internal_headers(req_id, tenant_id), json=payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not report sync progress to Core: {exc}")


async def send_field_report(
    tenant_id: str,
    source_id: str,
    report: Any,
    *,
    req_id: str,
    sync_run_id: str | None = None,
) -> None:
    """Tell Core which provider fields this import used, and which it ignored.

    Best-effort: an import that produced data must not fail because its bookkeeping
    could not be filed. The report carries paths and value *kinds* only — never a
    value — so it is safe to send and safe to keep.
    """
    payload = report.model_dump()
    payload["sync_run_id"] = sync_run_id
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/field-report"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=internal_headers(req_id, tenant_id), json=payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not send the field report to Core: {exc}")
