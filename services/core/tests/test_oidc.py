"""Tests for the OIDC Authorization Code + PKCE flow.

The security of this feature lives almost entirely in what it *refuses*, so most of
these are negative cases: a replayed state, a wrong nonce, a foreign issuer or
audience, an unverified email, and — the one that matters most — an existing local
account with the same email address, which must never be auto-adopted.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantIsolation
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from core.db.models import OidcAuthRequest, OidcProvider, User, UserIdentity
from core.db.session import async_session_maker
from core.main import app
from core.security import oidc as oidc_module
from core.security.cookies import ACCESS_COOKIE
from core.security.crypto import encrypt_secret
from core.security.oidc import (
    OidcError,
    apply_claims_mapping,
    build_authorization_request,
    generate_pkce_pair,
    is_redirect_uri_allowed,
    verify_id_token,
)
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

ISSUER = "https://idp.example.test"
CLIENT_ID = "qs-client-id"
REDIRECT = "https://app.example.test/auth/callback"

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
}

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_id_token(**overrides) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "provider-subject-123",
        "email": "person@example.test",
        "email_verified": True,
        "name": "Test Person",
        "nonce": "expected-nonce",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, _KEY, algorithm="RS256")


@pytest.fixture(autouse=True)
def stub_provider_network(monkeypatch):
    """Serve discovery and the signing key locally; no network in tests."""
    oidc_module.clear_discovery_cache()

    async def fake_discovery(issuer: str):
        return DISCOVERY

    class _Key:
        key = _KEY.public_key()

    class _JwkClient:
        def __init__(self, *a, **kw):
            pass

        def get_signing_key_from_jwt(self, token):
            return _Key()

    monkeypatch.setattr(oidc_module, "fetch_discovery", fake_discovery)
    monkeypatch.setattr("core.main.fetch_discovery", fake_discovery)
    monkeypatch.setattr(oidc_module, "PyJWKClient", _JwkClient)
    yield
    oidc_module.clear_discovery_cache()


async def create_provider(**overrides) -> str:
    """Insert a test provider. Any field may be overridden by the caller."""
    fields: dict = {
        "slug": f"idp-{uuid.uuid4().hex[:6]}",
        "display_name": "Test IdP",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "encrypted_client_secret": encrypt_secret("client-secret"),
        "redirect_uri": REDIRECT,
        "enabled": True,
        "allow_signup": True,
        "claims_mapping": {},
    }
    fields.update(overrides)

    async with async_session_maker() as session:
        session.add(OidcProvider(**fields))
        await session.commit()
    return fields["slug"]


async def drop_provider(slug: str) -> None:
    async with async_session_maker() as session:
        await session.execute(delete(OidcAuthRequest).where(OidcAuthRequest.provider_slug == slug))
        await session.execute(delete(OidcProvider).where(OidcProvider.slug == slug))
        await session.commit()


async def cleanup_user_by_email(email: str) -> None:
    """Remove an account created by an OIDC signup.

    The lookup session is closed before deleting: holding an open transaction
    while a second session deletes the same rows deadlocks against its own locks.
    """
    async with async_session_maker() as session:
        res = await session.execute(select(User).where(User.email == email))
        user = res.scalars().first()
        tenant_id = user.tenant_id if user else None

    if tenant_id:
        # cleanup_test_tenant removes user_identities too.
        await cleanup_test_tenant(tenant_id)


# ─── pure helpers ────────────────────────────────────────────


def test_pkce_challenge_is_the_s256_of_the_verifier():
    import base64
    import hashlib

    verifier, challenge = generate_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert challenge == expected
    assert "=" not in challenge


def test_pkce_pairs_are_unique():
    assert generate_pkce_pair()[0] != generate_pkce_pair()[0]


def test_authorization_url_carries_pkce_and_state():
    req = build_authorization_request(
        discovery=DISCOVERY, client_id=CLIENT_ID, redirect_uri=REDIRECT, scopes="openid email"
    )
    assert "code_challenge_method=S256" in req.authorization_url
    assert "response_type=code" in req.authorization_url
    assert req.state in req.authorization_url
    assert req.nonce in req.authorization_url
    # The verifier is the secret half; it must not be in the URL.
    assert req.code_verifier not in req.authorization_url


def test_redirect_uri_matching_is_exact():
    """Prefix matching here is how open redirects ship."""
    assert is_redirect_uri_allowed(REDIRECT, REDIRECT)
    assert not is_redirect_uri_allowed(f"{REDIRECT}.evil.test", REDIRECT)
    assert not is_redirect_uri_allowed("https://app.example.test.evil.test/cb", REDIRECT)
    assert not is_redirect_uri_allowed(f"{REDIRECT}/../x", REDIRECT)


def test_claims_mapping_reads_provider_specific_names():
    identity = oidc_module.VerifiedIdentity(
        subject="s", email=None, email_verified=False, name=None,
        raw_claims={"sub": "s", "mail": "a@b.test", "verified": True, "display": "A B"},
    )
    mapped = apply_claims_mapping(
        identity, {"email": "mail", "email_verified": "verified", "name": "display"}
    )
    assert mapped.email == "a@b.test"
    assert mapped.email_verified is True
    assert mapped.name == "A B"


# ─── id_token validation ─────────────────────────────────────


def test_valid_id_token_is_accepted():
    identity = verify_id_token(
        id_token=make_id_token(),
        discovery=DISCOVERY,
        client_id=CLIENT_ID,
        issuer=ISSUER,
        expected_nonce="expected-nonce",
    )
    assert identity.subject == "provider-subject-123"
    assert identity.email_verified is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"iss": "https://evil.example.test"}, "foreign issuer"),
        ({"aud": "some-other-client"}, "audience for another app"),
        ({"nonce": "different-nonce"}, "nonce from another request"),
        ({"exp": datetime.now(timezone.utc) - timedelta(minutes=5)}, "expired"),
    ],
)
def test_id_token_is_rejected(overrides, reason):
    with pytest.raises(OidcError):
        verify_id_token(
            id_token=make_id_token(**overrides),
            discovery=DISCOVERY,
            client_id=CLIENT_ID,
            issuer=ISSUER,
            expected_nonce="expected-nonce",
        )


def test_unsigned_token_is_rejected():
    """alg:none must never be accepted."""
    token = jwt.encode(
        {"iss": ISSUER, "aud": CLIENT_ID, "sub": "x", "nonce": "expected-nonce",
         "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        key="",
        algorithm="none",
    )
    with pytest.raises(OidcError):
        verify_id_token(
            id_token=token, discovery=DISCOVERY, client_id=CLIENT_ID,
            issuer=ISSUER, expected_nonce="expected-nonce",
        )


# ─── endpoints ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_only_enabled_providers_are_listed():
    enabled = await create_provider()
    disabled = await create_provider(enabled=False)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.get("/api/v1/auth/oidc/providers")

        slugs = [p["slug"] for p in res.json()["providers"]]
        assert enabled in slugs
        assert disabled not in slugs
        # No secret material, not even masked.
        assert "client_secret" not in res.text
    finally:
        await drop_provider(enabled)
        await drop_provider(disabled)


@pytest.mark.asyncio
async def test_provider_listing_needs_no_session():
    """Login buttons must render before anyone is signed in."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        assert (await ac.get("/api/v1/auth/oidc/providers")).status_code == 200


@pytest.mark.asyncio
async def test_start_stores_state_serverside_and_returns_a_url():
    slug = await create_provider()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(f"/api/v1/auth/oidc/{slug}/start", json={})

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["authorization_url"].startswith(f"{ISSUER}/authorize")

        async with async_session_maker() as session:
            stored = (
                await session.execute(
                    select(OidcAuthRequest).where(OidcAuthRequest.state == body["state"])
                )
            ).scalars().first()
        assert stored is not None
        # The verifier stays on the server; the response must not leak it.
        assert stored.code_verifier not in res.text
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_start_rejects_a_foreign_redirect_uri():
    slug = await create_provider()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/start",
                json={"redirect_uri": "https://evil.test/steal"},
            )
        assert res.status_code == 400
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_unknown_and_disabled_providers_answer_identically():
    disabled = await create_provider(enabled=False)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            unknown = await ac.post("/api/v1/auth/oidc/does-not-exist/start", json={})
            off = await ac.post(f"/api/v1/auth/oidc/{disabled}/start", json={})

        assert unknown.status_code == off.status_code == 404
        assert unknown.json()["detail"] == off.json()["detail"]
    finally:
        await drop_provider(disabled)


@pytest.mark.asyncio
async def test_callback_rejects_an_unknown_state():
    slug = await create_provider()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback",
                json={"code": "abc", "state": "never-issued-state"},
            )
        assert res.status_code == 400
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_callback_rejects_an_expired_state():
    slug = await create_provider()
    state = f"state-{uuid.uuid4().hex}"
    try:
        async with async_session_maker() as session:
            session.add(
                OidcAuthRequest(
                    state=state, provider_slug=slug, nonce="n", code_verifier="v",
                    redirect_uri=REDIRECT,
                    expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback", json={"code": "abc", "state": state}
            )
        assert res.status_code == 400
        assert "expired" in res.json()["detail"].lower()
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_callback_state_is_single_use():
    """A replayed callback must not produce a second session."""
    slug = await create_provider()
    state = f"state-{uuid.uuid4().hex}"
    try:
        async with async_session_maker() as session:
            session.add(
                OidcAuthRequest(
                    state=state, provider_slug=slug, nonce="n", code_verifier="v",
                    redirect_uri=REDIRECT,
                    consumed_at=datetime.now(timezone.utc),
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback", json={"code": "abc", "state": state}
            )
        assert res.status_code == 400
        assert "already used" in res.json()["detail"].lower()
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_existing_local_account_is_never_auto_adopted(monkeypatch):
    """The account-takeover case.

    A provider asserting an address that already has a local account must not hand
    that account over. The user has to sign in normally and link deliberately.
    """
    slug = await create_provider()
    tenant_id = await create_test_tenant()
    email = f"owner-{tenant_id}@example.test"
    state = f"state-{uuid.uuid4().hex}"

    async def fake_exchange(**kwargs):
        return {"id_token": make_id_token(email=email, nonce="n")}

    monkeypatch.setattr("core.main.exchange_code", fake_exchange)

    try:
        async with async_session_maker() as session:
            session.add(
                OidcAuthRequest(
                    state=state, provider_slug=slug, nonce="n", code_verifier="v",
                    redirect_uri=REDIRECT,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback", json={"code": "abc", "state": state}
            )

        assert res.status_code == 409
        assert "already exists" in res.json()["detail"]
    finally:
        await drop_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_unverified_email_is_refused(monkeypatch):
    slug = await create_provider(require_verified_email=True)
    state = f"state-{uuid.uuid4().hex}"
    email = f"unverified-{uuid.uuid4().hex[:8]}@example.test"

    async def fake_exchange(**kwargs):
        return {"id_token": make_id_token(email=email, email_verified=False, nonce="n")}

    monkeypatch.setattr("core.main.exchange_code", fake_exchange)

    try:
        async with async_session_maker() as session:
            session.add(
                OidcAuthRequest(
                    state=state, provider_slug=slug, nonce="n", code_verifier="v",
                    redirect_uri=REDIRECT,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback", json={"code": "abc", "state": state}
            )
        assert res.status_code == 403
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_signup_creates_an_account_and_issues_a_session(monkeypatch):
    slug = await create_provider(allow_signup=True)
    state = f"state-{uuid.uuid4().hex}"
    email = f"new-{uuid.uuid4().hex[:8]}@example.test"
    subject = f"sub-{uuid.uuid4().hex[:8]}"

    async def fake_exchange(**kwargs):
        return {"id_token": make_id_token(email=email, sub=subject, nonce="n")}

    monkeypatch.setattr("core.main.exchange_code", fake_exchange)

    try:
        async with async_session_maker() as session:
            session.add(
                OidcAuthRequest(
                    state=state, provider_slug=slug, nonce="n", code_verifier="v",
                    redirect_uri=REDIRECT,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
            )
            await session.commit()

        # https, because the session cookies are Secure and an RFC 6265 client
        # will not send them back over plain http.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://t"
        ) as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback", json={"code": "abc", "state": state}
            )

            assert res.status_code == 200, res.text
            body = res.json()
            assert body["account_created"] is True
            assert body["email"] == email
            # An external login is issued exactly like a local one: cookies, not
            # tokens in the body for the page to store.
            assert "access_token" not in body
            assert "refresh_token" not in body
            assert ac.cookies.get(ACCESS_COOKIE)

            # The issued session must actually work, carried by the cookie alone.
            me = await ac.get("/api/v1/auth/me")
            assert me.status_code == 200
            assert me.json()["email"] == email
    finally:
        await drop_provider(slug)
        await cleanup_user_by_email(email)


@pytest.mark.asyncio
async def test_signup_is_refused_when_the_provider_forbids_it(monkeypatch):
    slug = await create_provider(allow_signup=False)
    state = f"state-{uuid.uuid4().hex}"
    email = f"nosignup-{uuid.uuid4().hex[:8]}@example.test"

    async def fake_exchange(**kwargs):
        return {"id_token": make_id_token(email=email, sub=f"s-{uuid.uuid4().hex[:6]}", nonce="n")}

    monkeypatch.setattr("core.main.exchange_code", fake_exchange)

    try:
        async with async_session_maker() as session:
            session.add(
                OidcAuthRequest(
                    state=state, provider_slug=slug, nonce="n", code_verifier="v",
                    redirect_uri=REDIRECT,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.post(
                f"/api/v1/auth/oidc/{slug}/callback", json={"code": "abc", "state": state}
            )
        assert res.status_code == 403
    finally:
        await drop_provider(slug)
        await cleanup_user_by_email(email)


@pytest.mark.asyncio
async def test_identities_are_listed_and_tenant_scoped():
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    try:
        from tests.db_helpers import owner_user_id

        async with async_session_maker() as session:
            session.add(
                UserIdentity(
                    user_id=owner_user_id(tenant_a),
                    tenant_id=tenant_a,
                    provider_slug="google",
                    subject=f"sub-{uuid.uuid4().hex[:8]}",
                    email="a@example.test",
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            mine = await ac.get("/api/v1/data/oidc/identities", headers=auth_headers(tenant_a))
            theirs = await ac.get("/api/v1/data/oidc/identities", headers=auth_headers(tenant_b))

        assert len(mine.json()["identities"]) == 1
        assert theirs.json()["identities"] == []
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


@pytest.mark.asyncio
async def test_unlinking_the_only_login_method_is_refused():
    """Removing the last way in would lock the user out permanently."""
    tenant_id = await create_test_tenant()
    try:
        from tests.db_helpers import owner_user_id

        async with async_session_maker() as session:
            res = await session.execute(select(User).where(User.id == owner_user_id(tenant_id)))
            user = res.scalars().first()
            user.password_hash = "!oidc-only"
            session.add(
                UserIdentity(
                    user_id=user.id,
                    tenant_id=tenant_id,
                    provider_slug="google",
                    subject=f"sub-{uuid.uuid4().hex[:8]}",
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.delete(
                "/api/v1/data/oidc/identities/google", headers=auth_headers(tenant_id)
            )

        assert res.status_code == 409
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_unlinking_is_allowed_when_a_password_exists():
    tenant_id = await create_test_tenant()
    try:
        from tests.db_helpers import owner_user_id

        async with async_session_maker() as session:
            session.add(
                UserIdentity(
                    user_id=owner_user_id(tenant_id),
                    tenant_id=tenant_id,
                    provider_slug="google",
                    subject=f"sub-{uuid.uuid4().hex[:8]}",
                )
            )
            await session.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            res = await ac.delete(
                "/api/v1/data/oidc/identities/google", headers=auth_headers(tenant_id)
            )

        assert res.status_code == 200
    finally:
        await cleanup_test_tenant(tenant_id)
