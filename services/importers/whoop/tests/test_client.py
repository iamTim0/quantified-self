import httpx
import pytest

from whoop_importer.client import WhoopClient


@pytest.mark.asyncio
async def test_collection_uses_whoop_next_token():
    """Verifies all WHOOP collection pages are consumed exactly once."""
    requests = []
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "nextToken=next" in str(request.url):
            return httpx.Response(200, json={"records": [{"id": "two"}]})
        return httpx.Response(200, json={"records": [{"id": "one"}], "next_token": "next"})
    async with WhoopClient("secret", "https://example.test", httpx.MockTransport(handler)) as client:
        records = [record async for record in client.sleeps()]
    assert [record["id"] for record in records] == ["one", "two"]
    assert requests[0].headers["authorization"] == "Bearer secret"
