"""Integration tests for the session lifecycle: login, logout, refresh, revocation.

The reported bug was that a page refresh after logout logged the user back in.
The root cause was client-side (an automatic dev-token fetch), but the server had
no way to end a session either: there was no logout endpoint, no refresh token and
no revocation store, so an issued token stayed valid for its full 30 days.

These tests pin the server half of that contract.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- RevokedTokenRejected
- RefreshTokenSingleUse
"""

import uuid

import pytest
from core.db.models import RefreshToken, User
from core.db.session import async_session_maker
from core.main import app
from core.security.tokens import hash_token
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant

app.state.testing = True


async def _signup(ac: AsyncClient, email: str) -> dict:
    res = await ac.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "correct horse battery", "name": "Test Person"},
    )
    assert res.status_code == 200, res.text
    return res.json()


async def _tenant_of(email: str) -> str:
    async with async_session_maker() as session:
        res = await session.execute(select(User).where(User.email == email))
        user = res.scalars().first()
        return user.tenant_id


@pytest.mark.asyncio
async def test_signup_issues_access_and_refresh_tokens():
    """A new account gets both halves of a session."""
    email = f"signup-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            data = await _signup(ac, email)
        tenant_id = data["tenant_id"]

        assert data["access_token"]
        assert data["refresh_token"]
        assert data["expires_in"] > 0
        # The refresh token must be stored hashed, never in the clear.
        async with async_session_maker() as session:
            res = await session.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == hash_token(data["refresh_token"])
                )
            )
            assert res.scalars().first() is not None
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_logout_revokes_the_access_token():
    """After logout the same access token must be rejected.

    This is the server-side half of "refreshing the page must not log me back in".
    """
    email = f"logout-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            headers = {"Authorization": f"Bearer {data['access_token']}"}

            before = await ac.get("/api/v1/data/metrics/types", headers=headers)
            assert before.status_code == 200

            out = await ac.post(
                "/api/v1/auth/logout",
                headers=headers,
                json={"refresh_token": data["refresh_token"]},
            )
            assert out.status_code == 204

            after = await ac.get("/api/v1/data/metrics/types", headers=headers)
            assert after.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_logout_is_idempotent_and_tolerates_a_junk_token():
    """Logout must always succeed, and must not reveal whether the token was real."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        res = await ac.post(
            "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-token"}
        )
        assert res.status_code == 204

        res_no_header = await ac.post("/api/v1/auth/logout")
        assert res_no_header.status_code == 204


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_token_too():
    """A revoked refresh token must not be able to resurrect the session."""
    email = f"logout-refresh-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]

            await ac.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {data['access_token']}"},
                json={"refresh_token": data["refresh_token"]},
            )

            res = await ac.post(
                "/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}
            )
            assert res.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_refresh_rotates_and_old_token_is_single_use():
    """Refresh issues a new pair; replaying the old token kills the whole chain.

    Verifies Fizzbee Invariant: RefreshTokenSingleUse
    """
    email = f"rotate-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            first_refresh = data["refresh_token"]

            rotated = await ac.post(
                "/api/v1/auth/refresh", json={"refresh_token": first_refresh}
            )
            assert rotated.status_code == 200
            rotated_data = rotated.json()
            assert rotated_data["refresh_token"] != first_refresh

            # The new access token works.
            ok = await ac.get(
                "/api/v1/data/metrics/types",
                headers={"Authorization": f"Bearer {rotated_data['access_token']}"},
            )
            assert ok.status_code == 200

            # Replaying the consumed refresh token is refused...
            replay = await ac.post(
                "/api/v1/auth/refresh", json={"refresh_token": first_refresh}
            )
            assert replay.status_code == 401

            # ...and the replacement is revoked too, because a replay means the
            # chain is no longer trustworthy.
            after_replay = await ac.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": rotated_data["refresh_token"]},
            )
            assert after_replay.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_refresh_rejects_unknown_token():
    """An invented refresh token must not mint a session."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        res = await ac.post(
            "/api/v1/auth/refresh", json={"refresh_token": "definitely-not-issued-by-us"}
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_password_change_revokes_all_sessions():
    """Changing the password must not leave older sessions alive."""
    email = f"pwchange-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            headers = {"Authorization": f"Bearer {data['access_token']}"}

            changed = await ac.post(
                "/api/v1/auth/change-password",
                headers=headers,
                json={
                    "current_password": "correct horse battery",
                    "new_password": "a different long password",
                },
            )
            assert changed.status_code == 200
            assert changed.json()["sessions_revoked"] is True

            # The token used to make the change is itself revoked.
            after = await ac.get("/api/v1/data/metrics/types", headers=headers)
            assert after.status_code == 401

            # And the refresh token cannot be used to get a new one.
            refreshed = await ac.post(
                "/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}
            )
            assert refreshed.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_change_password_targets_the_calling_user_not_the_first_in_tenant():
    """The account is resolved by user_id from the token.

    The previous implementation selected the first user in the tenant, which in a
    workspace with more than one member changed somebody else's password.
    """
    email_a = f"multi-a-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            data = await _signup(ac, email_a)
            tenant_id = data["tenant_id"]

            # Add a second member to the same tenant, created before the request.
            second_id = str(uuid.uuid4())
            async with async_session_maker() as session:
                session.add(
                    User(
                        id=second_id,
                        tenant_id=tenant_id,
                        email=f"multi-b-{uuid.uuid4().hex[:8]}@example.test",
                        password_hash="$2b$12$notarealhashnotarealhashnotarealhashnotarealhash12",
                        name="Second Member",
                        role="member",
                    )
                )
                await session.commit()

            changed = await ac.post(
                "/api/v1/auth/change-password",
                headers={"Authorization": f"Bearer {data['access_token']}"},
                json={
                    "current_password": "correct horse battery",
                    "new_password": "yet another long password",
                },
            )
            assert changed.status_code == 200

            # The signer's password changed; the other member's did not.
            login = await ac.post(
                "/api/v1/auth/login",
                json={"email": email_a, "password": "yet another long password"},
            )
            assert login.status_code == 200

            async with async_session_maker() as session:
                res = await session.execute(select(User).where(User.id == second_id))
                other = res.scalars().first()
                assert other.password_hash.startswith("$2b$12$notarealhash")
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)
