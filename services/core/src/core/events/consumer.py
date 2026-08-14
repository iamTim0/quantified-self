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
import hashlib
import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import nats
from nats.js.api import ConsumerConfig, DiscardPolicy, StreamConfig
from shared_schemas import idempotency_key as derive_idempotency_key
from shared_schemas.metrics import UnknownMetricTypeError, canonical_metric_type
from sqlalchemy import and_, case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db.models import (
    DataPoint,
    DataSource,
    MetricMappingRule,
    QuarantinedDataPoint,
    QuarantineRefusal,
    SyncRun,
    SyncRunEvent,
)
from core.db.session import async_session_maker
from core.metric_mapping import ValidatedMapping, replay_value, validate_mapping
from core.tracing import set_current_request_id

logger = logging.getLogger(__name__)

MAX_QUARANTINED_NAMES = 100
MAX_QUARANTINED_ROWS = 100_000
MAX_QUARANTINE_REFUSALS = 10_000
DEFAULT_QUARANTINE_RETENTION_DAYS = 30
MAX_INGEST_EVENT_BYTES = 256 * 1024
MAX_POINT_METADATA_BYTES = 32 * 1024


def _processing_event_key(msg) -> str:
    """Return a stable, bounded identity for one broker delivery.

    JetStream stream sequence numbers are stable across redelivery. Plain NATS
    fallback subscriptions do not expose them, so a payload fingerprint is the
    safe fallback. The key is only a progress-ledger identity; provider values
    never enter the ledger.
    """
    try:
        metadata = msg.metadata
        stream = str(metadata.stream)
        sequence = str(metadata.sequence.stream)
        return "js:" + hashlib.sha256(f"{stream}:{sequence}".encode()).hexdigest()
    except Exception:  # noqa: BLE001 - non-JetStream messages have no metadata
        return "payload:" + hashlib.sha256(msg.data).hexdigest()


def bounded_point_metadata(
    metadata: dict[str, Any], provider_value: float | None
) -> dict[str, Any]:
    """Keep point provenance while refusing to archive a whole provider payload."""
    try:
        encoded = json.dumps(
            metadata, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError):
        encoded = None
    if encoded is not None and len(encoded.encode("utf-8")) <= MAX_POINT_METADATA_BYTES:
        return metadata

    stated_value = metadata.get("provider_value", provider_value)
    if (
        isinstance(stated_value, bool)
        or not isinstance(stated_value, (int, float))
        or not math.isfinite(float(stated_value))
    ):
        stated_value = provider_value
    stated_units = metadata.get("units")
    if not isinstance(stated_units, str) or len(stated_units) > 64:
        stated_units = None
    return {
        "provider_value": stated_value,
        "units": stated_units,
        "metadata_truncated": True,
    }


def event_idempotency_key_matches(
    tenant_id: str,
    source_id: str,
    raw_metric_type: str,
    canonical_metric: str | None,
    timestamp: str,
    supplied_key: str,
    idempotency_source_id: str | None = None,
) -> bool:
    """Check the key before an event can enter either the quarantine or data store."""
    metric_for_key = canonical_metric if canonical_metric is not None else raw_metric_type
    return supplied_key == derive_idempotency_key(
        tenant_id, idempotency_source_id or source_id, metric_for_key, timestamp
    )


async def _record_quarantine_refusal(
    session: AsyncSession,
    *,
    tenant_id: str,
    source: DataSource,
    raw_metric_type: str,
    reason: str,
) -> None:
    """Record a bounded-queue refusal without retaining the refused value."""
    now = datetime.now(timezone.utc)
    existing = await session.execute(
        select(QuarantineRefusal.id).where(
            QuarantineRefusal.tenant_id == tenant_id,
            QuarantineRefusal.source_id == source.id,
            QuarantineRefusal.raw_metric_type == raw_metric_type[:128],
            QuarantineRefusal.reason == reason[:128],
        )
    )
    refusal_metric = raw_metric_type[:128]
    if existing.scalar_one_or_none() is None:
        refusal_count = await session.execute(
            select(func.count(QuarantineRefusal.id)).where(
                QuarantineRefusal.tenant_id == tenant_id,
                QuarantineRefusal.source_id == source.id,
            )
        )
        if (refusal_count.scalar_one() or 0) >= MAX_QUARANTINE_REFUSALS:
            refusal_metric = "__overflow__"
    statement = insert(QuarantineRefusal).values(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        source_id=source.id,
        source_type=source.source_type,
        raw_metric_type=refusal_metric,
        reason=reason[:128],
        occurrences=1,
        first_seen_at=now,
        last_seen_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_quarantine_refusal_tenant_source_raw_reason",
        set_={
            "occurrences": QuarantineRefusal.occurrences + 1,
            "last_seen_at": now,
        },
    )
    await session.execute(statement)


async def _quarantine_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    source: DataSource,
    raw_metric_type: str,
    timestamp: datetime,
    value: float | None,
    metadata: dict[str, Any],
    original_idempotency_key: str,
    idempotency_source_id: str,
    sync_run_id: str | None,
    retention_days: int | None,
) -> str:
    """Hold one unknown point, or return the bounded-queue refusal reason."""
    now = datetime.now(timezone.utc)
    # Serialize the cap check per connector. Without this narrow lock, two unknown
    # events arriving together could both observe the last free slot and exceed a
    # limit that is meant to protect the tenant from provider-generated key storms.
    await session.execute(
        select(DataSource.id)
        .where(DataSource.tenant_id == tenant_id, DataSource.id == source.id)
        .with_for_update()
    )
    if retention_days is not None:
        cutoff = now - timedelta(days=retention_days)
        await session.execute(
            update(QuarantinedDataPoint)
            .where(
                QuarantinedDataPoint.tenant_id == tenant_id,
                QuarantinedDataPoint.source_id == source.id,
                QuarantinedDataPoint.status == "active",
                QuarantinedDataPoint.last_seen_at < cutoff,
            )
            .values(status="expired", resolved_at=now)
        )
        await session.execute(
            delete(QuarantinedDataPoint).where(
                QuarantinedDataPoint.tenant_id == tenant_id,
                QuarantinedDataPoint.source_id == source.id,
                QuarantinedDataPoint.status.in_(("expired", "promoted", "discarded")),
                QuarantinedDataPoint.resolved_at.is_not(None),
                QuarantinedDataPoint.resolved_at < cutoff,
            )
        )
    existing = await session.execute(
        select(QuarantinedDataPoint).where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.source_id == source.id,
            QuarantinedDataPoint.idempotency_key == original_idempotency_key,
            QuarantinedDataPoint.timestamp == timestamp,
        )
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        await session.execute(
            update(QuarantinedDataPoint)
            .where(
                QuarantinedDataPoint.tenant_id == tenant_id,
                QuarantinedDataPoint.source_id == source.id,
                QuarantinedDataPoint.idempotency_key == original_idempotency_key,
                QuarantinedDataPoint.timestamp == timestamp,
            )
            .values(
                seen_count=QuarantinedDataPoint.seen_count + 1,
                last_seen_at=now,
                status="active",
                value=value,
                metadata_=metadata,
                idempotency_source_id=idempotency_source_id,
                sync_run_id=sync_run_id,
                resolved_at=None,
                resolution_rule_id=None,
            )
        )
        return "quarantined"

    active_rows = await session.execute(
        select(func.count(QuarantinedDataPoint.id)).where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.source_id == source.id,
            QuarantinedDataPoint.status == "active",
        )
    )
    if (active_rows.scalar_one() or 0) >= MAX_QUARANTINED_ROWS:
        reason = "row_cap_reached"
        await _record_quarantine_refusal(
            session,
            tenant_id=tenant_id,
            source=source,
            raw_metric_type=raw_metric_type,
            reason=reason,
        )
        return reason

    active_names = await session.execute(
        select(func.count(func.distinct(QuarantinedDataPoint.raw_metric_type))).where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.source_id == source.id,
            QuarantinedDataPoint.status == "active",
        )
    )
    known_name = await session.execute(
        select(QuarantinedDataPoint.id).where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.source_id == source.id,
            QuarantinedDataPoint.raw_metric_type == raw_metric_type,
            QuarantinedDataPoint.status == "active",
        ).limit(1)
    )
    if (active_names.scalar_one() or 0) >= MAX_QUARANTINED_NAMES and known_name.scalar_one_or_none() is None:
        reason = "distinct_name_cap_reached"
        await _record_quarantine_refusal(
            session,
            tenant_id=tenant_id,
            source=source,
            raw_metric_type=raw_metric_type,
            reason=reason,
        )
        return reason

    await session.execute(
        insert(QuarantinedDataPoint).values(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source.id,
            source_type=source.source_type,
            raw_metric_type=raw_metric_type,
            timestamp=timestamp,
            value=value,
            metadata_=metadata,
            idempotency_source_id=idempotency_source_id,
            idempotency_key=original_idempotency_key,
            sync_run_id=sync_run_id,
            status="active",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    return "quarantined"


def _mapping_from_row(rule: MetricMappingRule) -> ValidatedMapping:
    """Turn a persisted, previously validated rule into a replay mapping."""
    return validate_mapping(
        raw_metric_type=rule.raw_metric_type,
        action=rule.action,
        target_metric_type=rule.target_metric_type,
        source_unit=rule.source_unit,
        target_unit=rule.target_unit,
        aggregation=rule.aggregation,
        cadence=rule.cadence,
    )


async def process_message(msg):
    # Bound before the try so the failure handlers can name the tenant whose event it
    # was; a rejection that does not say whose data it dropped is hard to act on.
    tenant_id: str | None = None
    source_id: str | None = None
    event_key = _processing_event_key(msg)
    try:
        if len(msg.data) > MAX_INGEST_EVENT_BYTES:
            logger.error("Rejected oversized ingest event. Acking to prevent redelivery.")
            await msg.ack()
            return
        try:
            data = json.loads(msg.data.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.error("Rejected malformed ingest event. Acking to prevent redelivery.")
            await msg.ack()
            return
        if not isinstance(data, dict):
            logger.error("Rejected non-object ingest event. Acking to prevent redelivery.")
            await msg.ack()
            return

        # Bind the correlation id before anything is logged, so a whole ingest is
        # traceable back to the sync that requested it.
        request_id = data.get("request_id")
        if request_id is not None and (
            not isinstance(request_id, str) or not request_id or len(request_id) > 128
        ):
            logger.error("Rejected ingest event with an invalid request_id.")
            await msg.ack()
            return
        if request_id:
            set_current_request_id(request_id)

        # INVARIANT: TenantIsolation — reject events without tenant_id
        tenant_id = data.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 128:
            logger.error("Rejected event: missing tenant_id. Acking to prevent redelivery.")
            await msg.ack()
            return

        idempotency_key = data.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            logger.error("Rejected event: missing idempotency_key. Acking to prevent redelivery.")
            await msg.ack()
            return

        raw_metric_type = data.get("metric_type")
        if not isinstance(raw_metric_type, str):
            logger.error("Rejected event for tenant=%s: metric_type is not a string.", tenant_id)
            await msg.ack()
            return
        raw_metric_type = raw_metric_type.strip()
        source_id = data.get("source_id")
        idempotency_source_id = data.get("idempotency_source_id")
        if idempotency_source_id is None:
            idempotency_source_id = source_id
        event_source_type = data.get("source_type")
        sync_run_id = data.get("sync_run_id")
        if not isinstance(source_id, str) or not source_id or len(source_id) > 128:
            logger.error("Rejected event for tenant=%s: source_id is invalid.", tenant_id)
            await msg.ack()
            return
        try:
            uuid.UUID(tenant_id)
            uuid.UUID(source_id)
        except ValueError:
            logger.error(
                "Rejected event: tenant_id or source_id is not a UUID. "
                "Acking to prevent redelivery."
            )
            await msg.ack()
            return
        if (
            not isinstance(idempotency_source_id, str)
            or not idempotency_source_id
            or len(idempotency_source_id) > 512
        ):
            logger.error(
                "Rejected event for tenant=%s: idempotency_source_id is invalid.", tenant_id
            )
            await msg.ack()
            return
        if sync_run_id is not None:
            try:
                uuid.UUID(str(sync_run_id))
            except (ValueError, AttributeError):
                logger.error("Rejected event for tenant=%s: sync_run_id is invalid.", tenant_id)
                await msg.ack()
                return
            sync_run_id = str(sync_run_id)
        if (
            not raw_metric_type
            or len(raw_metric_type) > 128
            or len(idempotency_key) > 128
            or (event_source_type is not None and not isinstance(event_source_type, str))
        ):
            logger.error(
                "Rejected event for tenant=%s: source_id or metric_type is invalid. "
                "Acking to prevent redelivery.",
                tenant_id,
            )
            await msg.ack()
            return

        ts_raw = data.get("timestamp")
        if not isinstance(ts_raw, str):
            logger.error("Rejected event for tenant=%s: timestamp is invalid.", tenant_id)
            await msg.ack()
            return
        try:
            ts_val = datetime.fromisoformat(ts_raw)
        except ValueError:
            logger.error("Rejected event for tenant=%s: timestamp is invalid.", tenant_id)
            await msg.ack()
            return
        if not isinstance(ts_val, datetime):
            logger.error("Rejected event for tenant=%s: timestamp is invalid.", tenant_id)
            await msg.ack()
            return
        if ts_val.tzinfo is None:
            ts_val = ts_val.replace(tzinfo=timezone.utc)

        metadata = data.get("metadata")
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            logger.error("Rejected event for tenant=%s: metadata is not an object.", tenant_id)
            await msg.ack()
            return
        raw_value = data.get("value")
        if raw_value is not None and (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(float(raw_value))
        ):
            logger.error("Rejected event for tenant=%s: value is not numeric.", tenant_id)
            await msg.ack()
            return
        numeric_value = float(raw_value) if raw_value is not None else None

        try:
            metric_type = canonical_metric_type(raw_metric_type)
        except UnknownMetricTypeError as exc:
            metric_type = None
            unknown_error = exc
        else:
            unknown_error = None

        if not event_idempotency_key_matches(
            tenant_id,
            source_id,
            raw_metric_type,
            metric_type,
            ts_raw,
            idempotency_key,
            idempotency_source_id,
        ):
            logger.error(
                "Rejected event for tenant=%s source=%s: idempotency_key does not match "
                "the tenant, connector, metric and timestamp.",
                tenant_id,
                source_id,
            )
            await msg.ack()
            return

        metadata = bounded_point_metadata(metadata, numeric_value)

        async with async_session_maker() as session:
            source_result = await session.execute(
                select(DataSource).where(
                    DataSource.tenant_id == tenant_id,
                    DataSource.id == source_id,
                )
            )
            source = source_result.scalars().first()
            if source is None:
                logger.error(
                    "Rejected event for tenant=%s source=%s: connector is unknown.",
                    tenant_id,
                    source_id,
                )
                await msg.ack()
                return
            if event_source_type is not None and event_source_type != source.source_type:
                logger.error(
                    "Rejected event for tenant=%s source=%s: source_type does not match "
                    "the configured connector.",
                    tenant_id,
                    source.id,
                )
                await msg.ack()
                return
            if idempotency_source_id != source.id and not idempotency_source_id.startswith(
                f"{source.id}_"
            ):
                logger.error(
                    "Rejected event for tenant=%s source=%s: idempotency_source_id "
                    "is not scoped to the configured connector.",
                    tenant_id,
                    source.id,
                )
                await msg.ack()
                return

            if unknown_error is not None:
                rule_result = await session.execute(
                    select(MetricMappingRule).where(
                        MetricMappingRule.tenant_id == tenant_id,
                        MetricMappingRule.source_id == source.id,
                        MetricMappingRule.raw_metric_type == raw_metric_type,
                    )
                )
                rule = rule_result.scalars().first()
                if rule is None or rule.action == "keep":
                    metadata.setdefault("provider_value", raw_value)
                    refusal = await _quarantine_event(
                        session,
                        tenant_id=tenant_id,
                        source=source,
                        raw_metric_type=raw_metric_type,
                        timestamp=ts_val,
                        value=numeric_value,
                        metadata=metadata,
                        original_idempotency_key=idempotency_key,
                        idempotency_source_id=idempotency_source_id,
                        sync_run_id=sync_run_id,
                        retention_days=(
                            rule.retention_days
                            if rule is not None and rule.action == "keep"
                            else DEFAULT_QUARANTINE_RETENTION_DAYS
                        ),
                    )
                    if refusal != "quarantined":
                        logger.error(
                            "Quarantine refused for tenant=%s source=%s metric=%s reason=%s.",
                            tenant_id,
                            source.id,
                            raw_metric_type,
                            refusal,
                        )
                    if sync_run_id:
                        await _tally(
                            session,
                            tenant_id,
                            sync_run_id,
                            source_id=source.id,
                            event_key=event_key,
                            inserted=None,
                        )
                    await session.commit()
                    await msg.ack()
                    return
                if rule.action == "discard":
                    await _record_quarantine_refusal(
                        session,
                        tenant_id=tenant_id,
                        source=source,
                        raw_metric_type=raw_metric_type,
                        reason="discarded_by_rule",
                    )
                    if sync_run_id:
                        await _tally(
                            session,
                            tenant_id,
                            sync_run_id,
                            source_id=source.id,
                            event_key=event_key,
                            inserted=None,
                        )
                    await session.commit()
                    await msg.ack()
                    return
                try:
                    mapping = _mapping_from_row(rule)
                except ValueError as exc:
                    await _record_quarantine_refusal(
                        session,
                        tenant_id=tenant_id,
                        source=source,
                        raw_metric_type=raw_metric_type,
                        reason="invalid_mapping_rule",
                    )
                    logger.error(
                        "Ignoring invalid mapping rule for tenant=%s source=%s metric=%s: %s",
                        tenant_id,
                        source.id,
                        raw_metric_type,
                        exc,
                    )
                    if sync_run_id:
                        await _tally(
                            session,
                            tenant_id,
                            sync_run_id,
                            source_id=source.id,
                            event_key=event_key,
                            inserted=None,
                        )
                    await session.commit()
                    await msg.ack()
                    return
                metric_type = mapping.target_metric_type
                numeric_value, metadata = replay_value(numeric_value, metadata, mapping)
                idempotency_key = derive_idempotency_key(
                    tenant_id, idempotency_source_id, metric_type, ts_val
                )
            elif metric_type != raw_metric_type:
                # Importers must canonicalise aliases before hashing. Core does not
                # rewrite this path because doing so would create a key/name mismatch.
                logger.error(
                    "Rejected event for tenant=%s: metric_type %r is a legacy alias of %r. "
                    "Acking to prevent redelivery.",
                    tenant_id,
                    raw_metric_type,
                    metric_type,
                )
                if sync_run_id:
                    await _tally(
                        session,
                        tenant_id,
                        sync_run_id,
                        source_id=source.id,
                        event_key=event_key,
                        inserted=None,
                    )
                    await session.commit()
                await msg.ack()
                return

            stmt = insert(DataPoint).values(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source_id=source_id,
                metric_type=metric_type,
                timestamp=ts_val,
                value=numeric_value,
                metadata_=metadata,
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
                await _tally(
                    session,
                    tenant_id,
                    sync_run_id,
                    source_id=source.id,
                    event_key=event_key,
                    inserted=inserted,
                )
            else:
                await _mark_source_seen(session, tenant_id, data)

            await session.commit()

        await msg.ack()
    except IntegrityError:
        # The fifth "a retry cannot fix this", and the one that cannot be seen in the
        # payload: a foreign key naming a tenant or a connector that does not exist.
        # Acked for the same reason as the four above, and it matters more than they do
        # because this arrives in bulk — a database wiped while a stream kept its events
        # leaves every one of them permanently unstorable.
        # `error`, not `exception`: the sentence is the whole diagnosis, and these arrive
        # in the millions. A traceback per event turns draining a stale backlog into a
        # second problem -- gigabytes of logs describing the same three lines of ORM.
        logger.error(
            "Rejected event for tenant=%s source=%s: it violates a database constraint, "
            "which a redelivery cannot change. Acking to prevent redelivery.",
            tenant_id,
            source_id,
        )
        await msg.ack()
    except Exception as exc:  # noqa: BLE001 - transient failures need redelivery
        logger.error(
            "Error processing ingest event for tenant=%s source=%s (%s)",
            tenant_id,
            source_id,
            type(exc).__name__,
        )
        await _retry_or_give_up(msg)


#: Attempts before an event is given up on. A durable consumer's ack window is finite
#: — 1000 by default — so messages that always fail occupy it and nothing behind them is
#: ever delivered. That is not a slow queue but a stopped one, and it is invisible from
#: the outside: measured here once at 1,043,404 pending behind 1.8 million events for a
#: tenant a database wipe had removed, with nothing stored from *any* importer for as
#: long as it stood, while each importer reported its own publishes as successful.
#:
#: Five rather than one, because unlike the rejections above this branch cannot tell a
#: permanent failure from a database that happens to be restarting.
MAX_DELIVERY_ATTEMPTS = 5


async def _retry_or_give_up(msg) -> None:
    """Leave a message for redelivery, unless it has had enough attempts.

    JetStream's `max_deliver` defaults to unlimited, and "unlimited" for an event that
    fails identically every time means the ack slot it holds is never released. The
    consumer is configured with a limit as well; this is the half that works on a
    consumer created before that config existed.
    """
    try:
        delivered = msg.metadata.num_delivered
    except Exception:  # noqa: BLE001 - metadata is absent on a non-JetStream message
        return

    if delivered < MAX_DELIVERY_ATTEMPTS:
        return  # Not acked: JetStream redelivers (at-least-once).

    logger.error(
        "Giving up on an event after %d attempts and terminating it. The ack window is "
        "worth more than this message: held by failures, it stops ingestion for every "
        "tenant. The payload stays in the stream's log for as long as its retention "
        "allows, so it can still be examined.",
        delivered,
    )
    await msg.term()


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


async def _tally(
    session: AsyncSession,
    tenant_id: str,
    sync_run_id: str,
    *,
    source_id: str | None = None,
    event_key: str,
    inserted: bool | None,
) -> None:
    """Accumulate Core processing counts and close a drained import run.

    Tenant- and connector-scoped on purpose: a forged ``sync_run_id`` from another
    tenant or connector must not let an event touch that audit record.

    ``points_received`` is the importer's publish count. ``points_processed`` is
    advanced here, after Core has stored, deduplicated or quarantined the event.
    The distinction prevents the importer from reporting success while NATS still
    holds events that Core has not loaded. The ledger insert is in the same
    transaction as the counter update, so a JetStream redelivery cannot count twice.
    """
    ledger = insert(SyncRunEvent).values(
        tenant_id=tenant_id,
        sync_run_id=sync_run_id,
        event_key=event_key[:128],
    )
    ledger = ledger.on_conflict_do_nothing(
        index_elements=["tenant_id", "sync_run_id", "event_key"],
    )
    ledger_result = await session.execute(ledger)
    if (ledger_result.rowcount or 0) == 0:
        return

    processed = SyncRun.points_processed + 1
    values = {SyncRun.points_processed: processed}
    if inserted is not None:
        column = SyncRun.points_accepted if inserted else SyncRun.points_duplicate
        values[column] = column + 1

    drained = and_(
        SyncRun.status == "loading",
        SyncRun.finished_at.is_(None),
        SyncRun.points_expected.is_not(None),
        processed >= SyncRun.points_expected,
    )
    now = datetime.now(timezone.utc)
    values.update(
        {
            SyncRun.status: case((drained, "success"), else_=SyncRun.status),
            SyncRun.finished_at: case((drained, now), else_=SyncRun.finished_at),
            SyncRun.message: case(
                (drained, "Core loaded all published data points."),
                else_=SyncRun.message,
            ),
            SyncRun.message_code: case(
                (drained, "core_loaded"),
                else_=SyncRun.message_code,
            ),
            SyncRun.message_params: case(
                (drained, {}),
                else_=SyncRun.message_params,
            ),
        }
    )

    run_query = update(SyncRun).where(
        SyncRun.id == sync_run_id,
        SyncRun.tenant_id == tenant_id,
    )
    if source_id is not None:
        run_query = run_query.where(SyncRun.source_id == source_id)
    result = await session.execute(
        run_query.values(values).returning(
            SyncRun.source_id, SyncRun.status, SyncRun.points_processed
        )
    )
    completed = result.first()
    if not completed or completed.status != "success":
        return

    # The connector badge follows the same authoritative transition as the run.
    # It must not return to idle when the importer merely finished publishing.
    source_id = completed.source_id
    if not source_id:
        return
    source_result = await session.execute(
        select(DataSource).where(
            DataSource.tenant_id == tenant_id,
            DataSource.id == source_id,
        )
    )
    source = source_result.scalars().first()
    if source is not None:
        config = dict(source.config or {})
        config["sync_status"] = "idle"
        config["last_sync_at"] = now.isoformat()
        config["last_sync_message"] = "Core loaded all published data points."
        source.config = config


# One connection attempt fails fast rather than burning the library's default
# retry budget inside it. Retrying is this module's job (see run_consumer_forever),
# so that a broker outage cannot hold up anything that calls in here.
CONNECT_TIMEOUT_SECONDS = 5
RECONNECT_INITIAL_DELAY = 1.0
RECONNECT_MAX_DELAY = 30.0

#: How long JetStream waits for an ack before redelivering. Named rather than left to the
#: library's default because it is half of what a stuck message costs: attempts times
#: this is how long one ack slot is unavailable.
ACK_WAIT_SECONDS = 30

#: The ingestion stream is a buffer, not an archive: an event in it is either stored
#: within seconds or re-derivable — importers re-poll, and an export file can be uploaded
#: again. Unbounded retention turned that assumption into a gigabyte of events for a
#: tenant a database wipe had deleted, which no consumer could ever drain and no limit
#: would ever expire. A week is long enough to survive an outage of Core and short enough
#: that a broker cannot outlive the database it feeds.
STREAM_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
STREAM_MAX_BYTES = 4 * 1024 * 1024 * 1024


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

    stream = StreamConfig(
        name="ingestion",
        subjects=["qs.ingest.>"],
        max_age=STREAM_MAX_AGE_SECONDS,
        max_bytes=STREAM_MAX_BYTES,
        discard=DiscardPolicy.OLD,
    )
    try:
        await js.add_stream(stream)
    except Exception:  # noqa: BLE001 - the stream already exists, which is the normal case
        # Its limits are brought up to date rather than left as whatever the first Core
        # to start ever created. An unbounded stream is the state this exists to correct,
        # so finding one is expected, not exceptional.
        try:
            await js.update_stream(stream)
        except Exception as exc:  # noqa: BLE001 - a server too old to update it still serves
            logger.warning(
                "Could not apply the ingestion stream's limits (%s)",
                type(exc).__name__,
            )

    consumer = ConsumerConfig(
        max_deliver=MAX_DELIVERY_ATTEMPTS,
        ack_wait=ACK_WAIT_SECONDS,
    )
    try:
        await js.subscribe(
            "qs.ingest.>", "core_data_service_group", cb=process_message, config=consumer
        )
    except Exception as exc:  # noqa: BLE001 - an existing consumer may refuse the change
        logger.warning(
            "Could not apply the consumer's delivery limit (%s); subscribing without it. "
            "`_retry_or_give_up` still terminates an event that cannot be stored.",
            type(exc).__name__,
        )
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
