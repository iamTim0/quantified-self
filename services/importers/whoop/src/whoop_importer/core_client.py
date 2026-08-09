"""Everything this importer asks the Core service, for the upload path.

Two different questions live here, and they authenticate differently on purpose.

*Who is uploading* is a question about a **user session**. An upload comes from a
signed-in browser rather than from a device holding an API key, so the credential is
the user's own token — and this service deliberately cannot validate it. Core keeps
``JWT_SECRET`` apart from ``INTERNAL_SERVICE_SECRET`` so that a compromised importer
cannot mint user tokens; giving importers the signing key to save one HTTP call would
undo exactly that. So the token goes back to Core, which answers with the workspace it
belongs to.

*What the upload may touch* is then a question about a connector, asked with this
service's own internal credential and the workspace as explicit delegation. Core
resolves a connector within one tenant only, so a source id belonging to somebody else
comes back as a 404 rather than as somebody else's data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException

from whoop_importer.config import settings
from whoop_importer.internal_auth import internal_headers

logger = logging.getLogger(__name__)


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
            raise HTTPException(
                status_code=503, detail="Core Data Service unavailable."
            ) from None

    if res.status_code != 200:
        raise HTTPException(status_code=401, detail="Session is not valid.")

    tenant_id = res.json().get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Session names no workspace.")
    return str(tenant_id)


async def resolve_upload_target(tenant_id: str, source_id: str, *, req_id: str) -> UploadTarget:
    """Confirm the connector exists, belongs to this workspace, and is a WHOOP one."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{source_id}/token"

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=internal_headers(req_id, tenant_id))
        except httpx.RequestError as exc:
            logger.warning("[req_id=%s] Could not reach Core to resolve the connector: %s", req_id, exc)
            raise HTTPException(
                status_code=503, detail="Core Data Service unavailable."
            ) from None

    if res.status_code != 200:
        # Core resolves a connector inside one tenant, so another workspace's id is
        # a 404 here. Repeating that verdict keeps this endpoint from becoming a way
        # to find out which connector ids exist.
        raise HTTPException(status_code=404, detail="Connector not found.")

    data = res.json()
    source_type = str(data.get("source_type") or "")
    if source_type != "whoop":
        raise HTTPException(
            status_code=409,
            detail=f"That connector is a {source_type} connector, not a WHOOP one.",
        )
    return UploadTarget(tenant_id=tenant_id, source_id=str(data["source_id"]), source_type=source_type)


async def open_sync_run(
    tenant_id: str,
    source_id: str,
    *,
    req_id: str,
    trigger: str = "upload",
    points_expected: int | None = None,
    message: str | None = None,
) -> str | None:
    """Open a run so an upload is visible while it is being published.

    Returns the run id, or ``None`` when Core cannot be reached — the import then
    proceeds unrecorded rather than being refused, because the file has already been
    handed to us and dropping it would be worse than losing its audit row.
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
            logger.warning(f"Could not report sync progress to Core: {exc}")


async def send_field_report(
    tenant_id: str,
    source_id: str,
    report: Any,
    *,
    req_id: str,
    sync_run_id: str | None = None,
) -> None:
    """Tell Core which export columns this import used, and which it ignored.

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
