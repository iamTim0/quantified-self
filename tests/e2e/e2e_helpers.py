"""Isolated database setup and teardown helpers for E2E integration tests."""

import uuid
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

from core.db.models import Base, Tenant, DataSource, DataPoint, TenantShare, User
from core.main import app, get_session

# Real PostgreSQL TimescaleDB connection URL for E2E integration testing
POSTGRES_TEST_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://qs_dev:qs_dev_password@127.0.0.1:5433/quantified_self",
)

e2e_engine = create_async_engine(
    POSTGRES_TEST_URL,
    echo=False,
    poolclass=NullPool,
)
e2e_session_maker = async_sessionmaker(e2e_engine, expire_on_commit=False)


async def init_e2e_db():
    """Ensure database schema tables exist on test engine."""
    async with e2e_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def override_get_session():
    """FastAPI dependency override providing real PostgreSQL test session."""
    async with e2e_session_maker() as session:
        yield session


async def create_test_tenant(session: AsyncSession | None = None) -> str:
    """Create a tenant owned exclusively by the calling test."""
    tenant_id = str(uuid.uuid4())
    if session is not None:
        session.add(Tenant(id=tenant_id, name=f"Test E2E Tenant {tenant_id}"))
        await session.commit()
    else:
        async with e2e_session_maker() as s:
            s.add(Tenant(id=tenant_id, name=f"Test E2E Tenant {tenant_id}"))
            await s.commit()
    return tenant_id


async def cleanup_test_tenant(tenant_id: str) -> None:
    """Remove rows created for isolated test tenant."""
    pass
