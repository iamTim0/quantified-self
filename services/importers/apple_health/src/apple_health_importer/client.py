"""Core Service Integration Client for Apple Health Importer.

Fetches dynamic connector credentials/token and source_id from Core Data Service DB
per Rule 8 (Stateless Importers & Connector Credentials).
"""

import logging
import uuid
from typing import Any

import httpx

from apple_health_importer.auth import internal_headers
from apple_health_importer.config import settings

logger = logging.getLogger(__name__)


async def get_connector_credentials_from_core(
    tenant_id: str, req_id: str = "req_apple_health_auth"
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Fetch decrypted token & source_id for Apple Health connector from Core Data Service DB."""
    url = f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/{settings.SOURCE_TYPE}/token"
    headers = internal_headers(req_id, tenant_id)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            res = await client.get(url, headers=headers)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "active":
                    token = data.get("access_token")
                    source_id = data.get("source_id") or str(
                        uuid.uuid5(uuid.NAMESPACE_DNS, f"{tenant_id}:{settings.SOURCE_TYPE}")
                    )
                    return token, source_id, data.get("config", {})
            return None, None, None
        except Exception as e:
            logger.warning(f"Could not reach Core Data Service to fetch connector token: {e}")
            return None, None, None
