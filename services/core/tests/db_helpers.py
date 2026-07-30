"""Isolated database setup and teardown helpers for Core integration tests."""

import uuid

from core.db.models import DataPoint, DataSource, Tenant, TenantShare, User
from core.db.session import async_session_maker
from sqlalchemy import delete, or_


async def create_test_tenant() -> str:
    """Create a tenant owned exclusively by the calling test."""
    tenant_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(Tenant(id=tenant_id, name=f"Test Tenant {tenant_id}"))
        await session.commit()
    return tenant_id


async def cleanup_test_tenant(tenant_id: str) -> None:
    """Remove every row created for an isolated test tenant."""
    async with async_session_maker() as session:
        await session.execute(
            delete(TenantShare).where(
                or_(
                    TenantShare.grantor_tenant_id == tenant_id,
                    TenantShare.grantee_tenant_id == tenant_id,
                )
            )
        )
        await session.execute(delete(DataPoint).where(DataPoint.tenant_id == tenant_id))
        await session.execute(delete(DataSource).where(DataSource.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()
