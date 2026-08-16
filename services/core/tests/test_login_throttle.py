"""The sign-in endpoint refuses a caller that keeps guessing, and says nothing extra.

Two defects are pinned here, and they interact — which is why they are in one
file rather than two.

The first is that nothing counted failed attempts at all: no lockout, no backoff,
no middleware at the edge. bcrypt slowed a credential-stuffing run down; it did
not stop one.

The second is that `if not user or not verify(...)` short-circuits, so an unknown
address never reached bcrypt and came back in microseconds while a known one took
a few hundred milliseconds. That told an attacker which addresses were real.

The interaction is the part worth testing deliberately: a throttle that engaged
only for accounts that exist would *reintroduce* the enumeration oracle through
the status code, having just closed it through timing. So the counter keys on the
address as submitted, and a nonexistent address gets throttled exactly like a
real one.

Every test creates its own tenant and cleans up after itself (rule 10), and each
uses a unique email so the per-account bucket of one test cannot influence
another.
"""

import uuid

import pytest
from core.db.models import LoginAttempt
from core.db.session import async_session_maker
from core.main import app
from core.security import login_throttle
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from tests.db_helpers import cleanup_test_tenant

app.state.testing = True

BASE_URL = "https://testserver"
PASSWORD = "correct horse battery staple"


def _client(client_ip: str | None = None) -> AsyncClient:
    """A client that presents the header the Gateway would set, if asked to."""
    headers = {login_throttle.CLIENT_IP_HEADER: client_ip} if client_ip else {}
    return AsyncClient(
        transport=ASGITransport(app=app), base_url=BASE_URL, headers=headers
    )


def _email() -> str:
    return f"throttle-{uuid.uuid4().hex[:12]}@example.com"


async def _signup(ac: AsyncClient, email: str) -> None:
    res = await ac.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": PASSWORD, "name": "Test Person"},
    )
    assert res.status_code == 200, res.text


async def _tenant_of(email: str) -> str | None:
    from core.db.models import User

    async with async_session_maker() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalars().first()
        return user.tenant_id if user else None


async def _forget(email: str, *addresses: str) -> None:
    """Drop this test's counters so a shared database does not couple tests."""
    async with async_session_maker() as session:
        await login_throttle.clear_account(session, email=email)
        for address in addresses:
            await session.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.scope == login_throttle.SCOPE_CLIENT,
                    LoginAttempt.scope_key == login_throttle._digest(address),
                )
            )
        await session.commit()


# ── The throttle ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_account_bucket_refuses_after_its_ceiling():
    """Ten wrong passwords against one address, and the eleventh is not answered."""
    email = _email()
    address = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
    async with _client(address) as ac:
        await _signup(ac, email)
        tenant_id = await _tenant_of(email)
        try:
            for attempt in range(login_throttle.MAX_PER_ACCOUNT):
                res = await ac.post(
                    "/api/v1/auth/login", json={"email": email, "password": "wrong"}
                )
                assert res.status_code == 401, f"attempt {attempt} should be a plain refusal"

            refused = await ac.post(
                "/api/v1/auth/login", json={"email": email, "password": "wrong"}
            )
            assert refused.status_code == 429
            assert refused.json()["detail"]["code"] == login_throttle.THROTTLED_CODE
            # A client needs to know when to come back, not just that it was refused.
            assert int(refused.headers["Retry-After"]) > 0
        finally:
            await _forget(email, address)
            if tenant_id:
                await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_right_password_is_refused_too_once_throttled():
    """The lockout is on the attempt, not on the guess.

    A throttle that still let the correct password through would be no throttle:
    the correct password is precisely what an attacker is looking for.
    """
    email = _email()
    address = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
    async with _client(address) as ac:
        await _signup(ac, email)
        tenant_id = await _tenant_of(email)
        try:
            for _ in range(login_throttle.MAX_PER_ACCOUNT):
                await ac.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})

            res = await ac.post(
                "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
            )
            assert res.status_code == 429
        finally:
            await _forget(email, address)
            if tenant_id:
                await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_signing_in_successfully_clears_the_account():
    """Otherwise somebody using six devices locks themselves out of their own data."""
    email = _email()
    address = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
    async with _client(address) as ac:
        await _signup(ac, email)
        tenant_id = await _tenant_of(email)
        try:
            for _ in range(login_throttle.MAX_PER_ACCOUNT - 1):
                await ac.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})

            good = await ac.post(
                "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
            )
            assert good.status_code == 200

            async with async_session_maker() as session:
                remaining = (
                    await session.execute(
                        select(LoginAttempt).where(
                            LoginAttempt.scope == login_throttle.SCOPE_ACCOUNT,
                            LoginAttempt.scope_key == login_throttle._digest(email),
                        )
                    )
                ).scalars().all()
            assert remaining == [], "a correct password forgives the earlier typos"
        finally:
            await _forget(email, address)
            if tenant_id:
                await cleanup_test_tenant(tenant_id)


# ── The enumeration oracle ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_address_that_does_not_exist_is_throttled_the_same_way():
    """The status code must not become the oracle the timing stopped being.

    If only real accounts could be throttled, a 429 would mean "this address is
    registered" — the exact question the dummy-hash verify was added to stop
    answering.
    """
    unknown = _email()
    address = f"203.0.113.{uuid.uuid4().int % 200 + 1}"
    async with _client(address) as ac:
        try:
            for _ in range(login_throttle.MAX_PER_ACCOUNT):
                res = await ac.post(
                    "/api/v1/auth/login", json={"email": unknown, "password": "wrong"}
                )
                assert res.status_code == 401

            refused = await ac.post(
                "/api/v1/auth/login", json={"email": unknown, "password": "wrong"}
            )
            assert refused.status_code == 429, "a nonexistent address throttles too"
        finally:
            await _forget(unknown, address)


@pytest.mark.asyncio
async def test_both_answers_are_byte_identical():
    """A wrong password and an unknown address say the same thing, exactly."""
    email = _email()
    unknown = _email()
    async with _client() as ac:
        await _signup(ac, email)
        tenant_id = await _tenant_of(email)
        try:
            real = await ac.post(
                "/api/v1/auth/login", json={"email": email, "password": "wrong"}
            )
            fake = await ac.post(
                "/api/v1/auth/login", json={"email": unknown, "password": "wrong"}
            )
            assert real.status_code == fake.status_code == 401
            assert real.json() == fake.json()
        finally:
            await _forget(email)
            await _forget(unknown)
            if tenant_id:
                await cleanup_test_tenant(tenant_id)


def test_a_missing_account_still_pays_for_a_password_check():
    """The structural half of the timing fix, asserted where it cannot flake.

    A wall-clock comparison would be a flaky test on shared CI, so this pins the
    thing that makes the timing equal instead: a dummy hash exists, it is a real
    bcrypt hash, and no password verifies against it.
    """
    from core.main import _DUMMY_PASSWORD_HASH, pwd_context

    assert _DUMMY_PASSWORD_HASH.startswith("$2"), "a real bcrypt hash, not a placeholder"
    assert not pwd_context.verify("wrong", _DUMMY_PASSWORD_HASH)
    assert not pwd_context.verify(PASSWORD, _DUMMY_PASSWORD_HASH)


# ── What is stored ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_address_is_stored_in_the_clear():
    """The counter holds digests. In plain text it would be a more sensitive
    record than the thing it protects — every address anyone tried to sign in as."""
    email = _email()
    address = f"203.0.113.{uuid.uuid4().int % 200 + 1}"
    async with _client(address) as ac:
        try:
            await ac.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})

            async with async_session_maker() as session:
                rows = (await session.execute(select(LoginAttempt))).scalars().all()
            stored = {row.scope_key for row in rows}

            assert email not in stored
            assert address not in stored
            assert login_throttle._digest(email) in stored
            assert login_throttle._digest(address) in stored
            assert all(len(key) == 64 for key in stored), "sha256 hex"
        finally:
            await _forget(email, address)


@pytest.mark.asyncio
async def test_a_request_with_no_forwarded_address_still_counts_the_account():
    """No client bucket rather than a shared one.

    Lumping every address-less request under one key would let the first caller
    to exhaust it lock out all the others. The account ceiling does not depend on
    the network and still applies.
    """
    email = _email()
    async with _client() as ac:
        try:
            await ac.post("/api/v1/auth/login", json={"email": email, "password": "wrong"})

            async with async_session_maker() as session:
                scopes = {
                    row.scope
                    for row in (await session.execute(select(LoginAttempt))).scalars().all()
                    if row.scope_key == login_throttle._digest(email)
                }
            assert scopes == {login_throttle.SCOPE_ACCOUNT}
        finally:
            await _forget(email)
