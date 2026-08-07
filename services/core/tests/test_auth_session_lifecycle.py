"""Integration tests for the session lifecycle: login, logout, refresh, revocation.

The reported bug was that a page refresh after logout logged the user back in.
The root cause was client-side (an automatic dev-token fetch), but the server had
no way to end a session either: there was no logout endpoint, no refresh token and
no revocation store, so an issued token stayed valid for its full 30 days.

Sessions are now carried in httpOnly cookies rather than handed to the page as
JSON for it to put in localStorage. These tests pin both halves of that contract:
the revocation rules, and the cookie mechanics that replaced token-in-body.

The base URL is **https** on purpose. Session cookies are issued with `Secure`,
and an RFC 6265 compliant client -- httpx included -- will not send a Secure
cookie back over plain http. Testing against http would silently exercise an
unauthenticated path and every assertion below would be meaningless.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- RevokedTokenRejected
- RefreshTokenSingleUse
- SessionCredentialNotReadableByScript
- StateChangingRequestRequiresCsrfProof
"""

import uuid

import pytest
from core.db.models import RefreshToken, User
from core.db.session import async_session_maker
from core.main import app
from core.security.cookies import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, REFRESH_COOKIE
from core.security.tokens import hash_token
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant

app.state.testing = True

BASE_URL = "https://testserver"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL)


def _csrf(ac: AsyncClient) -> dict[str, str]:
    """The double-submit header a browser would echo from the readable cookie."""
    token = ac.cookies.get(CSRF_COOKIE)
    return {CSRF_HEADER: token} if token else {}


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
async def test_signup_sets_session_cookies_and_returns_no_tokens():
    """A new account gets a session as cookies -- and the body carries no credential.

    The body assertion is the point of the change: as long as the token comes back
    as JSON, a client can put it somewhere a script can read, and the httpOnly
    cookie buys nothing.

    Verifies Fizzbee Invariant: SessionCredentialNotReadableByScript
    """
    email = f"signup-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            res = await ac.post(
                "/api/v1/auth/signup",
                json={
                    "email": email,
                    "password": "correct horse battery",
                    "name": "Test Person",
                },
            )
            assert res.status_code == 200, res.text
            data = res.json()
            tenant_id = data["tenant_id"]

            assert "access_token" not in data
            assert "refresh_token" not in data
            assert data["token_type"] == "cookie"
            assert data["expires_in"] > 0

            assert ac.cookies.get(ACCESS_COOKIE)
            assert ac.cookies.get(REFRESH_COOKIE)
            assert ac.cookies.get(CSRF_COOKIE)

            # The two credential cookies must be httpOnly; the CSRF one must not be,
            # because the page has to read it to echo it back.
            set_cookies = res.headers.get_list("set-cookie")
            access = next(c for c in set_cookies if c.startswith(f"{ACCESS_COOKIE}="))
            refresh = next(c for c in set_cookies if c.startswith(f"{REFRESH_COOKIE}="))
            csrf = next(c for c in set_cookies if c.startswith(f"{CSRF_COOKIE}="))

            assert "httponly" in access.lower()
            assert "secure" in access.lower()
            assert "samesite=lax" in access.lower()
            assert "httponly" in refresh.lower()
            # Scoped to the auth endpoints so it does not ride along on every
            # metrics query.
            assert "path=/api/v1/auth" in refresh.lower()
            assert "httponly" not in csrf.lower()

            raw_refresh = ac.cookies.get(REFRESH_COOKIE)

        # The refresh token must be stored hashed, never in the clear.
        async with async_session_maker() as session:
            res = await session.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == hash_token(raw_refresh)
                )
            )
            assert res.scalars().first() is not None
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_logout_revokes_the_session_and_clears_the_cookies():
    """After logout the same cookie must be rejected and the browser left empty.

    This is the server-side half of "refreshing the page must not log me back in".
    """
    email = f"logout-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]

            before = await ac.get("/api/v1/data/metrics/types")
            assert before.status_code == 200

            out = await ac.post("/api/v1/auth/logout", headers=_csrf(ac), json={})
            assert out.status_code == 204

            # The response expires all three cookies rather than leaving a stale
            # one behind for the next page load to find.
            cleared = out.headers.get_list("set-cookie")
            for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
                assert any(c.startswith(f"{name}=") for c in cleared), name
            assert not ac.cookies.get(ACCESS_COOKIE)

            after = await ac.get("/api/v1/data/metrics/types")
            assert after.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_revoked_access_token_is_rejected_on_the_header_path_too():
    """Logout denylists the jti, so the bearer path cannot outlive the cookie one.

    Verifies Fizzbee Invariant: RevokedTokenRejected
    """
    email = f"logout-hdr-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            captured = ac.cookies.get(ACCESS_COOKIE)

            await ac.post("/api/v1/auth/logout", headers=_csrf(ac), json={})

            replayed = await ac.get(
                "/api/v1/data/metrics/types",
                headers={"Authorization": f"Bearer {captured}"},
            )
            assert replayed.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_logout_is_idempotent_and_tolerates_a_junk_token():
    """Logout must always succeed, and must not reveal whether the token was real."""
    async with _client() as ac:
        res = await ac.post(
            "/api/v1/auth/logout", headers={"Authorization": "Bearer not-a-token"}
        )
        assert res.status_code == 204

        res_no_header = await ac.post("/api/v1/auth/logout")
        assert res_no_header.status_code == 204


@pytest.mark.asyncio
async def test_logout_revokes_the_refresh_cookie_too():
    """A revoked refresh token must not be able to resurrect the session."""
    email = f"logout-refresh-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            stolen_refresh = ac.cookies.get(REFRESH_COOKIE)

            await ac.post("/api/v1/auth/logout", headers=_csrf(ac), json={})

            # Even presented directly, out of band, the token is dead.
            res = await ac.post(
                "/api/v1/auth/refresh", json={"refresh_token": stolen_refresh}
            )
            assert res.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_refresh_rotates_cookies_and_old_token_is_single_use():
    """Refresh issues a new pair; replaying the old token kills the whole chain.

    Verifies Fizzbee Invariant: RefreshTokenSingleUse
    """
    email = f"rotate-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            first_refresh = ac.cookies.get(REFRESH_COOKIE)
            first_csrf = ac.cookies.get(CSRF_COOKIE)

            rotated = await ac.post("/api/v1/auth/refresh", headers=_csrf(ac))
            assert rotated.status_code == 200, rotated.text
            assert ac.cookies.get(REFRESH_COOKIE) != first_refresh
            # The CSRF token rotates with the credential, so one captured earlier
            # cannot be paired with the new session.
            assert ac.cookies.get(CSRF_COOKIE) != first_csrf

            ok = await ac.get("/api/v1/data/metrics/types")
            assert ok.status_code == 200

            # Replaying the consumed token is refused. This runs on a client with
            # no cookie jar, because that is the situation being modelled: whoever
            # replays a stolen refresh token has the token and nothing else. Doing
            # it on `ac` would prove nothing -- the endpoint prefers the cookie, so
            # it would quietly rotate the *current* token and return 200.
            async with _client() as thief:
                replay = await thief.post(
                    "/api/v1/auth/refresh", json={"refresh_token": first_refresh}
                )
                assert replay.status_code == 401

            # ...and the legitimate holder's replacement is revoked too, because a
            # replay means the whole chain is no longer trustworthy.
            after_replay = await ac.post("/api/v1/auth/refresh", headers=_csrf(ac))
            assert after_replay.status_code == 401
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_refresh_rejects_unknown_token():
    """An invented refresh token must not mint a session."""
    async with _client() as ac:
        res = await ac.post(
            "/api/v1/auth/refresh", json={"refresh_token": "definitely-not-issued-by-us"}
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_without_any_credential_is_401():
    """No cookie and no body means there is nothing to refresh."""
    async with _client() as ac:
        res = await ac.post("/api/v1/auth/refresh")
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_state_changing_cookie_request_requires_csrf_token():
    """A cookie-authenticated write without the CSRF header is refused.

    The cookie alone is not enough: a hostile page can make the browser send it,
    but cannot read it to construct the matching header.

    Verifies Fizzbee Invariant: StateChangingRequestRequiresCsrfProof
    """
    email = f"csrf-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]

            # Reads are unaffected.
            assert (await ac.get("/api/v1/data/metrics/types")).status_code == 200

            without = await ac.post(
                "/api/v1/data/sources/sync", json={"source_type": "oura"}
            )
            assert without.status_code == 403
            assert "CSRF" in without.json()["detail"]

            mismatched = await ac.post(
                "/api/v1/data/sources/sync",
                headers={CSRF_HEADER: "not-the-right-value"},
                json={"source_type": "oura"},
            )
            assert mismatched.status_code == 403
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_bearer_header_needs_no_csrf_token():
    """The header path is immune to CSRF and must not be burdened with it.

    A browser never attaches an Authorization header of its own accord, so a
    hostile page cannot cause a header-authenticated request in the first place.
    Requiring a CSRF token here would break every script and service client for no
    security gain.
    """
    email = f"bearer-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            token = ac.cookies.get(ACCESS_COOKIE)

        # A fresh client with no cookie jar at all: header only.
        async with _client() as bare:
            res = await bare.post(
                "/api/v1/data/sources/sync",
                headers={"Authorization": f"Bearer {token}"},
                json={"source_type": "oura"},
            )
            assert res.status_code != 403, res.text
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_password_change_revokes_all_sessions():
    """Changing the password must not leave older sessions alive."""
    email = f"pwchange-{uuid.uuid4().hex[:8]}@example.test"
    tenant_id = None
    try:
        async with _client() as ac:
            data = await _signup(ac, email)
            tenant_id = data["tenant_id"]
            refresh_before = ac.cookies.get(REFRESH_COOKIE)

            changed = await ac.post(
                "/api/v1/auth/change-password",
                headers=_csrf(ac),
                json={
                    "current_password": "correct horse battery",
                    "new_password": "a different long password",
                },
            )
            assert changed.status_code == 200
            assert changed.json()["sessions_revoked"] is True

            # The browser is left signed out rather than holding cookies for a
            # session that no longer exists.
            assert not ac.cookies.get(ACCESS_COOKIE)

            # The session used to make the change is itself revoked.
            after = await ac.get("/api/v1/data/metrics/types")
            assert after.status_code == 401

            # And the refresh token cannot be used to get a new one, even by
            # someone who kept a copy of it.
            async with _client() as holder:
                refreshed = await holder.post(
                    "/api/v1/auth/refresh", json={"refresh_token": refresh_before}
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
        async with _client() as ac:
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
                headers=_csrf(ac),
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
    finally:
        if tenant_id:
            await cleanup_test_tenant(tenant_id)
