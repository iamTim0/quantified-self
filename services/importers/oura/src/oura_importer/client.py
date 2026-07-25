import httpx
import logging
from oura_importer.config import settings

logger = logging.getLogger(__name__)

class OuraClient:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.OURA_ACCESS_TOKEN}"
        }
        self.base_url = settings.OURA_API_BASE_URL

    async def _get(self, endpoint: str):
        # Placeholder for proper error handling and rate limiting
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/{endpoint}", headers=self.headers)
            response.raise_for_status()
            return response.json()

    async def get_sleep(self):
        return await self._get("sleep")

    async def get_activity(self):
        return await self._get("daily_activity")

    async def get_readiness(self):
        return await self._get("daily_readiness")
