"""Request-driven calendar importer publishing exclusively through JetStream."""
import asyncio, json
from typing import Any
import httpx, nats
from calendar_importer.client import ProviderClient
from calendar_importer.config import settings
from calendar_importer.transformer import transform
async def credentials(tenant_id: str, request_id: str) -> dict[str, Any] | None:
    headers={"X-Tenant-ID":tenant_id,"X-Request-ID":request_id}
    async with httpx.AsyncClient(timeout=10) as client:
        response=await client.get(f"{settings.CORE_SERVICE_URL}/api/v1/internal/data/sources/calendar/token",headers=headers)
        return response.json() if response.status_code == 200 else None
async def process(message: Any, connection: Any) -> None:
    task=json.loads(message.data); tenant_id=task.get("tenant_id"); request_id=task.get("request_id")
    if not tenant_id or not request_id: await message.ack(); return
    secret=await credentials(tenant_id,request_id)
    if secret and secret.get("access_token"):
        config=secret.get("config") or {}; base_url=config.get("base_url") or settings.API_BASE_URL
        if base_url:
            records=await ProviderClient(base_url,secret["access_token"]).fetch()
            for event in transform(records,tenant_id,secret["source_id"]):
                event["request_id"]=request_id
                await connection.jetstream().publish("qs.ingest.calendar",json.dumps(event).encode())
    await message.ack()
async def main() -> None:
    connection=await nats.connect(settings.NATS_URL); stream=connection.jetstream()
    try: await stream.add_stream(name="tasks",subjects=["qs.task.sync.>"])
    except Exception: pass
    await stream.subscribe("qs.task.sync.calendar",queue="calendar_importer_task_group",cb=lambda msg: process(msg,connection))
    await asyncio.Event().wait()
if __name__ == "__main__": asyncio.run(main())
