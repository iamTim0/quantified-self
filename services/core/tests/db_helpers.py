"""Isolated database setup and teardown helpers for Core integration tests.

Every helper here creates what it needs and removes it again; nothing assumes a
pre-seeded database (AGENTS.md rule 10).
"""

import uuid

from core.db.models import (
    ApiKey,
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
from core.db.session import async_session_maker
from core.security.tokens import create_access_token, create_service_token
from sqlalchemy import delete, or_

TEST_PASSWORD_HASH = "$2b$12$abcdefghijklmnopqrstuv0123456789012345678901234567890ab"


async def create_test_tenant() -> str:
    """Create a tenant plus its owner user, owned exclusively by the calling test."""
    tenant_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(Tenant(id=tenant_id, name=f"Test Tenant {tenant_id}"))
        session.add(
            User(
                id=owner_user_id(tenant_id),
                tenant_id=tenant_id,
                email=f"owner-{tenant_id}@example.test",
                password_hash=TEST_PASSWORD_HASH,
                name="Test Owner",
                role="owner",
            )
        )
        await session.commit()
    return tenant_id


def owner_user_id(tenant_id: str) -> str:
    """Deterministic owner user id for a test tenant, so helpers need no lookup."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"owner:{tenant_id}"))


def auth_headers(tenant_id: str, role: str = "owner") -> dict[str, str]:
    """Bearer headers for a user principal of the given test tenant.

    No ``X-Tenant-ID`` is sent: the tenant must be derivable from the token alone.
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
    headers = {"Authorization": f"Bearer {create_service_token('test-importer')}"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


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
