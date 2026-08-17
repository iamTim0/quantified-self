"""Parsing of the ``qs.task.sync.*`` payload published by Core.

Core decides the import window, because Core owns the sync history the decision
depends on (see ``core.ingest_planning``). The importer's job is to honour the
window it is given, falling back to a lookback only for older payloads that
predate this field.

Maps to Fizzbee Invariants:
- TenantIsolation
- NoDuplicateData
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 7


@dataclass(frozen=True)
class SyncTask:
    """One sync instruction from Core."""

    tenant_id: str
    source_type: str
    request_id: str
    #: Which connector instance to sync. A tenant may hold several of one type, so
    #: the type alone no longer says whose credential to fetch or which
    #: ``source_id`` to key the resulting points on. Optional only for a payload
    #: published by an older Core.
    source_id: str | None = None
    mode: str = "smart"
    sync_run_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None

    @property
    def is_force(self) -> bool:
        return self.mode == "force"


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Ignoring unparseable timestamp in sync task: %r", value)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_sync_task(payload: dict[str, Any]) -> SyncTask | None:
    """Build a SyncTask, or None when the payload is unusable.

    A payload without a tenant is dropped rather than defaulted: guessing a tenant
    is exactly the class of bug that lets one tenant's data land in another's.
    """
    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        return None

    return SyncTask(
        tenant_id=tenant_id,
        source_id=payload.get("source_id"),
        source_type=payload.get("source_type", "github"),
        request_id=payload.get("request_id") or "req_importer_task",
        mode=payload.get("mode") or "smart",
        sync_run_id=payload.get("sync_run_id"),
        window_start=_parse_dt(payload.get("window_start")),
        window_end=_parse_dt(payload.get("window_end")),
    )


def resolve_window(
    task: SyncTask,
    config: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """The window to actually request from the upstream API.

    Prefers the window Core computed. Falls back to the connector's configured
    lookback so an older Core, or a replayed message, still does something sane.
    """
    now = now or datetime.now(timezone.utc)
    config = config or {}

    end = task.window_end or now
    if task.window_start:
        return task.window_start, end

    raw_hours = config.get("lookback_hours")
    if raw_hours is not None:
        try:
            return end - timedelta(hours=max(1.0, float(raw_hours))), end
        except (TypeError, ValueError):
            pass
    lookback = int(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS) or DEFAULT_LOOKBACK_DAYS)
    return end - timedelta(days=max(1, lookback)), end
