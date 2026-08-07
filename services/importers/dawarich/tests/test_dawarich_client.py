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
async def test_get_points_follows_pagination():
    """Everything past the first page used to be silently dropped.

    The client requested per_page=500 once and returned that page, so any window
    with more than 500 points lost the rest without any error.
    """
    pages = [
        [{"id": i, "latitude": 52.0, "longitude": 13.0} for i in range(500)],
        [{"id": 500 + i, "latitude": 52.1, "longitude": 13.1} for i in range(500)],
        [{"id": 1000 + i, "latitude": 52.2, "longitude": 13.2} for i in range(37)],
    ]
    calls: list[int] = []

    async def fake_get(self, url, headers=None, params=None):  # noqa: ANN001
        page = params.get("page", 1)
        calls.append(page)
        body = pages[page - 1] if page <= len(pages) else []
        return httpx.Response(
            status_code=200,
            json={"points": body},
            request=httpx.Request("GET", url),
        )

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = DawarichClient(api_key="k", base_url="http://dawarich.local")
        points = await client.get_points(start_at="2026-07-01T00:00:00Z")

    assert len(points) == 1037
    assert calls == [1, 2, 3], "should stop on the short final page"
    assert points[-1]["id"] == 1036


@pytest.mark.asyncio
async def test_get_points_stops_when_server_ignores_page_parameter():
    """A server that returns page 1 forever must not loop indefinitely."""
    page_one = [{"id": i, "latitude": 52.0, "longitude": 13.0} for i in range(500)]
    calls = {"n": 0}

    async def fake_get(self, url, headers=None, params=None):  # noqa: ANN001
        calls["n"] += 1
        return httpx.Response(
            status_code=200,
            json={"points": page_one},
            request=httpx.Request("GET", url),
        )

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = DawarichClient(api_key="k")
        points = await client.get_points()

    # Two requests: the second is recognised as a repeat and stops the loop.
    assert calls["n"] == 2
    assert len(points) == 500


@pytest.mark.asyncio
async def test_get_points_single_short_page_makes_one_request():
    """The common case must not cost an extra round trip."""
    calls = {"n": 0}

    async def fake_get(self, url, headers=None, params=None):  # noqa: ANN001
        calls["n"] += 1
        return httpx.Response(
            status_code=200,
            json={"points": [{"id": 1, "latitude": 52.0, "longitude": 13.0}]},
            request=httpx.Request("GET", url),
        )

    with patch("httpx.AsyncClient.get", new=fake_get):
        client = DawarichClient(api_key="k")
        points = await client.get_points()

    assert calls["n"] == 1
    assert len(points) == 1


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
