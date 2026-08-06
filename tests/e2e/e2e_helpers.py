"""Isolated database setup and teardown helpers for E2E integration tests."""

import os
import uuid

from core.db.models import (
    ApiKey,
    Base,
    DataPoint,
    DataSource,
    ExplorerView,
    RefreshToken,
    RevokedAccessToken,
    SyncRun,
    Tenant,
    TenantShare,
    User,
)
from core.security.tokens import create_access_token, create_service_token
from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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

TEST_PASSWORD_HASH = "$2b$12$abcdefghijklmnopqrstuv0123456789012345678901234567890ab"


async def init_e2e_db():
    """Ensure database schema tables exist on test engine."""
    async with e2e_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def override_get_session():
    """FastAPI dependency override providing real PostgreSQL test session."""
    async with e2e_session_maker() as session:
        yield session


def owner_user_id(tenant_id: str) -> str:
    """Deterministic owner user id for a test tenant, so helpers need no lookup."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"owner:{tenant_id}"))


def auth_headers(tenant_id: str, role: str = "owner") -> dict[str, str]:
    """Bearer headers for a user principal of the given test tenant.

    Core derives the tenant from the token, so no X-Tenant-ID is sent.
    """
    token, _jti, _exp = create_access_token(
        user_id=owner_user_id(tenant_id),
        tenant_id=tenant_id,
        email=f"owner-{tenant_id}@example.test",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


def service_headers(tenant_id: str | None = None) -> dict[str, str]:
    """Bearer headers for an internal service principal (importer-style caller)."""
    headers = {"Authorization": f"Bearer {create_service_token('e2e-importer')}"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


async def create_test_tenant(session: AsyncSession | None = None) -> str:
    """Create a tenant plus its owner user, owned exclusively by the calling test."""
    tenant_id = str(uuid.uuid4())
    tenant = Tenant(id=tenant_id, name=f"Test E2E Tenant {tenant_id}")
    user = User(
        id=owner_user_id(tenant_id),
        tenant_id=tenant_id,
        email=f"owner-{tenant_id}@example.test",
        password_hash=TEST_PASSWORD_HASH,
        name="E2E Owner",
        role="owner",
    )
    if session is not None:
        session.add(tenant)
        session.add(user)
        await session.commit()
    else:
        async with e2e_session_maker() as s:
            s.add(tenant)
            s.add(user)
            await s.commit()
    return tenant_id


async def cleanup_test_tenant(tenant_id: str) -> None:
    """Remove every row created for an isolated test tenant.

    This was previously a `pass` stub, so every e2e run leaked tenants, data points
    and connectors into the development database (AGENTS.md rule 10).
    """
    async with e2e_session_maker() as session:
        await session.execute(
            delete(TenantShare).where(
                or_(
                    TenantShare.grantor_tenant_id == tenant_id,
                    TenantShare.grantee_tenant_id == tenant_id,
                )
            )
        )
        await session.execute(delete(SyncRun).where(SyncRun.tenant_id == tenant_id))
        await session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await session.execute(
            delete(RevokedAccessToken).where(RevokedAccessToken.tenant_id == tenant_id)
        )
        await session.execute(
            delete(RefreshToken).where(RefreshToken.tenant_id == tenant_id)
        )
        await session.execute(
            delete(ExplorerView).where(ExplorerView.tenant_id == tenant_id)
        )
        await session.execute(delete(DataPoint).where(DataPoint.tenant_id == tenant_id))
        await session.execute(delete(DataSource).where(DataSource.tenant_id == tenant_id))
        await session.execute(delete(User).where(User.tenant_id == tenant_id))
        await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await session.commit()
