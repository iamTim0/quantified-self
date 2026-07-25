import uuid
from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field, field_validator


class IngestEvent(BaseModel):
    """Event model representing data ingestion into the system."""
    
    tenant_id: str = Field(..., description="The unique identifier for the tenant")
    source_id: str = Field(..., description="The unique identifier for the source")
    metric_type: str = Field(..., description="Type of metric being recorded")
    timestamp: datetime = Field(..., description="When the event occurred")
    value: float = Field(..., description="The recorded value")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context or properties")
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


class IngestEventBatch(BaseModel):
    """A batch of ingestion events to be processed together."""
    
    events: list[IngestEvent] = Field(default_factory=list, description="List of ingest events")
