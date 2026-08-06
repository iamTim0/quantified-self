"""Transform calendar records to canonical ingestion events."""
import hashlib
from datetime import datetime, timezone
from typing import Any


def transform(records: list[dict[str, Any]], tenant_id: str, source_id: str) -> list[dict[str, Any]]:
    events=[]
    for record in records:
        timestamp=str(record.get("start") or datetime.now(timezone.utc).isoformat())
        metric=str(record.get("metric_type") or "calendar_busy_minutes")
        raw_value=record.get("duration_minutes", record.get("value"))
        try: value=float(raw_value)
        except (TypeError, ValueError): continue
        key=hashlib.sha256(f"{tenant_id}:{source_id}:{metric}:{timestamp}".encode()).hexdigest()
        events.append({"tenant_id":tenant_id,"source_id":source_id,"metric_type":metric,"timestamp":timestamp,"value":value,"metadata":{"source_type":"calendar"},"idempotency_key":key})
    return events
