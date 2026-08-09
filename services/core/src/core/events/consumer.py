"""NATS JetStream consumer that persists ingest events into PostgreSQL.

Core is the only service that writes to the database (AGENTS.md rule 1), so this
is where every importer's data lands.

Two things the previous version did not do:

* It ignored the ``request_id`` on the event, so every ingest log line carried the
  process-wide default and a sync could not be traced end to end (rule 13).
* It logged duplicates but counted nothing, so there was no way to tell whether a
  sync had actually contributed anything. Counts now accumulate on the ``SyncRun``
  that triggered the sync, which is also what the adaptive-window logic reads.

It is also where ``metric_type`` is checked against the shared registry. This is the
one path every importer's data passes through, and it previously wrote
``data.get("metric_type")`` unexamined -- so a typo, a provider's renamed field or a
new HealthKit type became a metric of its own, and the ``max_length=128`` check on the
HTTP path did not apply here at all.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import nats
from shared_schemas.metrics import UnknownMetricTypeError, canonical_metric_type
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

        # INVARIANT: CanonicalMetricNames — only names the registry defines, or names
        # under a registered dynamic namespace, reach the database. Acked rather than
        # redelivered: an unregistered name is a code or configuration problem that
        # redelivery cannot fix, and the event would otherwise loop forever.
        raw_metric_type = data.get("metric_type")
        try:
            metric_type = canonical_metric_type(str(raw_metric_type or ""))
        except UnknownMetricTypeError as exc:
            logger.error(
                "Rejected event for tenant=%s: %s. Acking to prevent redelivery.",
                tenant_id,
                exc,
            )
            await msg.ack()
            return

        if metric_type != raw_metric_type:
            # The importer hashed the alias, so its key does not describe the name we
            # would store. Rewriting one without the other is how a series ends up with
            # two rows per reading.
            logger.error(
                "Rejected event for tenant=%s: metric_type %r is a legacy alias of %r; "
                "the importer must canonicalise before deriving the idempotency key. "
                "Acking to prevent redelivery.",
                tenant_id,
                raw_metric_type,
                metric_type,
            )
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
                metric_type=metric_type,
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
                # The run is the record of this import, and the importer closes it
                # out when it is actually finished. The connector row is left alone
                # here on purpose: it used to be stamped "idle" by the *first*
                # message of a batch, so a fifty-thousand-point Apple Health import
                # reported "done" while the other 49,999 were still queued — and
                # every message rewrote the same row, which serialised the whole
                # import behind one row lock for nothing.
                await _tally(session, tenant_id, sync_run_id, inserted=inserted)
            else:
                await _mark_source_seen(session, tenant_id, data)

            await session.commit()

        await msg.ack()
    except Exception:
        logger.exception("Error processing message")
        # Not acking — message will be redelivered by JetStream (at-least-once)


async def _mark_source_seen(session, tenant_id: str, data: dict) -> None:
    """Record that a connector produced data, for events with no run attached.

    Only reachable for an importer that publishes without a `sync_run_id`. With a
    run, the run *is* the status and this write would contradict it mid-import.
    """
    source_id = data.get("source_id")
    source_type = data.get("source_type") or (data.get("metadata") or {}).get("source_type")
    if not source_id and not source_type:
        return

    if source_id:
        stmt = select(DataSource).where(
            DataSource.tenant_id == tenant_id, DataSource.id == source_id
        )
    else:
        # Ordered and limited rather than `scalar_one_or_none()`, which raised
        # MultipleResultsFound as soon as a tenant held two connectors of one type
        # — and since the handler does not ack on exception, that message would
        # have been redelivered by JetStream forever.
        stmt = (
            select(DataSource)
            .where(
                DataSource.tenant_id == tenant_id,
                DataSource.source_type == source_type,
            )
            .order_by(DataSource.created_at, DataSource.id)
            .limit(1)
        )

    ds = (await session.execute(stmt)).scalars().first()
    if ds:
        cfg = dict(ds.config or {})
        cfg["sync_status"] = "idle"
        cfg["last_sync_at"] = datetime.now(timezone.utc).isoformat()
        cfg["last_sync_message"] = "Data points imported."
        ds.config = cfg


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


# One connection attempt fails fast rather than burning the library's default
# retry budget inside it. Retrying is this module's job (see run_consumer_forever),
# so that a broker outage cannot hold up anything that calls in here.
CONNECT_TIMEOUT_SECONDS = 5
RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0


async def start_consumer():
    """Connect to NATS and subscribe. Raises promptly if the broker is unreachable."""
    nc = await nats.connect(
        settings.NATS_URL,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        # No retries *here*. nats-py's default is 60 attempts two seconds apart,
        # so an unreachable broker blocked this call for two minutes -- and with
        # it Core's startup, because the lifespan awaited it before serving. The
        # HTTP API has no business being unavailable because the broker is down.
        max_reconnect_attempts=0,
        allow_reconnect=False,
    )
    js = nc.jetstream()

    # Ensure stream exists
    try:
        await js.add_stream(name="ingestion", subjects=["qs.ingest.>"])
    except Exception as e:
        logger.info(f"Stream may already exist: {e}")

    await js.subscribe("qs.ingest.>", "core_data_service_group", cb=process_message)
    logger.info("Started consuming from qs.ingest.>")
    return nc


async def run_consumer_forever(on_connected=None) -> None:
    """Keep trying to establish the subscription, backing off between attempts.

    Meant to run as a background task so that Core serves HTTP and gRPC whether
    or not the broker is up. Ingestion is degraded while NATS is unreachable;
    queries, authentication and the dashboard are not, and conflating the two
    turns a broker outage into a full outage.

    Backs off exponentially to 30s. A tight retry loop against a broker that is
    restarting is its own kind of denial of service.
    """
    delay = RECONNECT_INITIAL_DELAY
    while True:
        try:
            nc = await start_consumer()
        except Exception as exc:  # noqa: BLE001 - any failure means "not connected yet"
            logger.warning(
                "NATS unavailable (%s); ingestion is paused, retrying in %.0fs",
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
            continue

        logger.info("NATS consumer established")
        if on_connected is not None:
            on_connected(nc)
        return
