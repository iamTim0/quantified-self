"""Tests for self-service account and workspace profile changes.

The endpoint updates the authenticated user's row and the authenticated tenant's
workspace row together, never a row selected from a caller-supplied tenant id.

Maps to Fizzbee Invariants:
- TenantIsolation
- UnauthenticatedRequestsBlocked
- NoUnauthorizedAccess
"""

import uuid

import pytest
from core.db.models import Tenant, User
from core.db.session import async_session_maker
from core.main import app
from core.security.tokens import create_access_token
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import (
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
    owner_user_id,
)

app.state.testing = True


@pytest.mark.asyncio
async def test_owner_can_update_identity_and_workspace_name():
    """The authenticated owner can change their own profile and workspace label.

    Verifies Fizzbee Invariant: TenantIsolation.
    """
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)
    new_email = f"updated-{uuid.uuid4().hex[:8]}@example.test"

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as client:
            response = await client.put(
                "/api/v1/auth/me",
                headers=headers,
                json={
                    "name": "Updated Owner",
                    "email": new_email,
                    "workspace_name": "Updated Workspace",
                },
            )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["name"] == "Updated Owner"
        assert payload["email"] == new_email
        assert payload["workspace_name"] == "Updated Workspace"
        assert payload["session_refreshed"] is True
        assert "access_token" not in payload

        async with async_session_maker() as session:
            user = (
                await session.execute(
                    select(User).where(
                        User.id == owner_user_id(tenant_id),
                        User.tenant_id == tenant_id,
                    )
                )
            ).scalars().one()
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            ).scalars().one()

        assert user.email == new_email
        assert user.name == "Updated Owner"
        assert tenant.name == "Updated Workspace"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_member_cannot_rename_workspace():
    """A member may edit their identity but not the shared workspace label.

    Verifies Fizzbee Invariant: NoUnauthorizedAccess.
    """
    tenant_id = await create_test_tenant()
    member_id = str(uuid.uuid4())
    member_email = f"member-{uuid.uuid4().hex[:8]}@example.test"
    async with async_session_maker() as session:
        session.add(
            User(
                id=member_id,
                tenant_id=tenant_id,
                email=member_email,
                password_hash="!test-only",
                name="Member",
                role="member",
            )
        )
        await session.commit()

    token, _jti, _expires = create_access_token(
        user_id=member_id,
        tenant_id=tenant_id,
        email=member_email,
        role="member",
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as client:
            response = await client.put(
                "/api/v1/auth/me",
                headers=headers,
                json={"workspace_name": "Must Not Change"},
            )

        assert response.status_code == 403
        async with async_session_maker() as session:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            ).scalars().one()
        assert tenant.name != "Must Not Change"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_email_change_rejects_another_tenant_account():
    """The global sign-in address remains unique regardless of tenant.

    Verifies Fizzbee Invariant: TenantIsolation.
    """
    first_tenant = await create_test_tenant()
    second_tenant = await create_test_tenant()
    async with async_session_maker() as session:
        target_email = (
            await session.execute(
                select(User.email).where(User.tenant_id == second_tenant)
            )
        ).scalar_one()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as client:
            response = await client.put(
                "/api/v1/auth/me",
                headers=auth_headers(first_tenant),
                json={"email": target_email.upper()},
            )

        assert response.status_code == 409
    finally:
        await cleanup_test_tenant(first_tenant)
        await cleanup_test_tenant(second_tenant)
