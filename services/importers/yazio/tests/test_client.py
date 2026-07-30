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
    mock_response = httpx.Response(
        status_code=200,
        json={"items": [{"name": "Apple", "calories": 95}]},
        request=httpx.Request("GET", "http://test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = YazioClient(access_token="test_token")
        res = await client.get_consumed_items(date="2026-07-26")
        assert "items" in res
        assert res["items"][0]["name"] == "Apple"


@pytest.mark.asyncio
async def test_get_consumed_items_401():
    mock_response = httpx.Response(status_code=401)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = YazioClient(access_token="invalid_token")
        with pytest.raises(YazioUnauthorizedError):
            await client.get_consumed_items(date="2026-07-26")


@pytest.mark.asyncio
async def test_get_consumed_items_429():
    mock_response = httpx.Response(status_code=429, headers={"Retry-After": "30"})
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = YazioClient(access_token="test_token")
        with pytest.raises(YazioRateLimitError) as exc_info:
            await client.get_consumed_items(date="2026-07-26")
        assert exc_info.value.retry_after == 30
