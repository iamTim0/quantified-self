"""Core Service Integration Client for Apple Health Importer.

Fetches dynamic connector credentials/token and source_id from Core Data Service DB
per Rule 8 (Stateless Importers & Connector Credentials), and opens and closes the
``SyncRun`` that makes a pushed import visible in the history.
"""

import logging
from typing import Any

import httpx

from apple_health_importer.auth import internal_headers
from apple_health_importer.config import settings

logger = logging.getLogger(__name__)


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
        except Exception as e:
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
        except Exception as exc:
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
) -> None:
    """Close the run out so the history shows what happened."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/status"
    payload: dict[str, Any] = {
        "sync_status": status,
        "last_sync_message": message[:512],
        "sync_run_id": sync_run_id,
    }
    if points_received is not None:
        payload["points_received"] = points_received

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=internal_headers(req_id, tenant_id), json=payload)
        except Exception as exc:
            logger.warning(f"Could not report sync result to Core: {exc}")


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
        except Exception as exc:
            logger.warning(f"Could not send the field report to Core: {exc}")
