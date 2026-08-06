"""Request-driven Home Assistant importer publishing exclusively through JetStream."""
import asyncio
import json
import logging
from typing import Any

import httpx
import nats

from home_assistant_importer.client import ProviderClient
from home_assistant_importer.config import settings
from home_assistant_importer.internal_auth import internal_headers
from home_assistant_importer.transformer import transform

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-importer-home_assistant] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def credentials(tenant_id: str, request_id: str) -> dict[str, Any] | None:
    headers = internal_headers(request_id, tenant_id)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(
                f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/home_assistant/token",
                headers=headers,
            )
            return response.json() if response.status_code == 200 else None
        except Exception as e:
            logger.warning(f"[req_id={request_id}] Failed to fetch credentials for tenant {tenant_id}: {e}")
            return None


async def process(message: Any, connection: Any) -> None:
    try:
        task = json.loads(message.data)
        tenant_id = task.get("tenant_id")
        request_id = task.get("request_id", "req_unknown")
        if not tenant_id or not request_id:
            await message.ack()
            return

        logger.info(f"[req_id={request_id}] Processing home_assistant sync task for tenant {tenant_id}")
        secret = await credentials(tenant_id, request_id)
        if secret and secret.get("access_token") and secret.get("status") == "active":
            config = secret.get("config") or {}
            base_url = config.get("base_url") or settings.API_BASE_URL
            if base_url:
                records = await ProviderClient(base_url, secret["access_token"]).fetch()
                published = 0
                for event in transform(records, tenant_id, secret["source_id"]):
                    event["request_id"] = request_id
                    await connection.jetstream().publish("qs.ingest.home_assistant", json.dumps(event).encode())
                    published += 1
                logger.info(f"[req_id={request_id}] Published {published} home_assistant events to JetStream")
    except Exception as e:
        logger.error(f"Error processing home_assistant task: {e}")
    finally:
        await message.ack()


async def main() -> None:
    logger.info("Starting Home Assistant Importer Service...")
    connection = await nats.connect(settings.NATS_URL)
    stream = connection.jetstream()
    try:
        await stream.add_stream(name="tasks", subjects=["qs.task.sync.>"])
    except Exception:
        pass
    await stream.subscribe(
        "qs.task.sync.home_assistant",
        queue="home_assistant_importer_task_group",
        cb=lambda msg: process(msg, connection),
    )
    logger.info("Subscribed to NATS subject 'qs.task.sync.home_assistant'")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
