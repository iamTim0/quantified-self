"""Async client for the home_assistant provider API."""
from typing import Any
import httpx
class ProviderClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url, self.token = base_url.rstrip("/"), token
    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{self.base_url}/api/states", headers={"Authorization": f"Bearer {self.token}"})
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else payload.get("data", payload.get("events", []))
