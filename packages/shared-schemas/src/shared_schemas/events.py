import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .metrics import UnknownMetricTypeError, canonical_metric_type


class IngestEvent(BaseModel):
    """Event model representing data ingestion into the system."""
    
    tenant_id: str = Field(..., description="The unique identifier for the tenant")
    source_id: str = Field(..., description="The unique identifier for the source")
    metric_type: str = Field(..., description="Type of metric being recorded")
    timestamp: datetime = Field(..., description="When the event occurred")
    value: float = Field(..., description="The recorded value")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional context or properties")
    idempotency_key: str = Field(..., description="Key to prevent duplicate processing")
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


class IngestEventBatch(BaseModel):
    """A batch of ingestion events to be processed together."""
    
    events: list[IngestEvent] = Field(default_factory=list, description="List of ingest events")
