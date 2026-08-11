import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .metrics import UnknownMetricTypeError, canonical_metric_type


def idempotency_key(
    tenant_id: str,
    source_id: str,
    metric_type: str,
    timestamp: str | datetime,
) -> str:
    """``SHA256(tenant_id:source_id:metric_type:timestamp)`` — AGENTS.md rule 4.

    One definition, because this hash *is* the exact-once guarantee. It was written out
    nine times: once in each of the eight importers' transformers and once inline in
    Core's batch-import endpoint, as ``__import__("hashlib").sha256(...)``. All nine
    happened to agree, and nothing in the repository checked that they did — so a
    typo in one importer's separator would have cost that source its deduplication
    silently. Duplicates are not an error anywhere: Core inserts
    ``ON CONFLICT DO NOTHING``, so a key that no longer matches the stored one simply
    inserts a second row, and the only symptom is a metric that slowly doubles.

    ``timestamp`` takes a string or a ``datetime``, because the importers already hold a
    formatted ISO string while Core holds a converted ``datetime``. A ``datetime`` is
    converted to UTC first, so an offset-aware value and its UTC equivalent agree.

    **A string is hashed exactly as given, and that is deliberate.** It would be easy to
    parse and re-emit it so that ``…T00:00:00Z`` and ``…T00:00:00+00:00`` — the two
    spellings the importers actually use, Dawarich and Yazio the first, the rest the
    second — converged on one key. Doing that would silently re-key every point those two
    sources have already stored: the next import would derive a key matching nothing, and
    ``ON CONFLICT DO NOTHING`` does not fail, it inserts. One quiet re-key would double
    the history it was meant to protect.

    So each source stays self-consistent, which is what deduplication needs, and the
    consequence is written down instead: the *same* reading written by an importer and
    re-imported through Core's manual path can land twice, because the two paths spell the
    timestamp differently. Converging them is a migration — re-derive the stored keys in
    one transaction — not a change to this function.

    The metric name must be canonical *before* it gets here, which is why this does not
    canonicalise for you: the name is part of the hash, so resolving it afterwards keys
    the point under a name it is not stored under. ``IngestEvent`` rejects an alias for
    the same reason.
    """
    if isinstance(timestamp, datetime):
        moment = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        stamp = moment.astimezone(timezone.utc).isoformat()
    else:
        stamp = timestamp

    raw = f"{tenant_id}:{source_id}:{metric_type}:{stamp}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class IngestEvent(BaseModel):
    """Event model representing data ingestion into the system."""
    
    tenant_id: str = Field(..., description="The unique identifier for the tenant")
    source_id: str = Field(..., description="The unique identifier for the source")
    metric_type: str = Field(..., description="Type of metric being recorded")
    timestamp: datetime = Field(..., description="When the event occurred")
    value: float = Field(..., description="The recorded value")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional context or properties")
    idempotency_key: str = Field(..., description="Key to prevent duplicate processing")
    #: Stable identity of a child item when several provider records share one
    #: connector. It is still scoped to ``source_id`` by Core before hashing.
    idempotency_source_id: str | None = Field(
        None, description="Stable child identity used for idempotency when needed"
    )
    source_type: str = Field(..., description="Type of source (e.g., 'oura', 'whoop')")

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("tenant_id must be a valid UUID")
        return v

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("idempotency_key cannot be empty")
        return v

    @field_validator("metric_type")
    @classmethod
    def validate_metric_type_is_canonical(cls, v: str) -> str:
        """Reject anything the metric registry does not recognise as canonical.

        Strict on purpose, including for aliases: the idempotency key is derived from
        the metric name before the event is built, so silently rewriting an alias here
        would store the point under a name its key does not describe. A transformer
        resolves the name itself via ``canonical_metric_type`` and then hashes it.
        """
        try:
            canonical = canonical_metric_type(v)
        except UnknownMetricTypeError as exc:
            raise ValueError(str(exc)) from None
        if canonical != v.strip():
            raise ValueError(
                f"metric_type {v!r} is a legacy alias of {canonical!r}; call "
                "shared_schemas.canonical_metric_type() before deriving the "
                "idempotency key and emit the canonical name"
            )
        return canonical
