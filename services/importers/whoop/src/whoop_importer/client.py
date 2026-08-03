"""Async client generated from the WHOOP OpenAPI collection operations.

Regenerate the client after replacing ``openapi/whoop.json`` by running the
command documented in this service's README. This small facade is retained so
the importer is insulated from generated package naming changes.
"""

from datetime import datetime
from typing import Any, AsyncIterator

import httpx


class WhoopApiError(Exception):
    """WHOOP returned an unsuccessful API response."""


class WhoopUnauthorizedError(WhoopApiError):
    """The OAuth access token is invalid or expired."""


class WhoopClient:
    def __init__(self, access_token: str, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
            transport=transport,
        )

    async def __aenter__(self) -> "WhoopClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def _page(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        if response.status_code == 401:
            raise WhoopUnauthorizedError("WHOOP OAuth token is invalid or expired")
        if not response.is_success:
            raise WhoopApiError(f"WHOOP API returned HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise WhoopApiError("WHOOP API returned an invalid collection")
        return payload

    async def iter_collection(
        self, path: str, *, start: datetime | None = None, end: datetime | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        params: dict[str, Any] = {"limit": 25}
        if start:
            params["start"] = start.isoformat()
        if end:
            params["end"] = end.isoformat()
        while True:
            page = await self._page(path, params)
            for record in page.get("records", []):
                if isinstance(record, dict):
                    yield record
            token = page.get("next_token")
            if not token:
                break
            params["nextToken"] = token

    def cycles(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        return self.iter_collection("/v2/cycle", **kwargs)

    def recoveries(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        return self.iter_collection("/v2/recovery", **kwargs)

    def sleeps(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        return self.iter_collection("/v2/activity/sleep", **kwargs)

    def workouts(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        return self.iter_collection("/v2/activity/workout", **kwargs)
