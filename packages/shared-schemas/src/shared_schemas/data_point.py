from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DataPointRead(BaseModel):
    """Model representing a DataPoint in API responses."""
    
    id: str = Field(..., description="Unique identifier for the data point")
    tenant_id: str = Field(..., description="The unique identifier for the tenant")
    source_id: str = Field(..., description="The unique identifier for the source")
    metric_type: str = Field(..., description="Type of metric being recorded")
    timestamp: datetime = Field(..., description="When the event occurred")
    value: float = Field(..., description="The recorded value")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context or properties")
    idempotency_key: str = Field(..., description="Key to prevent duplicate processing")
    created_at: datetime = Field(..., description="When this record was created in the database")


class DataPointQuery(BaseModel):
    """Model representing query parameters for fetching data points."""
    
    tenant_id: str = Field(..., description="The unique identifier for the tenant")
    start_time: datetime = Field(..., description="Start of the time range (inclusive)")
    end_time: datetime = Field(..., description="End of the time range (inclusive)")
    metric_type: Optional[str] = Field(None, description="Optional metric type to filter by")
    source_id: Optional[str] = Field(None, description="Optional source ID to filter by")
