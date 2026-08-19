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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import nats
from nats.js.api import ConsumerConfig, DiscardPolicy, RetentionPolicy, StreamConfig
from shared_schemas import idempotency_key as derive_idempotency_key
from shared_schemas.metrics import UnknownMetricTypeError, canonical_metric_type
from sqlalchemy import and_, case, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
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
from core.deployment_warnings import Warning_
from core.metric_mapping import ValidatedMapping, replay_value, validate_mapping
from core.rollups import update_rollups_for_point
from core.tracing import get_current_request_id, set_current_request_id

logger = logging.getLogger(__name__)

MAX_QUARANTINED_NAMES = 100
MAX_QUARANTINED_ROWS = 100_000
MAX_QUARANTINE_REFUSALS = 10_000
DEFAULT_QUARANTINE_RETENTION_DAYS = 30
MAX_INGEST_EVENT_BYTES = 256 * 1024
MAX_POINT_METADATA_BYTES = 32 * 1024
MAX_BATCH_EVENTS = 1000
MAX_BATCH_BYTES = 512 * 1024


def _processing_event_key(msg) -> str:
    """Return a stable, bounded identity for one broker delivery.

    JetStream stream sequence numbers are stable across redelivery. Plain NATS
    fallback subscriptions do not expose them, so a payload fingerprint is the
    safe fallback. The key is only a progress-ledger identity; provider values
    never enter the ledger.
    """
    if (event_key := getattr(msg, "event_key", None)):
        return str(event_key)[:128]
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


async def _tally_rejected_event(
    *,
    tenant_id: str | None,
    source_id: str | None,
    sync_run_id: str | None,
    event_key: str,
    session: AsyncSession | None = None,
) -> None:
    """Count a valid run-scoped event that Core permanently rejects.

    Importers set ``points_expected`` to the number of events they publish. A
    permanent validation rejection is still processed by Core, so it must advance
    the same once-only ledger as an accepted, duplicate or quarantined event. The
    helper verifies the tenant/source/run relationship before writing anything;
    malformed or forged identifiers are therefore acknowledged without creating an
    orphan progress record.
    """
    if not all(
        isinstance(value, str) and value
        for value in (tenant_id, source_id, sync_run_id)
    ):
        return

    async def record(rejection_session: AsyncSession) -> None:
        run = await rejection_session.execute(
            select(SyncRun.id).where(
                SyncRun.id == sync_run_id,
                SyncRun.tenant_id == tenant_id,
                SyncRun.source_id == source_id,
            )
        )
        if run.scalar_one_or_none() is None:
            return
        await _tally(
            rejection_session,
            tenant_id,
            sync_run_id,
            source_id=source_id,
            event_key=event_key,
            inserted=None,
            rejected=True,
        )

    if session is not None:
        await record(session)
        return

    async with async_session_maker() as rejection_session:
        await record(rejection_session)
        await rejection_session.commit()


class _SyntheticPointMessage:
    """A no-ack view of one point inside a versioned batch envelope."""

    def __init__(self, data: bytes, *, event_key: str | None = None) -> None:
        self.data = data
        self.metadata = None
        self.failed = False
        # Whether the failure is one a redelivery could fix. A constraint violation
        # is not: the envelope would fail identically every time and take its 999
        # healthy siblings down with it on the last attempt.
        self.permanent = False
        self.event_key = event_key or "payload:" + hashlib.sha256(data).hexdigest()

    async def ack(self) -> None:
        """Keep the envelope pending until every child has completed."""

    async def term(self) -> None:
        """A child rejection is already recorded; the envelope remains retryable."""


async def _process_batch_message(msg: Any, envelope: dict[str, Any]) -> None:
    """Process a bounded envelope while preserving single-point semantics.

    The child path retains the existing validation, idempotency and run-ledger
    behavior. All child writes share one database transaction, so the envelope is
    acknowledged only after every child has either been durably stored, deduplicated
    or permanently rejected. A transient child failure rolls the transaction back
    and leaves the whole envelope for redelivery.
    """
    events = envelope.get("events")
    if not isinstance(events, list) or not events or len(events) > MAX_BATCH_EVENTS:
        logger.error("Rejected ingest batch: event count exceeds the bounded contract")
        await msg.ack()
        return
    if len(msg.data) > MAX_BATCH_BYTES:
        logger.error("Rejected oversized ingest batch. Acking to prevent redelivery.")
        await msg.ack()
        return

    inherited_keys = (
        "tenant_id",
        "source_id",
        "source_type",
        "request_id",
        "sync_run_id",
    )
    batch_id = str(envelope.get("batch_id") or hashlib.sha256(msg.data).hexdigest())

    async with async_session_maker() as session:
        known_source: DataSource | None = None
        tenant_value = envelope.get("tenant_id")
        source_value = envelope.get("source_id")
        try:
            uuid.UUID(str(tenant_value))
            uuid.UUID(str(source_value))
        except (ValueError, AttributeError, TypeError):
            pass
        else:
            source_result = await session.execute(
                select(DataSource).where(
                    DataSource.tenant_id == tenant_value,
                    DataSource.id == source_value,
                )
            )
            known_source = source_result.scalars().first()

        failed = False
        permanently_rejected = 0
        for index, raw_child in enumerate(events):
            child = dict(raw_child) if isinstance(raw_child, dict) else {}
            mismatch = any(
                key in child
                and key in envelope
                and child[key] != envelope[key]
                for key in inherited_keys
            )
            if mismatch:
                logger.error("Rejected ingest batch child with mismatched envelope identity")
                child = {}
            for key in inherited_keys:
                if key in envelope:
                    child.setdefault(key, envelope[key])
            if "metric_type" not in child:
                child["metric_type"] = None

            child_key = hashlib.sha256(f"{batch_id}:{index}".encode()).hexdigest()
            synthetic = _SyntheticPointMessage(
                json.dumps(child).encode("utf-8"), event_key=f"batch:{child_key}"
            )
            # Each child inside its own savepoint. Without one, a child that
            # violates a constraint poisons the shared transaction, so the only
            # available response was to fail the whole envelope — which JetStream
            # then redelivered five times before discarding all thousand events,
            # the 999 storable ones included. The single-event path has acked this
            # class of failure since the day a wiped database produced it in bulk;
            # the batch path could not, and so undid that fix wherever batching was
            # in use.
            nested = await session.begin_nested()
            await process_message(
                synthetic,
                db_session=session,
                known_source=known_source,
            )

            if synthetic.failed:
                # Rolled back before anything else is decided. A transient failure
                # is usually a DBAPI error, which leaves the transaction aborted —
                # and `RELEASE SAVEPOINT` on an aborted transaction raises, so
                # committing first and branching afterwards threw out of this
                # function entirely, skipping both the rollback below and
                # `_retry_or_give_up`. `nested.rollback()`, not
                # `session.rollback()`: the savepoint is what has to go, and
                # rolling back the session would discard every sibling already
                # written in this envelope.
                await nested.rollback()
                if not synthetic.permanent:
                    # A database restarting, say. The envelope stays
                    # unacknowledged so JetStream delivers it again.
                    failed = True
                    break
                permanently_rejected += 1
                logger.error(
                    "Dropped child %s of ingest batch %s: it violates a database "
                    "constraint, which a redelivery cannot change.",
                    index,
                    batch_id,
                )
                # Counted against the run, not only logged. The single-event path
                # tallies this class of rejection, and a batch that quietly did
                # not would leave `points_processed` short of `points_expected`
                # forever — the run never reconciles, and the only trace is a log
                # line. Rule 19: stored, carried, or *named*.
                await _tally_rejected_event(
                    tenant_id=child.get("tenant_id"),
                    source_id=child.get("source_id"),
                    sync_run_id=child.get("sync_run_id"),
                    event_key=synthetic.event_key,
                    session=session,
                )
                continue

            await nested.commit()

        if failed:
            await session.rollback()
        else:
            await session.commit()
            if permanently_rejected:
                logger.error(
                    "Ingest batch %s stored %s of %s events; %s could not be stored "
                    "and were dropped rather than failing the envelope.",
                    batch_id,
                    len(events) - permanently_rejected,
                    len(events),
                    permanently_rejected,
                )

    if failed:
        if all(
            isinstance(envelope.get(key), str) and envelope.get(key)
            for key in ("tenant_id", "source_id", "sync_run_id")
        ):
            await _retry_or_give_up(
                msg,
                tenant_id=envelope["tenant_id"],
                source_id=envelope["source_id"],
                sync_run_id=envelope["sync_run_id"],
            )
        else:
            await _retry_or_give_up(msg)
        return
    await msg.ack()


@asynccontextmanager
async def _session_scope(
    existing: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    """Use a caller-owned session or create the single-event session."""
    if existing is not None:
        yield existing
        return
    async with async_session_maker() as session:
        yield session


async def process_message(
    msg: Any,
    *,
    db_session: AsyncSession | None = None,
    known_source: DataSource | None = None,
) -> None:
    # Bound before the try so the failure handlers can name the tenant whose event it
    # was; a rejection that does not say whose data it dropped is hard to act on.
    tenant_id: str | None = None
    source_id: str | None = None
    sync_run_id: str | None = None
    event_key = _processing_event_key(msg)
    active_session = db_session
    owns_session = db_session is None

    async def _ack_rejected(session: AsyncSession | None = None) -> None:
        """Acknowledge a permanent rejection after recording run progress."""
        await _tally_rejected_event(
            tenant_id=tenant_id,
            source_id=source_id,
            sync_run_id=sync_run_id,
            event_key=event_key,
            session=session if session is not None else active_session,
        )
        await msg.ack()

    try:
        if len(msg.data) > MAX_BATCH_BYTES:
            logger.error("Rejected oversized ingest event. Acking to prevent redelivery.")
            await _ack_rejected()
            return
        try:
            data = json.loads(msg.data.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.error("Rejected malformed ingest event. Acking to prevent redelivery.")
            await _ack_rejected()
            return
        if not isinstance(data, dict):
            logger.error("Rejected non-object ingest event. Acking to prevent redelivery.")
            await _ack_rejected()
            return

        if data.get("schema_version") == 2 and "events" in data:
            await _process_batch_message(msg, data)
            return
        if len(msg.data) > MAX_INGEST_EVENT_BYTES:
            logger.error("Rejected oversized ingest event. Acking to prevent redelivery.")
            await _ack_rejected()
            return

        # Bind the correlation id before anything is logged, so a whole ingest is
        # traceable back to the sync that requested it.
        request_id = data.get("request_id")
        if request_id is not None and (
            not isinstance(request_id, str) or not request_id or len(request_id) > 128
        ):
            logger.error("Rejected ingest event with an invalid request_id.")
            await _ack_rejected()
            return
        if request_id:
            set_current_request_id(request_id)

        # INVARIANT: TenantIsolation — reject events without tenant_id
        tenant_id = data.get("tenant_id")
        if not isinstance(tenant_id, str) or not tenant_id or len(tenant_id) > 128:
            logger.error("Rejected event: missing tenant_id. Acking to prevent redelivery.")
            await _ack_rejected()
            return

        idempotency_key = data.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            logger.error("Rejected event: missing idempotency_key. Acking to prevent redelivery.")
            await _ack_rejected()
            return

        raw_metric_type = data.get("metric_type")
        if not isinstance(raw_metric_type, str):
            logger.error("Rejected event for tenant=%s: metric_type is not a string.", tenant_id)
            await _ack_rejected()
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
            await _ack_rejected()
            return
        try:
            uuid.UUID(tenant_id)
            uuid.UUID(source_id)
        except ValueError:
            logger.error(
                "Rejected event: tenant_id or source_id is not a UUID. "
                "Acking to prevent redelivery."
            )
            await _ack_rejected()
            return
        if (
            not isinstance(idempotency_source_id, str)
            or not idempotency_source_id
            or len(idempotency_source_id) > 512
        ):
            logger.error(
                "Rejected event for tenant=%s: idempotency_source_id is invalid.", tenant_id
            )
            await _ack_rejected()
            return
        if sync_run_id is not None:
            try:
                uuid.UUID(str(sync_run_id))
            except (ValueError, AttributeError):
                logger.error("Rejected event for tenant=%s: sync_run_id is invalid.", tenant_id)
                await _ack_rejected()
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
            await _ack_rejected()
            return

        ts_raw = data.get("timestamp")
        if not isinstance(ts_raw, str):
            logger.error("Rejected event for tenant=%s: timestamp is invalid.", tenant_id)
            await _ack_rejected()
            return
        try:
            ts_val = datetime.fromisoformat(ts_raw)
        except ValueError:
            logger.error("Rejected event for tenant=%s: timestamp is invalid.", tenant_id)
            await _ack_rejected()
            return
        if not isinstance(ts_val, datetime):
            logger.error("Rejected event for tenant=%s: timestamp is invalid.", tenant_id)
            await _ack_rejected()
            return
        if ts_val.tzinfo is None:
            ts_val = ts_val.replace(tzinfo=timezone.utc)

        metadata = data.get("metadata")
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            logger.error("Rejected event for tenant=%s: metadata is not an object.", tenant_id)
            await _ack_rejected()
            return
        raw_value = data.get("value")
        if raw_value is not None and (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, (int, float))
            or not math.isfinite(float(raw_value))
        ):
            logger.error("Rejected event for tenant=%s: value is not numeric.", tenant_id)
            await _ack_rejected()
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
            await _ack_rejected()
            return

        metadata = bounded_point_metadata(metadata, numeric_value)

        async with _session_scope(db_session) as session:
            active_session = session
            source = known_source
            if source is None:
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
                await _ack_rejected(session)
                if owns_session:
                    await session.commit()
                return
            if event_source_type is not None and event_source_type != source.source_type:
                logger.error(
                    "Rejected event for tenant=%s source=%s: source_type does not match "
                    "the configured connector.",
                    tenant_id,
                    source.id,
                )
                await _ack_rejected(session)
                if owns_session:
                    await session.commit()
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
                await _ack_rejected(session)
                if owns_session:
                    await session.commit()
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
                            rejected=True,
                        )
                    if owns_session:
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
                            rejected=True,
                        )
                    if owns_session:
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
                            rejected=True,
                        )
                    if owns_session:
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
                        rejected=True,
                    )
                    if owns_session:
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

            if inserted:
                await update_rollups_for_point(
                    session,
                    tenant_id=tenant_id,
                    source_id=source.id,
                    metric_type=metric_type,
                    timestamp=ts_val,
                    value=numeric_value,
                    metadata=metadata,
                )

            if not inserted:
                # `debug`, not `info`. A duplicate is the idempotency key doing its
                # job (rule 4) — the expected outcome of any re-import — and one line
                # per duplicate made this the loudest stream in the deployment:
                # 77,000 lines in 48 hours, of which essentially every one said this.
                # A real error in that stream is unfindable, which turns a log into a
                # thing nobody reads.
                #
                # Nothing is lost by moving it. The count is already kept per run and
                # reported: `points_duplicate` on the `SyncRun`, via `_tally` below,
                # which is where a reader asking "how much of that import was new"
                # should be looking anyway.
                logger.debug(
                    "Duplicate event skipped: tenant=%s key=%s", tenant_id, idempotency_key
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

            if owns_session:
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
        if isinstance(msg, _SyntheticPointMessage) and db_session is not None:
            # The batch owner rolls back to this child's savepoint and carries on.
            # A constraint failure cannot safely be acknowledged from a transaction
            # whose state is already failed, but it is also permanent: marking it as
            # such is what stops one unstorable point from discarding the whole
            # envelope after five identical attempts.
            msg.failed = True
            msg.permanent = True
            return
        await _ack_rejected()
    except Exception as exc:  # noqa: BLE001 - transient failures need redelivery
        if isinstance(msg, _SyntheticPointMessage):
            msg.failed = True
        logger.error(
            "Error processing ingest event for tenant=%s source=%s (%s)",
            tenant_id,
            source_id,
            type(exc).__name__,
        )
        if tenant_id and source_id and sync_run_id:
            await _retry_or_give_up(
                msg,
                tenant_id=tenant_id,
                source_id=source_id,
                sync_run_id=sync_run_id,
            )
        else:
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


async def _mark_sync_run_delivery_failure(
    *,
    tenant_id: str,
    source_id: str,
    sync_run_id: str,
    attempts: int,
) -> None:
    """Close the one run whose event JetStream permanently abandoned.

    The importer has already reported ``loading`` by this point.  If the consumer
    terminates the final delivery without this transition, ``points_processed`` can
    never reach ``points_expected`` and that run remains in the dashboard forever.
    Every predicate names tenant, connector and run so a forged or stale event cannot
    mutate another import; an already terminal run is left untouched.
    """
    if not all(
        isinstance(value, str) and value
        for value in (tenant_id, source_id, sync_run_id)
    ):
        return

    now = datetime.now(timezone.utc)
    message = (
        f"Core stopped retrying this import event after {max(1, attempts)} delivery "
        "attempts. The import is incomplete; retry the source."
    )
    async with async_session_maker() as session:
        transition = await session.execute(
            update(SyncRun)
            .where(
                SyncRun.id == sync_run_id,
                SyncRun.tenant_id == tenant_id,
                SyncRun.source_id == source_id,
                SyncRun.status.in_(("queued", "running", "loading")),
                SyncRun.finished_at.is_(None),
            )
            .values(
                status="error",
                message=message[:512],
                message_code="core_ingest_delivery_failed",
                message_params={"attempts": max(1, attempts)},
                finished_at=now,
            )
            .returning(SyncRun.source_id)
        )
        changed_source_id = transition.scalar_one_or_none()
        if changed_source_id is not None:
            source_result = await session.execute(
                select(DataSource).where(
                    DataSource.tenant_id == tenant_id,
                    DataSource.id == changed_source_id,
                )
            )
            source = source_result.scalars().first()
            if source is not None:
                config = dict(source.config or {})
                config["sync_status"] = "error"
                config["last_sync_at"] = now.isoformat()
                config["last_sync_message"] = message[:512]
                source.config = config
        await session.commit()


async def _retry_or_give_up(
    msg: Any,
    *,
    tenant_id: str | None = None,
    source_id: str | None = None,
    sync_run_id: str | None = None,
) -> None:
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

    if tenant_id and source_id and sync_run_id:
        try:
            await _mark_sync_run_delivery_failure(
                tenant_id=tenant_id,
                source_id=source_id,
                sync_run_id=sync_run_id,
                attempts=delivered,
            )
        except Exception:  # noqa: BLE001 - termination must still release the slot
            logger.error(
                "Could not mark the abandoned ingest event's sync run as failed; "
                "terminating the broker delivery anyway."
            )

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
                DataSource.deleted_at.is_(None),
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
    rejected: bool = False,
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
    if rejected:
        values[SyncRun.points_rejected] = SyncRun.points_rejected + 1

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
                (drained, literal({}, type_=JSONB)),
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
INGESTION_STREAM_NAME = "ingestion"
INGESTION_SUBJECT = "qs.ingest.>"
INGESTION_CONSUMER_NAME = "core_data_service_group"
# During a reset the stream is still present, but ordinary importer subjects no
# longer match it. A publisher already in flight before the update is visible to
# the final consumer_info check; a publisher after the update receives no stream
# acknowledgement and can retry instead of being deleted with the stream.
INGESTION_RESET_GATE_SUBJECT = "qs.internal.ingestion-reset-gate"
INGESTION_RESET_TIMEOUT_SECONDS = 30.0

#: A work queue, because the sentence above was only true of the *comment*.
#:
#: With the default `limits` retention, an acknowledged message stays in the stream
#: until `max_age` expires it. Core stores an event and acks it within milliseconds,
#: and the message then occupies its bytes for the remaining seven days — so the
#: stream is not a buffer holding what has yet to be stored, it is an archive of
#: everything that already has been. Paired with `discard=new`, which refuses a
#: publish rather than dropping unacknowledged data, that archive eventually fills
#: and **every importer stops being able to publish at all**.
#:
#: Measured in production: 6,292,863 messages, 4,294,966,938 bytes against a
#: 4 GiB ceiling — 358 bytes below it — with the consumer fully caught up
#: (`num_pending=0`, `num_ack_pending=0`, ack floor equal to the last sequence).
#: Nothing was stuck; there was simply no room left. Every importer failed
#: identically with `ServiceUnavailableError` after 0 events, across all four
#: triggers, which is what made it look like a Core fault rather than a full disk.
#:
#: `WORK_QUEUE` deletes a message when the consumer acks it, which is the behaviour
#: the comment above always claimed. `discard=new` keeps its meaning and gets its
#: teeth back: the stream can now only fill with events Core has *not* yet stored,
#: which is the one case where refusing a publish is the correct answer.
#:
#: This requires exactly one consumer per subject, which `qs.ingest.>` has
#: (`core_data_service_group`). A second overlapping consumer would be refused by
#: the broker rather than silently stealing messages.
STREAM_RETENTION = RetentionPolicy.WORK_QUEUE


def ingestion_stream_config() -> StreamConfig:
    """Return the one configured shape used when the ingestion stream is created."""
    return StreamConfig(
        name=INGESTION_STREAM_NAME,
        subjects=[INGESTION_SUBJECT],
        max_age=STREAM_MAX_AGE_SECONDS,
        max_bytes=STREAM_MAX_BYTES,
        retention=STREAM_RETENTION,
        discard=DiscardPolicy.NEW,
    )


def _stream_config_with_subjects(config: StreamConfig, subjects: list[str]) -> StreamConfig:
    """Preserve every broker setting while changing only the accepted subjects."""
    return replace(config, subjects=subjects)


def _counter(info: Any, name: str) -> int:
    """Read a JetStream consumer counter without allowing an unknown value as zero."""
    value = getattr(info, name, None)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"consumer_info returned an invalid {name}")
    return value


class IngestionResetError(RuntimeError):
    """Stable API error raised when a stream reset cannot be completed safely."""

    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 503,
        num_pending: int | None = None,
        num_ack_pending: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.num_pending = num_pending
        self.num_ack_pending = num_ack_pending

    def as_dict(self) -> dict[str, Any]:
        """Return the machine-readable response shared by Core and the Gateway."""
        payload: dict[str, Any] = {"code": self.code, "detail": self.detail}
        if self.num_pending is not None:
            payload["num_pending"] = self.num_pending
        if self.num_ack_pending is not None:
            payload["num_ack_pending"] = self.num_ack_pending
        return payload


def _client_is_connected(client: Any) -> bool:
    """Read nats-py's connection state while keeping simple fakes compatible."""
    state = getattr(client, "is_connected", True)
    if callable(state):
        state = state()
    return bool(state)


class IngestionConsumerController:
    """Own the live consumer connection and coordinate a safe stream reset.

    The supervisor calls ``connected`` after the stream has been recreated and
    the durable subscription has been installed. The reset path therefore waits
    for that callback rather than guessing that a closed socket means the next
    consumer is ready.
    """

    def __init__(self) -> None:
        self.client: Any | None = None
        self.connection_lost: asyncio.Event | None = None
        self.status = "disconnected"
        self.generation = 0
        self.ready = asyncio.Event()
        self._lock = asyncio.Lock()
        self._reset_in_progress = False

    def connected(self, client: Any, connection_lost: asyncio.Event) -> None:
        """Record a client only after ``start_consumer`` completed successfully."""
        self.client = client
        self.connection_lost = connection_lost
        self.status = "connected"
        self.generation += 1
        self.ready.set()

    def disconnected(self, client: Any) -> None:
        """Forget a client only if it is still the current one."""
        if self.client is client:
            self.client = None
            self.connection_lost = None
            self.status = "disconnected"
            self.ready.clear()

    def _assert_current(self, client: Any, connection_lost: asyncio.Event) -> None:
        """Refuse to mutate a stream after the supervisor has changed clients."""
        if (
            self.client is not client
            or self.connection_lost is not connection_lost
            or connection_lost.is_set()
            or not _client_is_connected(client)
        ):
            raise IngestionResetError(
                "ingestion_consumer_unavailable",
                "The ingestion consumer connection changed during the reset; no stream was deleted.",
            )

    async def _consumer_counts(self, js: Any) -> tuple[int, int]:
        """Read both safety counters from the named durable consumer."""
        info = await js.consumer_info(INGESTION_STREAM_NAME, INGESTION_CONSUMER_NAME)
        return _counter(info, "num_pending"), _counter(info, "num_ack_pending")

    async def _restore_subjects(self, js: Any, config: StreamConfig) -> None:
        """Re-open ordinary importer subjects after an aborted gated reset."""
        try:
            await js.update_stream(config)
        except Exception as exc:
            logger.error(
                "[req_id=%s] Could not restore ingestion stream subjects after reset refusal (%s)",
                get_current_request_id(),
                type(exc).__name__,
            )
            raise IngestionResetError(
                "ingestion_reset_gate_restore_failed",
                "The ingestion reset was refused, but the temporary publish gate could not be removed.",
            ) from exc

    async def _wait_for_reconnected(self, previous_generation: int) -> None:
        """Wait until the supervisor has recreated and subscribed a new client."""
        deadline = asyncio.get_running_loop().time() + INGESTION_RESET_TIMEOUT_SECONDS
        while self.generation <= previous_generation or self.client is None:
            self.ready.clear()
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise IngestionResetError(
                    "ingestion_stream_recreation_timeout",
                    "The ingestion stream was deleted, but Core did not recreate its consumer in time.",
                )
            try:
                await asyncio.wait_for(self.ready.wait(), timeout=remaining)
            except TimeoutError as exc:
                raise IngestionResetError(
                    "ingestion_stream_recreation_timeout",
                    "The ingestion stream was deleted, but Core did not recreate its consumer in time.",
                ) from exc

    async def reset(self) -> dict[str, Any]:
        """Gate publishers, re-check counters, delete, and await resubscription."""
        # The flag is set before the first await. That closes the small gap in
        # which two requests could both observe an unlocked asyncio.Lock.
        if self._reset_in_progress:
            raise IngestionResetError(
                "ingestion_reset_busy",
                "Another ingestion stream reset is already in progress.",
                status_code=409,
            )
        self._reset_in_progress = True
        lock_acquired = False
        jetstream: Any | None = None
        restore_config: StreamConfig | None = None
        gate_active = False
        stream_deleted = False

        async def restore_gate() -> None:
            """Restore importer subjects after a reset stops before deletion."""
            nonlocal gate_active
            if not gate_active or stream_deleted or jetstream is None or restore_config is None:
                return
            await self._restore_subjects(jetstream, restore_config)
            gate_active = False

        try:
            await self._lock.acquire()
            lock_acquired = True
            client = self.client
            connection_lost = self.connection_lost
            # Capture this before any broker await. A supervisor reconnect that
            # wins a race before deletion must count as a new generation, never
            # as the client this request started with.
            previous_generation = self.generation
            if (
                client is None
                or connection_lost is None
                or connection_lost.is_set()
                or not _client_is_connected(client)
            ):
                raise IngestionResetError(
                    "ingestion_consumer_unavailable",
                    "The ingestion consumer is not connected; no stream was deleted.",
                )

            js = client.jetstream()
            jetstream = js
            try:
                num_pending, num_ack_pending = await self._consumer_counts(js)
            except Exception as exc:
                raise IngestionResetError(
                    "ingestion_consumer_unavailable",
                    "Core could not inspect the ingestion consumer; no stream was deleted.",
                ) from exc

            if num_pending or num_ack_pending:
                raise IngestionResetError(
                    "ingestion_reset_pending_events",
                    "The ingestion stream still contains events that must be stored before it can be reset.",
                    status_code=409,
                    num_pending=num_pending,
                    num_ack_pending=num_ack_pending,
                )

            self._assert_current(client, connection_lost)
            try:
                stream_info = await js.stream_info(INGESTION_STREAM_NAME)
                original_config = stream_info.config
                original_subjects = list(original_config.subjects or [INGESTION_SUBJECT])
                restore_config = _stream_config_with_subjects(
                    original_config, original_subjects
                )
                gated_config = _stream_config_with_subjects(
                    original_config,
                    [INGESTION_RESET_GATE_SUBJECT],
                )
                # Mark this before the await: the broker may apply an update and
                # then lose the connection before returning to the caller.
                gate_active = True
                await js.update_stream(gated_config)
            except IngestionResetError:
                raise
            except Exception as exc:
                await restore_gate()
                raise IngestionResetError(
                    "ingestion_reset_gate_failed",
                    "Core could not pause ingestion publishers; no stream was deleted.",
                ) from exc

            try:
                # The gate closes the publish/delete race: a normal importer
                # subject cannot enter the stream after this update. A message
                # accepted before the update is still caught by this final check.
                self._assert_current(client, connection_lost)
                num_pending, num_ack_pending = await self._consumer_counts(js)
                if num_pending or num_ack_pending:
                    await restore_gate()
                    raise IngestionResetError(
                        "ingestion_reset_pending_events",
                        "The ingestion stream received an event while the reset was starting; nothing was deleted.",
                        status_code=409,
                        num_pending=num_pending,
                        num_ack_pending=num_ack_pending,
                    )

                self._assert_current(client, connection_lost)
                deleted = await js.delete_stream(INGESTION_STREAM_NAME)
                if deleted is False:
                    raise RuntimeError("delete_stream returned false")
                stream_deleted = True
                gate_active = False
            except IngestionResetError:
                with suppress(Exception):
                    await restore_gate()
                raise
            except Exception as exc:
                await restore_gate()
                raise IngestionResetError(
                    "ingestion_stream_reset_failed",
                    "Core could not delete the gated ingestion stream; no data was deleted.",
                ) from exc

            # Do this before closing the socket. The endpoint must never report
            # the deleted connection as active while the supervisor is waking.
            self.client = None
            self.connection_lost = None
            self.status = "resetting"
            connection_lost.set()
            with suppress(Exception):
                await client.close()

            await self._wait_for_reconnected(previous_generation)
            return {
                "code": "ingestion_stream_reset",
                "status": "recreated",
                "stream": INGESTION_STREAM_NAME,
                "retention": STREAM_RETENTION.value,
            }
        except asyncio.CancelledError:
            # A browser disconnect must not leave the stream accepting only the
            # internal gate subject. Cleanup is safe before deletion and the
            # supervisor will reconcile the stream if the connection itself died.
            with suppress(Exception):
                await restore_gate()
            raise
        finally:
            if lock_acquired:
                self._lock.release()
            self._reset_in_progress = False


async def ingestion_retention_warning(client: Any) -> Warning_ | None:
    """Return the dashboard warning when the live stream has old retention."""
    if client is None or not _client_is_connected(client):
        return None
    try:
        info = await client.jetstream().stream_info(INGESTION_STREAM_NAME)
    except Exception:  # noqa: BLE001 - a disconnected broker is not a mismatch
        return None

    actual = getattr(info.config.retention, "value", info.config.retention)
    expected = getattr(STREAM_RETENTION, "value", STREAM_RETENTION)
    if actual == expected:
        return None
    counts: dict[str, str] = {}
    try:
        consumer_info = await client.jetstream().consumer_info(
            INGESTION_STREAM_NAME,
            INGESTION_CONSUMER_NAME,
        )
        counts = {
            "num_pending": str(_counter(consumer_info, "num_pending")),
            "num_ack_pending": str(_counter(consumer_info, "num_ack_pending")),
        }
    except Exception as exc:  # noqa: BLE001 - a mismatch remains useful without counts
        logger.debug(
            "Could not read ingestion consumer counts for the retention warning (%s)",
            type(exc).__name__,
        )
    return Warning_(
        code="ingestion_stream_retention_mismatch",
        severity="critical",
        title="The ingestion stream uses the wrong retention policy",
        detail=(
            f"The stream currently uses {actual}; it must use {expected}. "
            "An owner can reset it after confirming that the queue is empty."
        ),
        action="An owner can reset the ingestion stream from the dashboard after confirming the queue is empty.",
        docs="/docs/operations.html#rebuilding-a-workspace-from-scratch",
        params={
            "actual_retention": str(actual),
            "expected_retention": str(expected),
            "owner_only": "true",
            **counts,
        },
    )


async def _reconcile_stream(js: Any, desired: StreamConfig) -> None:
    """Bring an existing ingestion stream up to the configuration above.

    `max_age` and `max_bytes` are updatable in place. **`retention` is not** — the
    broker rejects a change on a live stream, and that refusal is the one worth
    saying out loud rather than folding into a generic warning: a stream left on
    `limits` retention will fill with already-stored events and stop accepting
    publishes from every importer at once (see STREAM_RETENTION).

    Deliberately not self-healing. Switching retention means deleting and
    recreating the stream, and a stream may hold events Core has not stored yet;
    destroying those to fix a configuration problem would trade an outage that
    stops when someone acts for data loss that does not. So this reports precisely
    what is wrong and what to do, and leaves the decision to a person.
    """
    try:
        current = await js.stream_info(desired.name)
        actual_retention = current.config.retention
    except Exception as exc:  # noqa: BLE001 - an old server may not answer stream_info
        logger.warning(
            "Could not read the ingestion stream's configuration (%s)",
            type(exc).__name__,
        )
        actual_retention = None

    if actual_retention is not None and actual_retention != desired.retention:
        logger.error(
            "The 'ingestion' stream uses %s retention, not %s. Acknowledged events "
            "are therefore kept until max_age instead of being dropped once stored, "
            "so the stream fills with data Core already holds and discard=new then "
            "refuses every importer's publish. Retention cannot be changed in place: "
            "drain the stream, confirm the consumer reports num_pending=0 and "
            "num_ack_pending=0, then delete and let Core recreate it.",
            getattr(actual_retention, "value", actual_retention),
            getattr(desired.retention, "value", desired.retention),
        )
    # What is actually sent. On a retention mismatch the broker rejects the whole
    # update, so asking for the desired retention would also throw away the age
    # and byte ceilings — in exactly the deployment where they matter most, since
    # a legacy `limits` stream is the one that fills up. Ask for the retention the
    # stream already has, and the rest applies.
    applicable = desired
    if actual_retention is not None and actual_retention != desired.retention:
        applicable = replace(desired, retention=actual_retention)

    try:
        await js.update_stream(applicable)
    except Exception as exc:  # noqa: BLE001 - a server too old to update it still serves
        logger.warning(
            "Could not apply the ingestion stream's limits (%s)",
            type(exc).__name__,
        )


async def start_consumer(
    connection_lost: asyncio.Event | None = None,
) -> Any:
    """Connect to NATS and subscribe. Raises promptly if the broker is unreachable.

    ``connection_lost`` is owned by the supervisor. Both the disconnect and close
    callbacks set it because this client deliberately disables nats-py's internal
    reconnect loop; the supervisor must create a new client and re-bind the durable
    subscription instead.
    """
    if connection_lost is None:
        connection_lost = asyncio.Event()

    async def mark_connection_lost() -> None:
        connection_lost.set()

    nc = await nats.connect(
        settings.NATS_URL,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        # No retries *here*. nats-py's default is 60 attempts two seconds apart,
        # so an unreachable broker blocked this call for two minutes -- and with
        # it Core's startup, because the lifespan awaited it before serving. The
        # HTTP API has no business being unavailable because the broker is down.
        max_reconnect_attempts=0,
        allow_reconnect=False,
        disconnected_cb=mark_connection_lost,
        closed_cb=mark_connection_lost,
    )
    ready = False
    try:
        js = nc.jetstream()

        # The reset controller and the supervisor must recreate the same shape.
        stream = ingestion_stream_config()
        try:
            await js.add_stream(stream)
        except Exception:  # noqa: BLE001 - the stream already exists, which is the normal case
            # Its limits are brought up to date rather than left as whatever the first Core
            # to start ever created. An unbounded stream is the state this exists to correct,
            # so finding one is expected, not exceptional.
            await _reconcile_stream(js, stream)

        consumer = ConsumerConfig(
            max_deliver=MAX_DELIVERY_ATTEMPTS,
            ack_wait=ACK_WAIT_SECONDS,
            max_ack_pending=1000,
        )
        try:
            await js.subscribe(
                INGESTION_SUBJECT,
                INGESTION_CONSUMER_NAME,
                cb=process_message,
                config=consumer,
            )
        except Exception as exc:  # noqa: BLE001 - an existing consumer may refuse the change
            logger.warning(
                "Could not apply the consumer's delivery limit (%s); subscribing without it. "
                "`_retry_or_give_up` still terminates an event that cannot be stored.",
                type(exc).__name__,
            )
            await js.subscribe(
                INGESTION_SUBJECT,
                INGESTION_CONSUMER_NAME,
                cb=process_message,
            )
        logger.info("Started consuming from qs.ingest.>")
        ready = True
        return nc
    finally:
        if not ready:
            with suppress(Exception):
                await nc.close()


async def run_consumer_forever(
    on_connected: Callable[[Any], None] | None = None,
    on_connection_ready: Callable[[Any, asyncio.Event], None] | None = None,
    on_connection_lost: Callable[[Any], None] | None = None,
) -> None:
    """Supervise the subscription and reconnect after a connection loss.

    Meant to run as a background task so that Core serves HTTP and gRPC whether
    or not the broker is up. Ingestion is degraded while NATS is unreachable;
    queries, authentication and the dashboard are not, and conflating the two
    turns a broker outage into a full outage.

    The first connection attempt fails fast. Failed attempts then back off
    exponentially up to 30s. An established connection signals both disconnect
    and close through its event; the next loop iteration creates a new client and
    rebinds the durable subscription with the same ``process_message`` callback.
    A tight retry loop against a broker that is restarting is its own kind of
    denial of service.
    """
    delay = RECONNECT_INITIAL_DELAY
    while True:
        connection_lost = asyncio.Event()
        try:
            nc = await start_consumer(connection_lost=connection_lost)
        except Exception as exc:  # noqa: BLE001 - any failure means "not connected yet"
            logger.warning(
                "NATS unavailable (%s); ingestion is paused, retrying in %.0fs",
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
            continue

        delay = RECONNECT_INITIAL_DELAY
        logger.info("NATS consumer established")
        if on_connection_ready is not None:
            # start_consumer returns only after stream creation/reconciliation
            # and durable subscription have both completed.
            on_connection_ready(nc, connection_lost)
        if on_connected is not None:
            on_connected(nc)

        try:
            await connection_lost.wait()
        except asyncio.CancelledError:
            with suppress(Exception):
                await nc.close()
            raise

        if on_connection_lost is not None:
            on_connection_lost(nc)
        logger.warning("NATS consumer connection lost; restarting the subscription")
        with suppress(Exception):
            await nc.close()
        # A broker that accepts and immediately drops connections must not cause
        # a tight reconnect loop. Continue the same bounded backoff sequence used
        # for failed connection attempts.
        await asyncio.sleep(delay)
        delay = min(delay * 2, RECONNECT_MAX_DELAY)
