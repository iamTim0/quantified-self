import uuid
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class TenantContext(BaseModel):
    """Context holding the current tenant information."""
    
    tenant_id: str = Field(..., description="The unique identifier for the tenant")

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id_uuid(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("tenant_id must be a valid UUID")
        return v


class ShareScope(str, Enum):
    """Scope of access granted between tenants."""
    
    READ_ALL = "READ_ALL"
    READ_METRIC = "READ_METRIC"


class TenantShareGrant(BaseModel):
    """Represents a data sharing agreement between two tenants."""
    
    grantor_tenant_id: str = Field(..., description="Tenant granting access")
    grantee_tenant_id: str = Field(..., description="Tenant receiving access")
    scope: str = Field(..., description="Scope of the grant (e.g., READ_ALL, READ_METRIC:metric_name)")
