"""Yazio API v15 Client implementation with rate-limiting & auth error handling."""

import logging
from typing import Any

import httpx

from yazio_importer.config import settings

logger = logging.getLogger(__name__)

CLIENT_ID = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
CLIENT_SECRET = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"


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
    """HTTP Client for Yazio API v15."""

    def __init__(self, access_token: str | None = None, base_url: str | None = None):
        self.access_token = access_token
        self.base_url = (base_url or settings.YAZIO_API_BASE_URL).rstrip("/")

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
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
                    url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
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
                    url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                if res.status_code == 401:
                    raise YazioUnauthorizedError("Refresh token is invalid or expired.")
                res.raise_for_status()
                return res.json()
            except httpx.HTTPStatusError as e:
                raise YazioApiError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                raise YazioApiError(f"Network error: {e}")

    async def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=self._headers, params=params)
                if response.status_code == 401:
                    logger.error("Yazio API 401 Unauthorized.")
                    raise YazioUnauthorizedError("Yazio access token is invalid or expired.")
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Yazio API 429 Rate Limit. Backing off for {retry_after}s.")
                    raise YazioRateLimitError(retry_after=retry_after)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error polling Yazio endpoint {endpoint}: {e}")
                raise YazioApiError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Network error communicating with Yazio API: {e}")
                raise YazioApiError(f"Network request failed: {e}")

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
