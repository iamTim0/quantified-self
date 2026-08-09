"""Core Service Integration Client for Streak Importer.

Fetches dynamic connector credentials & source_id from Core Data Service DB
per Rule 8 (Stateless Importers & Connector Credentials).
"""

import logging
from typing import Any

import httpx

from streak_importer.auth import internal_headers
from streak_importer.config import settings

logger = logging.getLogger(__name__)


async def open_sync_run(
    tenant_id: str,
    source_id: str,
    *,
    req_id: str,
    points_expected: int | None = None,
    message: str | None = None,
) -> str | None:
    """Open a run for an inbound Streak webhook before transformation begins."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/sync-runs"
    payload: dict[str, Any] = {"trigger": "push", "request_id": req_id}
    if points_expected is not None:
        payload["points_expected"] = points_expected
    if message:
        payload["message"] = message

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                url,
                headers=internal_headers(req_id, tenant_id),
                json=payload,
            )
            if response.status_code == 201:
                return response.json().get("sync_run_id")
            logger.warning("Could not open a Streak sync run: Core returned %s", response.status_code)
        except Exception as exc:
            logger.warning("Could not open a Streak sync run: %s", exc)
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
    """Close the Streak webhook run with its final outcome."""
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
            await client.post(
                url,
                headers=internal_headers(req_id, tenant_id),
                json=payload,
            )
        except Exception as exc:
            logger.warning("Could not report Streak sync result to Core: %s", exc)


async def report_sync_progress(
    tenant_id: str,
    source_id: str,
    sync_run_id: str | None,
    *,
    req_id: str,
    points_expected: int | None = None,
    points_received: int | None = None,
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
    if message:
        payload["message"] = message[:512]

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(url, headers=internal_headers(req_id, tenant_id), json=payload)
        except Exception as exc:
            logger.warning("Could not report Streak sync progress to Core: %s", exc)


async def get_connector_credentials_from_core(
    tenant_id: str, req_id: str = "req_streak_auth"
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted token & source_id for Streak connector from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{settings.SOURCE_TYPE}/token"
    headers = internal_headers(req_id, tenant_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active":
                    token = data.get("access_token")
                    source_id = data.get("source_id")
                    if not source_id:
                        # No synthetic fallback. It collapsed every instance of a
                        # type onto one id -- and that id is the second component
                        # of every idempotency key, so two devices would have
                        # written one indistinguishable series.
                        logger.warning(
                            "Core returned no source_id for tenant %s; refusing to guess one.",
                            tenant_id,
                        )
                        return None, None, None
                    # "get" was a typo for "config" that silently shadowed the real
                    # connector configuration whenever Core emitted that key.
                    return token, source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None
