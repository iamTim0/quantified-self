"""Warnings the operator actually sees, rather than ones in a log they do not read.

Everything checked here was previously only discoverable in a startup log line, a
commit message or docs/operations.md. The platform now surfaces it in the
dashboard, which is the only place any of it has a chance of being acted on.

Two properties are load-bearing and both are easy to get backwards:

* Deployment warnings name *which* secret is weak, so they must not reach a
  plain member.
* The account warning is about the caller's own password and must reach them
  whatever their role.

Maps to Fizzbee Invariants:
- NoUnauthorizedAccess
- SecretMaskedInReadResponse
"""

import hashlib

import pytest
from core.db.models import User
from core.db.session import async_session_maker
from core.deployment_warnings import (
    PUBLISHED_PASSWORD_HASH_DIGESTS,
    deployment_warnings,
    password_hash_is_published,
)
from core.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from tests.db_helpers import (
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
    owner_user_id,
)

app.state.testing = True

STRONG = "MZ3q7Xk9vJ2wR8tLpN5cQaB1dY6sHfUg"


def clean(**overrides):
    kwargs = {
        "environment": "production",
        "jwt_secret": STRONG,
        "encryption_key": STRONG,
        "internal_secret": STRONG,
        "allow_registration": False,
        "cookie_secure": True,
    }
    kwargs.update(overrides)
    return deployment_warnings(**kwargs)


def codes(warnings) -> set[str]:
    return {w.code for w in warnings}


# ─── deployment warnings ─────────────────────────────────────


def test_a_properly_configured_deployment_warns_about_nothing():
    assert clean() == []


@pytest.mark.parametrize(
    ("field", "code"),
    [
        ("jwt_secret", "insecure_jwt_secret"),
        ("encryption_key", "insecure_encryption_key"),
    ],
)
def test_a_published_secret_is_reported(field, code):
    assert code in codes(clean(**{field: "dev-secret-key-quantified-self-2026"}))


def test_an_unset_secret_is_reported_too():
    assert "insecure_jwt_secret" in codes(clean(jwt_secret=""))


def test_an_unset_internal_secret_is_not_a_warning():
    """Empty means "derive it from JWT_SECRET", which is covered by its own
    warning. Reporting both would be one problem counted twice."""
    assert "insecure_internal_secret" not in codes(clean(internal_secret=""))


def test_open_registration_is_reported():
    assert "registration_open" in codes(clean(allow_registration=True))


def test_insecure_cookies_are_reported():
    assert "cookies_not_secure" in codes(clean(cookie_secure=False))


def test_the_environment_note_only_appears_alongside_a_real_problem():
    """On its own, a development environment is not a finding — it is the
    explanation for why the others did not stop startup."""
    assert "development_environment" not in codes(clean(environment="dev"))
    assert "development_environment" in codes(clean(environment="dev", jwt_secret=""))


def test_every_warning_says_what_to_do():
    """A warning without an action is a warning nobody acts on."""
    every = clean(
        environment="dev",
        jwt_secret="",
        encryption_key="",
        internal_secret="dev-secret-key-quantified-self-2026",
        allow_registration=True,
        cookie_secure=False,
    )
    assert len(every) == 6
    for w in every:
        assert w.action.strip(), f"{w.code} has no action"
        assert w.severity in {"critical", "warning", "info"}


def test_the_encryption_warning_does_not_just_say_change_it():
    """Setting a new ENCRYPTION_KEY without re-encrypting destroys every stored
    credential. A warning that omits the order would cause the damage."""
    warning = next(w for w in clean(encryption_key="") if w.code == "insecure_encryption_key")
    assert "rotate_encryption_key" in warning.action


def test_no_warning_discloses_a_secret_value():
    """They name the variable, never its content."""
    leaked = "dev-secret-key-quantified-self-2026"
    rendered = " ".join(
        f"{w.title} {w.detail} {w.action}"
        for w in clean(jwt_secret=leaked, internal_secret=leaked)
    )
    assert leaked not in rendered


# ─── the published-password check ────────────────────────────


def test_a_hash_whose_digest_is_recorded_is_recognised(monkeypatch):
    """Tests the mechanism, not the datum.

    An earlier version of this test rebuilt the real leaked hash from string
    fragments so that check_private_info.py would not spot it. That is evading a
    check I wrote three commits earlier, which is not better for being
    well-intentioned. Whether the recorded digest really is that hash was
    verified once, at a shell, and cannot be re-verified here without committing
    the hash — which is the entire thing being avoided.
    """
    import core.deployment_warnings as module

    stand_in = "$2b$12$" + "q" * 53
    monkeypatch.setattr(
        module,
        "PUBLISHED_PASSWORD_HASH_DIGESTS",
        frozenset({hashlib.sha256(stand_in.encode()).hexdigest()}),
    )
    assert module.password_hash_is_published(stand_in)
    assert not module.password_hash_is_published("$2b$12$" + "z" * 53)


def test_an_ordinary_hash_is_not_flagged():
    assert not password_hash_is_published("$2b$12$" + "z" * 53)
    assert not password_hash_is_published(None)
    assert not password_hash_is_published("")


def test_the_account_warning_tells_the_user_to_change_it_elsewhere_too(monkeypatch):
    """Password reuse is the reason this matters beyond this application."""
    import core.deployment_warnings as module

    stand_in = "$2b$12$" + "q" * 53
    monkeypatch.setattr(
        module,
        "PUBLISHED_PASSWORD_HASH_DIGESTS",
        frozenset({hashlib.sha256(stand_in.encode()).hexdigest()}),
    )
    warning = module.account_warnings(password_hash=stand_in)[0]
    assert warning.severity == "critical"
    assert "anderswo" in warning.action


# ─── the endpoint, and who sees what ─────────────────────────


def _publish_a_stand_in_hash(monkeypatch) -> str:
    """Record the digest of a throwaway hash, so no real one is needed."""
    import core.deployment_warnings as module

    stand_in = "$2b$12$" + "q" * 53
    monkeypatch.setattr(
        module,
        "PUBLISHED_PASSWORD_HASH_DIGESTS",
        frozenset({hashlib.sha256(stand_in.encode()).hexdigest()}),
    )
    return stand_in


async def get_warnings(tenant_id: str, role: str = "owner"):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as ac:
        response = await ac.get(
            "/api/v1/data/system/warnings", headers=auth_headers(tenant_id, role)
        )
    assert response.status_code == 200, response.text
    return {w["code"] for w in response.json()["warnings"]}


@pytest.mark.asyncio
async def test_an_owner_sees_deployment_warnings(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret-key-quantified-self-2026")
    tenant_id = await create_test_tenant()
    try:
        assert "insecure_jwt_secret" in await get_warnings(tenant_id, "owner")
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_member_does_not(monkeypatch):
    """The warnings name which secret is weak. That is a disclosure, small but
    real, and a member has nothing to do with it anyway."""
    from core.config import settings

    monkeypatch.setattr(settings, "JWT_SECRET", "dev-secret-key-quantified-self-2026")
    tenant_id = await create_test_tenant()
    try:
        assert await get_warnings(tenant_id, "member") == set()
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_member_does_see_their_own_password_warning(monkeypatch):
    """The one that must not be role-gated."""
    from core.config import settings

    monkeypatch.setattr(settings, "JWT_SECRET", STRONG)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", STRONG)
    stand_in = _publish_a_stand_in_hash(monkeypatch)
    tenant_id = await create_test_tenant()
    try:
        async with async_session_maker() as session:
            await session.execute(
                update(User)
                .where(User.id == owner_user_id(tenant_id))
                .values(password_hash=stand_in)
            )
            await session.commit()

        assert await get_warnings(tenant_id, "member") == {"password_published"}
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_healthy_deployment_returns_an_empty_list(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "JWT_SECRET", STRONG)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", STRONG)
    monkeypatch.setattr(settings, "INTERNAL_SERVICE_SECRET", STRONG)
    monkeypatch.setattr(settings, "ALLOW_REGISTRATION", False)
    monkeypatch.setattr(settings, "COOKIE_SECURE", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    tenant_id = await create_test_tenant()
    try:
        assert await get_warnings(tenant_id, "owner") == set()
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_endpoint_requires_a_session():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as ac:
        response = await ac.get("/api/v1/data/system/warnings")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_it_does_not_leak_across_tenants(monkeypatch):
    """The account warning must describe the caller, not whoever else is stored."""
    from core.config import settings

    monkeypatch.setattr(settings, "JWT_SECRET", STRONG)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", STRONG)
    stand_in = _publish_a_stand_in_hash(monkeypatch)
    exposed = await create_test_tenant()
    bystander = await create_test_tenant()
    try:
        async with async_session_maker() as session:
            await session.execute(
                update(User)
                .where(User.id == owner_user_id(exposed))
                .values(password_hash=stand_in)
            )
            await session.commit()

        assert "password_published" in await get_warnings(exposed, "owner")
        assert "password_published" not in await get_warnings(bystander, "owner")
    finally:
        await cleanup_test_tenant(exposed)
        await cleanup_test_tenant(bystander)


def test_the_digest_list_contains_no_bcrypt_hash():
    """The whole point of storing digests: rule 14 forbids committing a hash, and
    detecting a leaked hash must not mean republishing it."""
    for digest in PUBLISHED_PASSWORD_HASH_DIGESTS:
        assert not digest.startswith("$2")
        assert len(digest) == 64
        int(digest, 16)  # plain hex, not a hash of the wrong kind
