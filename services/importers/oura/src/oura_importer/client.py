"""Oura API v2 Client implementation with rate-limiting & auth error handling.

Maps to Fizzbee Invariants:
- TokenRefreshEnforced (handles HTTP 401)
- NoDataLossOnRateLimit (handles HTTP 429 backoff)
"""

import asyncio
import logging
from typing import Any, Dict, Optional
import httpx
from oura_importer.config import settings

logger = logging.getLogger(__name__)

class OuraApiError(Exception):
    """Base exception for Oura API errors."""
    pass

class OuraUnauthorizedError(OuraApiError):
    """Raised when Oura API returns 401 Unauthorized (invalid/expired access token)."""
    pass

class OuraRateLimitError(OuraApiError):
    """Raised when Oura API returns 429 Rate Limit Exceeded."""
    def __init__(self, retry_after: int = 60):
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")
        self.retry_after = retry_after

class OuraClient:
    def __init__(self, access_token: Optional[str] = None, base_url: Optional[str] = None):
        self.access_token = access_token or settings.OURA_ACCESS_TOKEN
        self.base_url = (base_url or settings.OURA_API_BASE_URL).rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(url, headers=self.headers, params=params)
                
                if response.status_code == 401:
                    logger.error("Oura API 401 Unauthorized: token expired or invalid.")
                    raise OuraUnauthorizedError("Oura Access Token is invalid or expired.")
                    
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Oura API 429 Rate Limit. Backing off for {retry_after}s.")
                    raise OuraRateLimitError(retry_after=retry_after)
                    
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error polling Oura endpoint {endpoint}: {e}")
                raise OuraApiError(f"HTTP {e.response.status_code}: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Network error communicating with Oura API: {e}")
                raise OuraApiError(f"Network request failed: {e}")

    async def get_daily_sleep(self, start_date: str, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Fetch daily sleep documents from Oura API v2."""
        params = {"start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        return await self._get("v2/usercollection/daily_sleep", params=params)

    async def get_daily_readiness(self, start_date: str, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Fetch daily readiness documents from Oura API v2."""
        params = {"start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        return await self._get("v2/usercollection/daily_readiness", params=params)

    async def get_daily_activity(self, start_date: str, end_date: Optional[str] = None) -> Dict[str, Any]:
        """Fetch daily activity documents from Oura API v2."""
        params = {"start_date": start_date}
        if end_date:
            params["end_date"] = end_date
        return await self._get("v2/usercollection/daily_activity", params=params)
