"""Async client for the Home Assistant REST API.

The template client this replaces called `GET /api/states`, which returns only the
*current* state of every entity. That has no history and no time dimension, so a
sync could never backfill a window and re-running it would produce one point per
entity at whatever moment the sync happened to run.

This uses `/api/history/period/...`, which is the endpoint that actually carries
timestamps, and filters to the entities the tenant selected instead of importing
every entity in the house.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HomeAssistantApiError(RuntimeError):
    """Raised when Home Assistant cannot be queried."""


class HomeAssistantUnauthorizedError(HomeAssistantApiError):
    """Raised on 401/403 — the long-lived access token is wrong or revoked."""


class ProviderClient:
    """Reads historical entity states from a Home Assistant instance."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        entity_ids: list[str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.entity_ids = entity_ids or []

    async def fetch(
        self, start_time: str | None = None, end_time: str | None = None
    ) -> list[dict[str, Any]]:
        """Return a flat list of state changes across the requested window."""
        if not self.token:
            raise HomeAssistantUnauthorizedError(
                "Home Assistant requires a long-lived access token."
            )

        path = "/api/history/period"
        if start_time:
            path = f"{path}/{start_time}"

        params: dict[str, Any] = {}
        if end_time:
            params["end_time"] = end_time
        if self.entity_ids:
            # Without this, Home Assistant returns every entity it knows about.
            params["filter_entity_id"] = ",".join(self.entity_ids)
        params["minimal_response"] = "true"

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept": "application/json",
                    },
                    params=params,
                )
        except httpx.HTTPError as exc:
            raise HomeAssistantApiError(
                f"Home Assistant unreachable: {type(exc).__name__}"
            ) from exc

        if response.status_code in (401, 403):
            raise HomeAssistantUnauthorizedError(
                "Home Assistant rejected the stored access token."
            )
        if response.status_code >= 400:
            raise HomeAssistantApiError(
                f"Home Assistant returned HTTP {response.status_code}"
            )

        return self._flatten(response.json())

    @staticmethod
    def _flatten(payload: Any) -> list[dict[str, Any]]:
        """History comes back as a list of per-entity lists; flatten to state rows."""
        if not isinstance(payload, list):
            return []

        rows: list[dict[str, Any]] = []
        for entry in payload:
            if isinstance(entry, list):
                rows.extend(item for item in entry if isinstance(item, dict))
            elif isinstance(entry, dict):
                rows.append(entry)
        return rows
