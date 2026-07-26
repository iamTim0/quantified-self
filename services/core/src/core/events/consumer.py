import json
import logging
from datetime import datetime

import nats
from sqlalchemy.dialects.postgresql import insert

from core.config import settings
from core.db.models import DataPoint
from core.db.session import async_session_maker

logger = logging.getLogger(__name__)

async def process_message(msg):
    try:
        data = json.loads(msg.data.decode())

        # INVARIANT: TenantIsolation — reject events without tenant_id
        tenant_id = data.get("tenant_id")
        if not tenant_id:
            logger.error("Rejected event: missing tenant_id. Acking to prevent redelivery.")
            await msg.ack()
            return

        ts_raw = data.get("timestamp")
        if isinstance(ts_raw, str):
            ts_val = datetime.fromisoformat(ts_raw)
        else:
            ts_val = ts_raw

        async with async_session_maker() as session:
            stmt = insert(DataPoint).values(
                id=data.get("id"),
                tenant_id=tenant_id,
                source_id=data.get("source_id"),
                metric_type=data.get("metric_type"),
                timestamp=ts_val,
                value=data.get("value"),
                metadata_=data.get("metadata"),
                idempotency_key=data.get("idempotency_key"),
            )
            # INVARIANT: NoDuplicateData — composite unique constraint matches
            # the TimescaleDB hypertable requirement: (tenant_id, idempotency_key, timestamp)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["tenant_id", "idempotency_key", "timestamp"]
            )
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount == 0:
                logger.info(
                    f"Duplicate event skipped: tenant={tenant_id} "
                    f"key={data.get('idempotency_key')}"
                )

        await msg.ack()
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        # Not acking — message will be redelivered by JetStream (at-least-once)

async def start_consumer():
    nc = await nats.connect(settings.NATS_URL)
    js = nc.jetstream()
    
    # Ensure stream exists
    try:
        await js.add_stream(name="ingestion", subjects=["qs.ingest.>"])
    except Exception as e:
        logger.info(f"Stream may already exist: {e}")
    
    await js.subscribe("qs.ingest.>", "core_data_service_group", cb=process_message)
    logger.info("Started consuming from qs.ingest.>")
    return nc
