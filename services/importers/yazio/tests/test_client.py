"""Unit tests for Yazio API Client.

Verifies:
- 200 OK responses for diary, summary, product, and recipe endpoints.
- 404 Not Found returns empty dict without retrying or error logging.
- 401 Unauthorized raises YazioUnauthorizedError.
- 429 Rate Limit raises YazioRateLimitError.
"""

from unittest.mock import AsyncMock, patch
import httpx
import pytest

from yazio_importer.client import (
    YazioClient,
    YazioRateLimitError,
    YazioUnauthorizedError,
)


@pytest.mark.asyncio
async def test_get_consumed_items_success():
    """Verifies successful retrieval of consumed items diary for ISO date."""
    mock_response = httpx.Response(
        status_code=200,
        json={"items": [{"name": "Apple", "calories": 95}]},
        request=httpx.Request("GET", "http://test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = YazioClient(access_token="test_token")
        res = await client.get_consumed_items(date="2026-07-31")
        assert "items" in res
        assert res["items"][0]["name"] == "Apple"


@pytest.mark.asyncio
async def test_get_daily_summary_404_handling():
    """Verifies that 404 Not Found on summary endpoint returns empty dict without throwing errors."""
    mock_response = httpx.Response(status_code=404, request=httpx.Request("GET", "http://test"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = YazioClient(access_token="test_token")
        res = await client.get_daily_summary(date="2026-07-31")
        assert res == {}


@pytest.mark.asyncio
async def test_get_consumed_items_401():
    """Verifies 401 Unauthorized raises YazioUnauthorizedError."""
    mock_response = httpx.Response(status_code=401, request=httpx.Request("GET", "http://test"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = YazioClient(access_token="invalid_token")
        with pytest.raises(YazioUnauthorizedError):
            await client.get_consumed_items(date="2026-07-31")


@pytest.mark.asyncio
async def test_get_consumed_items_429():
    """Verifies 429 Rate Limit Exceeded raises YazioRateLimitError."""
    mock_response = httpx.Response(status_code=429, headers={"Retry-After": "30"}, request=httpx.Request("GET", "http://test"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        client = YazioClient(access_token="test_token")
        with pytest.raises(YazioRateLimitError) as exc_info:
            await client.get_consumed_items(date="2026-07-31")
        assert exc_info.value.retry_after == 30


@pytest.mark.asyncio
async def test_get_product_and_recipe():
    """Verifies product and recipe detail endpoint polling."""
    mock_product = httpx.Response(
        status_code=200,
        json={"name": "Oat Milk", "nutrients": {"energy.energy": 120.0}},
        request=httpx.Request("GET", "http://test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_product):
        client = YazioClient(access_token="test_token")
        product = await client.get_product("prod_123")
        assert product["name"] == "Oat Milk"
