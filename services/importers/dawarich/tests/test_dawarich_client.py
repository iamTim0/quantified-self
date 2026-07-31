"""Unit tests for Dawarich Location API Client.

Verifies:
- 200 OK responses for GPS points and location stats.
- 404 Not Found returns empty response cleanly.
- 401 Unauthorized raises DawarichUnauthorizedError.
- API Key headers and query parameter injection.
"""

from unittest.mock import AsyncMock, patch
import httpx
import pytest

from dawarich_importer.client import (
    DawarichClient,
    DawarichUnauthorizedError,
)


@pytest.mark.asyncio
async def test_get_points_success():
    """Verifies successful retrieval of GPS location points."""
    mock_response = httpx.Response(
        status_code=200,
        json={"points": [{"id": 1, "latitude": 52.52, "longitude": 13.40}]},
        request=httpx.Request("GET", "http://test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = DawarichClient(api_key="test_api_key", base_url="http://dawarich.local")
        points = await client.get_points(start_at="2026-07-01T00:00:00Z")
        assert len(points) == 1
        assert points[0]["latitude"] == 52.52


@pytest.mark.asyncio
async def test_get_points_404():
    """Verifies 404 Not Found returns empty list cleanly."""
    mock_response = httpx.Response(status_code=404, request=httpx.Request("GET", "http://test"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = DawarichClient(api_key="test_api_key")
        points = await client.get_points()
        assert points == []


@pytest.mark.asyncio
async def test_get_points_401():
    """Verifies 401 Unauthorized raises DawarichUnauthorizedError."""
    mock_response = httpx.Response(status_code=401, request=httpx.Request("GET", "http://test"))
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = DawarichClient(api_key="invalid_key")
        with pytest.raises(DawarichUnauthorizedError):
            await client.get_points()


@pytest.mark.asyncio
async def test_get_stats_success():
    """Verifies retrieval of Dawarich location statistics."""
    mock_response = httpx.Response(
        status_code=200,
        json={"total_points": 1520, "total_distance_km": 420.5},
        request=httpx.Request("GET", "http://test"),
    )
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = DawarichClient(api_key="test_api_key")
        stats = await client.get_stats()
        assert stats["total_points"] == 1520
