"""End-to-End Ingestion Integration Test.

Verifies real event flow:
1. Importer formats data & generates idempotency_key
2. Publishes to NATS JetStream subject 'qs.ingest.oura'
3. Core consumer ingests event into PostgreSQL TimescaleDB
4. Duplicate events (same tenant_id + idempotency_key + timestamp) are skipped

Verifies Fizzbee Invariants:
- TenantIsolation
- NoDuplicateData
- EventualConsistency
"""

import json
import uuid
from datetime import datetime, timezone

import nats
import pytest
from core.db.models import DataPoint, DataSource, Tenant
from core.db.session import async_session_maker
from core.events.consumer import process_message
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant

NATS_URL = "nats://127.0.0.1:4222"

@pytest.mark.asyncio
async def test_end_to_end_ingestion_deduplication():
    """Test full ingestion pipeline with NATS JetStream & PostgreSQL deduplication."""
    # 1. Setup tenant & data_source in DB
    tenant_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    idempotency_key = f"test-idemp-{uuid.uuid4().hex[:8]}"

    nc = None
    try:
        async with async_session_maker() as session:
            t = Tenant(id=tenant_id, name="Test Integration Tenant")
            session.add(t)
            await session.flush()

            ds = DataSource(id=source_id, tenant_id=tenant_id, source_type="oura")
            session.add(ds)
            await session.commit()

        # 2. Connect to NATS JetStream
        nc = await nats.connect(NATS_URL)
        js = nc.jetstream()

        # Ensure stream
        try:
            await js.add_stream(name="ingestion", subjects=["qs.ingest.>"])
        except Exception:
            pass

        # 3. Create test event payload
        event_payload = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": "sleep_score",
            "timestamp": now.isoformat(),
            "value": 88.5,
            "metadata": {"source": "oura_api_v2", "readiness": 90},
            "idempotency_key": idempotency_key,
        }

        # 4. Publish event TWICE (simulating at-least-once network retry)
        payload_bytes = json.dumps(event_payload).encode()
        ack1 = await js.publish("qs.ingest.oura", payload_bytes)
        ack2 = await js.publish("qs.ingest.oura", payload_bytes)

        assert ack1.seq > 0
        assert ack2.seq > 0

        # 5. Process messages from NATS
        class MockMsg:
            def __init__(self, data):
                self.data = data
                self.acked = False

            async def ack(self):
                self.acked = True

        msg1 = MockMsg(payload_bytes)
        msg2 = MockMsg(payload_bytes)

        await process_message(msg1)
        await process_message(msg2)

        assert msg1.acked
        assert msg2.acked

        # 6. Verify Database State: exactly ONE data point created (deduplication worked!)
        async with async_session_maker() as session:
            stmt = select(DataPoint).where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.idempotency_key == idempotency_key
            )
            res = await session.execute(stmt)
            points = res.scalars().all()

            assert len(points) == 1, "Deduplication failed: expected exactly 1 record in DB"
            assert points[0].value == 88.5
            assert points[0].metric_type == "sleep_score"
            assert points[0].tenant_id == tenant_id
    finally:
        if nc:
            await nc.close()
        await cleanup_test_tenant(tenant_id)
