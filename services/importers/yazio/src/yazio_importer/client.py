"""Yazio API v15 Client implementation with rate-limiting & auth error handling."""

import asyncio
import logging
import random
from typing import Any

import httpx

from yazio_importer.config import settings

logger = logging.getLogger(__name__)

CLIENT_ID = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
CLIENT_SECRET = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"

# ANTI-BAN & RATE PROTECTION CONFIGURATION
REQUEST_PACING_SECONDS = 0.25  # Pacing delay between HTTP requests
USER_AGENT = "Yazio/15.2.0 (iPhone; iOS 17.5.1; Scale/3.00)"


class YazioApiError(Exception):
    """Base exception for Yazio API errors."""


class YazioUnauthorizedError(YazioApiError):
    """Raised when Yazio API returns 401 Unauthorized."""


class YazioRateLimitError(YazioApiError):
    """Raised when Yazio API returns 429 Rate Limit Exceeded."""

    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after


class YazioClient:
    """HTTP Client for Yazio API v15 with Anti-Ban rate protection."""

    def __init__(self, access_token: str | None = None, base_url: str | None = None):
        self.access_token = access_token
        self.base_url = (base_url or settings.YAZIO_API_BASE_URL).rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def login(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate via OAuth password flow and return token response dict."""
        url = f"{self.base_url}/v15/oauth/token"
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": username,
            "password": password,
            "grant_type": "password",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.post(
                    url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT}
                )
                if res.status_code == 401:
                    raise YazioUnauthorizedError("Invalid credentials provided to Yazio API.")
                res.raise_for_status()
                return res.json()
            except httpx.HTTPStatusError as e:
                raise YazioApiError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                raise YazioApiError(f"Network error: {e}")

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh access token using refresh_token grant."""
        url = f"{self.base_url}/v15/oauth/token"
        data = {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                res = await client.post(
                    url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT}
                )
                if res.status_code == 401:
                    raise YazioUnauthorizedError("Refresh token is invalid or expired.")
                res.raise_for_status()
                return res.json()
            except httpx.HTTPStatusError as e:
                raise YazioApiError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                raise YazioApiError(f"Network error: {e}")

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None, max_retries: int = 3) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        for attempt in range(max_retries):
            # Anti-ban pacing delay with randomized jitter between requests
            pacing_delay = REQUEST_PACING_SECONDS + random.uniform(0.05, 0.15)
            await asyncio.sleep(pacing_delay)

            async with httpx.AsyncClient(timeout=15.0) as client:
                try:
                    response = await client.get(url, headers=self._headers, params=params)
                    if response.status_code == 401:
                        logger.error("Yazio API 401 Unauthorized.")
                        raise YazioUnauthorizedError("Yazio access token is invalid or expired.")
                    if response.status_code == 404:
                        logger.debug(f"Yazio endpoint '{endpoint}' returned 404 Not Found (no entry for date/resource).")
                        return {}
                    if response.status_code == 429:
                        retry_after = int(response.headers.get("Retry-After", 10))
                        if attempt == max_retries - 1:
                            raise YazioRateLimitError(retry_after=retry_after)
                        backoff = retry_after + (attempt * 5) + random.uniform(1.0, 3.0)
                        logger.warning(
                            f"Yazio API 429 Rate Limit (attempt {attempt + 1}/{max_retries}). "
                            f"Backing off safely for {backoff:.1f}s to avoid IP ban..."
                        )
                        await asyncio.sleep(backoff)
                        continue
                    response.raise_for_status()
                    return response.json()
                except YazioUnauthorizedError:
                    raise
                except httpx.HTTPStatusError as e:
                    if attempt == max_retries - 1:
                        logger.error(f"HTTP error polling Yazio endpoint {endpoint}: {e}")
                        raise YazioApiError(f"HTTP {e.response.status_code}: {e.response.text}")
                    await asyncio.sleep(2.0 ** attempt)
                except httpx.RequestError as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Network error communicating with Yazio API: {e}")
                        raise YazioApiError(f"Network request failed: {e}")
                    await asyncio.sleep(2.0 ** attempt)

        return {}

    async def get_consumed_items(self, date: str) -> dict[str, Any]:
        """Fetch consumed items diary document for a given ISO date (YYYY-MM-DD)."""
        return await self._get("v15/user/consumed-items", params={"date": date})

    async def get_daily_summary(self, date: str) -> dict[str, Any]:
        """Fetch daily nutrition summary (calories, macros, water) for a given date."""
        try:
            return await self._get("v15/user/summary", params={"date": date})
        except YazioApiError:
            return {}

    async def get_product(self, product_id: str) -> dict[str, Any]:
        """Fetch product details for a given product_id."""
        try:
            return await self._get(f"v15/products/{product_id}")
        except YazioApiError:
            return {}

    async def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        """Fetch recipe details for a given recipe_id."""
        try:
            return await self._get(f"v15/recipes/{recipe_id}")
        except YazioApiError:
            return {}

    async def get_user_profile(self) -> dict[str, Any]:
        """Fetch user profile information."""
        return await self._get("v15/user")
