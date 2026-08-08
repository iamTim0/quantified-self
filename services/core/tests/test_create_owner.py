"""Creating the first account when self-registration is off.

`ALLOW_REGISTRATION` now defaults to False, which would otherwise leave a
deployment with no way in. This is that way in, and it is a command rather than
a startup step for a reason visible in this repository's own history:
`infra/db/init.sql` seeded an owner account with a bcrypt hash committed beside
it, so every clone shared one set of credentials for one real address.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
"""

import uuid

import pytest
from core.create_owner import BootstrapError, create_owner, read_password
from core.db.models import Tenant, User
from core.db.session import async_session_maker
from core.main import app, pwd_context
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

app.state.testing = True

PASSWORD = "a-sufficiently-long-password"


def unique_email() -> str:
    return f"owner-{uuid.uuid4().hex[:10]}@example.test"


async def drop_account(email: str) -> None:
    async with async_session_maker() as session:
        user = (
            await session.execute(
                select(User).where(func.lower(User.email) == email.lower())
            )
        ).scalars().first()
        tenant_id = user.tenant_id if user else None
    if tenant_id:
        from tests.db_helpers import cleanup_test_tenant

        await cleanup_test_tenant(tenant_id)


async def fetch(email: str) -> User | None:
    async with async_session_maker() as session:
        return (
            await session.execute(
                select(User).where(func.lower(User.email) == email.lower())
            )
        ).scalars().first()


@pytest.mark.asyncio
async def test_it_creates_an_owner_and_a_workspace():
    email = unique_email()
    try:
        message = await create_owner(
            email=email, name="Owner", workspace="Test Space",
            password=PASSWORD, reset=False,
        )
        assert email in message

        user = await fetch(email)
        assert user is not None
        assert user.role == "owner"
        # The password is stored hashed, and the hash verifies. A test that only
        # checked the row exists would pass on a column full of plaintext.
        assert user.password_hash != PASSWORD
        assert pwd_context.verify(PASSWORD, user.password_hash)

        async with async_session_maker() as session:
            tenant = (
                await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
            ).scalars().first()
        assert tenant is not None and tenant.name == "Test Space"
    finally:
        await drop_account(email)


def test_registration_is_closed_by_default():
    """Asserted on the declared default, not on the resolved value.

    `settings.ALLOW_REGISTRATION` reflects whatever `.env` says on the machine
    running the tests, so reading it would prove nothing about what a fresh
    deployment does.
    """
    from core.config import Settings

    assert Settings.model_fields["ALLOW_REGISTRATION"].default is False


@pytest.mark.asyncio
async def test_the_new_owner_can_sign_in_while_signup_is_closed(monkeypatch):
    """The whole point. An account nobody can use is not a way in."""
    from core.config import settings

    monkeypatch.setattr(settings, "ALLOW_REGISTRATION", False)

    email = unique_email()
    try:
        await create_owner(
            email=email, name="Owner", workspace="Test Space",
            password=PASSWORD, reset=False,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            signup = await ac.post(
                "/api/v1/auth/signup",
                json={"email": unique_email(), "password": PASSWORD, "name": "Nobody"},
            )
            login = await ac.post(
                "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
            )

        assert signup.status_code == 403, "self-registration must be refused"
        assert login.status_code == 200, "the bootstrapped account must still work"
    finally:
        await drop_account(email)


@pytest.mark.asyncio
async def test_running_it_twice_refuses_rather_than_overwrites():
    """Silently resetting somebody's password on a re-run would be a very bad
    way to find out the command is not idempotent."""
    email = unique_email()
    try:
        await create_owner(
            email=email, name="Owner", workspace="A", password=PASSWORD, reset=False
        )
        with pytest.raises(BootstrapError, match="already exists"):
            await create_owner(
                email=email, name="Owner", workspace="B",
                password="another-long-password", reset=False,
            )
        # And the original password still works.
        user = await fetch(email)
        assert pwd_context.verify(PASSWORD, user.password_hash)
    finally:
        await drop_account(email)


@pytest.mark.asyncio
async def test_an_existing_address_is_matched_regardless_of_case():
    email = unique_email()
    try:
        await create_owner(
            email=email, name="Owner", workspace="A", password=PASSWORD, reset=False
        )
        with pytest.raises(BootstrapError, match="already exists"):
            await create_owner(
                email=email.upper(), name="Owner", workspace="B",
                password=PASSWORD, reset=False,
            )
    finally:
        await drop_account(email)


@pytest.mark.asyncio
async def test_reset_changes_the_password_and_ends_every_session():
    email = unique_email()
    try:
        await create_owner(
            email=email, name="Owner", workspace="A", password=PASSWORD, reset=False
        )
        new_password = "a-completely-different-password"
        message = await create_owner(
            email=email, name="Owner", workspace="A",
            password=new_password, reset=True,
        )
        assert "reset" in message.lower()

        user = await fetch(email)
        assert pwd_context.verify(new_password, user.password_hash)
        assert not pwd_context.verify(PASSWORD, user.password_hash)
        # Resetting a password while leaving the old sessions usable would
        # defeat the reason for resetting it.
        assert user.sessions_valid_from is not None
    finally:
        await drop_account(email)


@pytest.mark.asyncio
async def test_reset_on_a_missing_account_is_an_error_not_a_creation():
    email = unique_email()
    with pytest.raises(BootstrapError, match="nothing to reset"):
        await create_owner(
            email=email, name="Owner", workspace="A", password=PASSWORD, reset=True
        )
    assert await fetch(email) is None


@pytest.mark.asyncio
async def test_a_malformed_address_is_refused_before_anything_is_written():
    with pytest.raises(BootstrapError, match="email address"):
        await create_owner(
            email="not-an-email", name="Owner", workspace="A",
            password=PASSWORD, reset=False,
        )
    async with async_session_maker() as session:
        leaked = (
            await session.execute(select(Tenant).where(Tenant.name == "A"))
        ).scalars().first()
    assert leaked is None, "the tenant must not be created before validation"


def test_a_short_password_is_refused(monkeypatch):
    """Twelve characters, not the signup form's six: this account is the whole
    way in, and it is created once by someone who can choose freely."""
    monkeypatch.setenv("QS_OWNER_PASSWORD", "short")
    with pytest.raises(BootstrapError, match="at least"):
        read_password(confirm=False)


def test_the_password_comes_from_the_environment_when_set(monkeypatch):
    monkeypatch.setenv("QS_OWNER_PASSWORD", PASSWORD)
    assert read_password(confirm=False) == PASSWORD


def test_the_password_is_never_an_argument(capsys):
    """Command lines land in shell history, `ps` output and CI logs.

    argparse exits 2 on an unrecognised flag, which is what makes `--password`
    unusable rather than merely undocumented.
    """
    from core.create_owner import main

    with pytest.raises(SystemExit) as exit_info:
        main(["--email", "owner@example.test", "--password", PASSWORD])

    assert exit_info.value.code == 2
    assert "--password" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_it_leaves_no_tenant_behind_when_the_user_insert_fails(monkeypatch):
    """A half-created workspace with no owner is unreachable and invisible."""
    email = unique_email()

    async with async_session_maker() as session:
        before = (
            await session.execute(select(func.count()).select_from(Tenant))
        ).scalar_one()

    def explode(*_a, **_k):
        raise RuntimeError("hashing failed")

    monkeypatch.setattr("core.main.pwd_context.hash", explode)
    with pytest.raises(RuntimeError):
        await create_owner(
            email=email, name="Owner", workspace="Orphan",
            password=PASSWORD, reset=False,
        )

    async with async_session_maker() as session:
        after = (
            await session.execute(select(func.count()).select_from(Tenant))
        ).scalar_one()
        await session.execute(delete(Tenant).where(Tenant.name == "Orphan"))
        await session.commit()

    assert after == before, "the tenant insert must not survive a later failure"
