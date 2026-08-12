"""WHOOP Developer API v2 Client."""

from datetime import datetime
from typing import Any

import httpx


class WhoopApiError(Exception):
    """WHOOP returned an unsuccessful API response."""


class WhoopUnauthorizedError(WhoopApiError):
    """The WHOOP OAuth access token is invalid or expired."""


class WhoopRateLimitError(WhoopApiError):
    """WHOOP API rate limit exceeded (HTTP 429)."""


class WhoopClient:
    """Async HTTP client for WHOOP Developer API v2 endpoints."""

    def __init__(self, access_token: str, base_url: str = "https://api.prod.whoop.com/developer"):
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")

    async def _request(self, method: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.request(method, url, headers=headers, params=params)
            if res.status_code == 401:
                raise WhoopUnauthorizedError("WHOOP OAuth access token is invalid or expired.")
            if res.status_code == 429:
                raise WhoopRateLimitError("WHOOP API rate limit exceeded.")
            if not res.is_success:
                safe_msg = "Unknown error"
                try:
                    err_payload = res.json()
                    safe_msg = err_payload.get("message", err_payload.get("error", "Unknown error"))
                except Exception:
                    pass
                raise WhoopApiError(f"WHOOP API error {res.status_code}: {safe_msg}")
            payload = res.json()
            if not isinstance(payload, dict):
                raise WhoopApiError("Invalid JSON response payload from WHOOP API.")
            return payload

    async def get_collection(
        self, path: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated WHOOP v2 collection."""
        records: list[dict[str, Any]] = []
        params: dict[str, Any] = {"limit": 25}
        if start:
            params["start"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        if end:
            params["end"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        while True:
            page = await self._request("GET", path, params)
            recs = page.get("records") or []
            for r in recs:
                if isinstance(r, dict):
                    records.append(r)
            token = page.get("next_token")
            if not token:
                break
            params["nextToken"] = token

        return records

    async def get_cycles(self, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        return await self.get_collection("/v2/cycle", start=start, end=end)

    async def get_recoveries(self, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        return await self.get_collection("/v2/recovery", start=start, end=end)

    async def get_sleeps(self, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        return await self.get_collection("/v2/activity/sleep", start=start, end=end)

    async def get_workouts(self, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        return await self.get_collection("/v2/activity/workout", start=start, end=end)
