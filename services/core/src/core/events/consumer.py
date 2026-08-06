"""NATS JetStream consumer that persists ingest events into PostgreSQL.

Core is the only service that writes to the database (AGENTS.md rule 1), so this
is where every importer's data lands.

Two things the previous version did not do:

* It ignored the ``request_id`` on the event, so every ingest log line carried the
  process-wide default and a sync could not be traced end to end (rule 13).
* It logged duplicates but counted nothing, so there was no way to tell whether a
  sync had actually contributed anything. Counts now accumulate on the ``SyncRun``
  that triggered the sync, which is also what the adaptive-window logic reads.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import nats
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from core.config import settings
from core.db.models import DataPoint, DataSource, SyncRun
from core.db.session import async_session_maker
from core.tracing import set_current_request_id

logger = logging.getLogger(__name__)


async def process_message(msg):
    try:
        data = json.loads(msg.data.decode())

        # Bind the correlation id before anything is logged, so a whole ingest is
        # traceable back to the sync that requested it.
        request_id = data.get("request_id")
        if request_id:
            set_current_request_id(request_id)

        # INVARIANT: TenantIsolation — reject events without tenant_id
        tenant_id = data.get("tenant_id")
        if not tenant_id:
            logger.error("Rejected event: missing tenant_id. Acking to prevent redelivery.")
            await msg.ack()
            return

        idempotency_key = data.get("idempotency_key")
        if not idempotency_key:
            logger.error("Rejected event: missing idempotency_key. Acking to prevent redelivery.")
            await msg.ack()
            return

        ts_raw = data.get("timestamp")
        if isinstance(ts_raw, str):
            ts_val = datetime.fromisoformat(ts_raw)
        else:
            ts_val = ts_raw

        sync_run_id = data.get("sync_run_id")

        async with async_session_maker() as session:
            stmt = insert(DataPoint).values(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source_id=data.get("source_id"),
                metric_type=data.get("metric_type"),
                timestamp=ts_val,
                value=data.get("value"),
                metadata_=data.get("metadata"),
                idempotency_key=idempotency_key,
            )
            # INVARIANT: NoDuplicateData — duplicate events must not mutate
            # previously stored data for the same tenant-scoped idempotency key.
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["tenant_id", "idempotency_key", "timestamp"],
            )
            result = await session.execute(stmt)
            inserted = (result.rowcount or 0) > 0

            if not inserted:
                logger.info(
                    f"Duplicate event skipped: tenant={tenant_id} key={idempotency_key}"
                )

            if sync_run_id:
                await _tally(session, tenant_id, sync_run_id, inserted=inserted)

            # Update DataSource sync_status to idle
            source_id = data.get("source_id")
            source_type = data.get("source_type") or (data.get("metadata") or {}).get(
                "source_type"
            )
            if source_id or source_type:
                if source_id:
                    s_stmt = select(DataSource).where(
                        DataSource.tenant_id == tenant_id,
                        DataSource.id == source_id,
                    )
                else:
                    s_stmt = select(DataSource).where(
                        DataSource.tenant_id == tenant_id,
                        DataSource.source_type == source_type,
                    )
                res = await session.execute(s_stmt)
                ds = res.scalar_one_or_none()
                if ds:
                    cfg = dict(ds.config or {})
                    cfg["sync_status"] = "idle"
                    cfg["last_sync_at"] = datetime.now(timezone.utc).isoformat()
                    cfg["last_sync_message"] = "Erfolgreich Datenpunkte importiert."
                    ds.config = cfg

            await session.commit()

        await msg.ack()
    except Exception:
        logger.exception("Error processing message")
        # Not acking — message will be redelivered by JetStream (at-least-once)


async def _tally(session, tenant_id: str, sync_run_id: str, *, inserted: bool) -> None:
    """Accumulate accepted/duplicate counts on the run that requested this data.

    Tenant-scoped on purpose: a forged ``sync_run_id`` from another tenant must not
    let an event touch that tenant's audit record.
    """
    column = SyncRun.points_accepted if inserted else SyncRun.points_duplicate
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == sync_run_id, SyncRun.tenant_id == tenant_id)
        .values({column: column + 1})
    )


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
