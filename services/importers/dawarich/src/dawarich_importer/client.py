"""Dawarich Location API v1 Client implementation with rate-limiting & auth error handling."""

import asyncio
import logging
import random
from typing import Any

import httpx

from dawarich_importer.config import settings

logger = logging.getLogger(__name__)

REQUEST_PACING_SECONDS = 0.2
USER_AGENT = "QuantifiedSelf-DawarichImporter/1.0.0"


class DawarichApiError(Exception):
    """Base exception for Dawarich API errors."""


class DawarichUnauthorizedError(DawarichApiError):
    """Raised when Dawarich API returns 401 Unauthorized."""


class DawarichRateLimitError(DawarichApiError):
    """Raised when Dawarich API returns 429 Rate Limit Exceeded."""

    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class DawarichClient:
    """HTTP Client for self-hosted Dawarich location API."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = (base_url or settings.DAWARICH_API_BASE_URL).rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        return headers

    async def _get(
        self, endpoint: str, params: dict[str, Any] | None = None, max_retries: int = 3
    ) -> dict[str, Any] | list[Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query_params = dict(params or {})
        if self.api_key:
            query_params["api_key"] = self.api_key

        for attempt in range(max_retries):
            pacing_delay = REQUEST_PACING_SECONDS + random.uniform(0.05, 0.1)
            await asyncio.sleep(pacing_delay)

            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    response = await client.get(url, headers=self._headers, params=query_params)
                    if response.status_code == 401:
                        logger.error("Dawarich API 401 Unauthorized.")
                        raise DawarichUnauthorizedError("Dawarich API key is invalid or expired.")
                    if response.status_code == 404:
                        logger.debug(f"Dawarich endpoint '{endpoint}' returned 404 Not Found.")
                        return {}
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 10))
                        if attempt == max_retries - 1:
                            raise DawarichRateLimitError(retry_after=retry_after)
                        await asyncio.sleep(retry_after + 1.0)
                        continue
                    response.raise_for_status()
                    return response.json()
                except DawarichUnauthorizedError:
                    raise
                except httpx.HTTPStatusError as e:
                    if attempt == max_retries - 1:
                        logger.error(f"HTTP error polling Dawarich endpoint {endpoint}: {e}")
                        raise DawarichApiError(f"HTTP {e.response.status_code}: {e.response.text}")
                    await asyncio.sleep(2.0 ** attempt)
                except httpx.RequestError as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Network error communicating with Dawarich API: {e}")
                        raise DawarichApiError(f"Network request failed: {e}")
                    await asyncio.sleep(2.0 ** attempt)

        return {}

    async def get_points(self, start_at: str | None = None, end_at: str | None = None, per_page: int = 500) -> list[dict[str, Any]]:
        """Fetch GPS points recorded in Dawarich for a given time window."""
        params: dict[str, Any] = {"per_page": per_page}
        if start_at:
            params["start_at"] = start_at
        if end_at:
            params["end_at"] = end_at

        res = await self._get("api/v1/points", params=params)
        if isinstance(res, list):
            return res
        if isinstance(res, dict):
            return res.get("points") or res.get("data") or []
        return []

    async def get_stats(self) -> dict[str, Any]:
        """Fetch general location stats from Dawarich."""
        res = await self._get("api/v1/stats")
        return res if isinstance(res, dict) else {}
