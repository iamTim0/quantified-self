"""OIDC Back-Channel Logout: the provider tells us a session is over.

RP-initiated logout covers the user clicking "sign out" here. This is the other
direction — signed out at the provider, account disabled, device deprovisioned —
and until now nothing consumed the notification, so the local session lived out
its full thirty days.

The endpoint is unauthenticated by necessity: the caller is the provider's
server, which holds no session with us. Everything therefore rests on validating
the token, so most of what follows is negative cases. Each one corresponds to a
clause in ``verify_logout_token`` and to a defect in
``specs/oidc_backchannel_logout.fizz``; deleting a clause makes the model checker
produce that defect and makes one of these fail.

Maps to Fizzbee Invariants:
- AcceptedTokenWasGenuine
- AcceptedLogoutLeavesNothingItCoveredAlive
- ProviderLogoutEventuallyEndsEverySession
"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from core.db.models import OidcProvider, RefreshToken, User, UserIdentity
from core.db.session import async_session_maker
from core.main import app
from core.security import oidc as oidc_module
from core.security.crypto import encrypt_secret
from core.security.oidc import BACKCHANNEL_LOGOUT_EVENT, OidcError, verify_logout_token
from core.security.tokens import create_access_token, create_refresh_token
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

from tests.db_helpers import cleanup_test_tenant, create_test_tenant, owner_user_id

app.state.testing = True

ISSUER = "https://idp.example.test"
CLIENT_ID = "qs-client-id"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
}

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_logout_token(*, key=None, **overrides) -> str:
    """A conformant logout token, unless the caller breaks one thing on purpose."""
    now = datetime.now(timezone.utc)
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "sub": "provider-subject-123",
        "iat": now,
        "jti": str(uuid.uuid4()),
        "events": {BACKCHANNEL_LOGOUT_EVENT: {}},
    }
    claims.update(overrides)
    for field, value in list(claims.items()):
        if value is _ABSENT:
            del claims[field]
    return jwt.encode(claims, key or _KEY, algorithm="RS256")


class _Absent:
    """Sentinel so a test can remove a claim rather than only change it."""


_ABSENT = _Absent()


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
    fields: dict = {
        "slug": f"idp-{uuid.uuid4().hex[:6]}",
        "display_name": "Test IdP",
        "issuer": ISSUER,
        "client_id": CLIENT_ID,
        "encrypted_client_secret": encrypt_secret("client-secret"),
        "redirect_uri": "https://app.example.test/auth/callback",
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
        await session.execute(delete(OidcProvider).where(OidcProvider.slug == slug))
        await session.commit()


async def link_identity(tenant_id: str, slug: str, subject: str) -> None:
    async with async_session_maker() as session:
        session.add(
            UserIdentity(
                user_id=owner_user_id(tenant_id),
                tenant_id=tenant_id,
                provider_slug=slug,
                subject=subject,
                email=f"owner-{tenant_id}@example.test",
            )
        )
        await session.commit()


async def give_refresh_token(tenant_id: str) -> str:
    """Persist a live refresh token for the tenant's owner and return its hash."""
    _raw, token_hash, expires_at = create_refresh_token()
    async with async_session_maker() as session:
        session.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=owner_user_id(tenant_id),
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        await session.commit()
    return token_hash


async def refresh_token_is_live(token_hash: str) -> bool:
    async with async_session_maker() as session:
        revoked_at = (
            await session.execute(
                select(RefreshToken.revoked_at).where(
                    RefreshToken.token_hash == token_hash
                )
            )
        ).scalar_one_or_none()
    return revoked_at is None


async def post_logout(slug: str, token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver"
    ) as ac:
        return await ac.post(
            f"/api/v1/auth/oidc/{slug}/backchannel-logout",
            content=f"logout_token={token}",
            headers=FORM,
        )


# ─── token validation, one test per clause ───────────────────


def _verify(token: str, **overrides):
    kwargs = {
        "logout_token": token,
        "discovery": DISCOVERY,
        "client_id": CLIENT_ID,
        "issuer": ISSUER,
    }
    kwargs.update(overrides)
    return verify_logout_token(**kwargs)


def test_a_conformant_token_names_its_subject(stub_provider_network):
    named = _verify(make_logout_token())
    assert named.subject == "provider-subject-123"
    assert named.session_id is None


def test_a_token_signed_by_another_key_is_refused(stub_provider_network):
    with pytest.raises(OidcError) as exc:
        _verify(make_logout_token(key=_OTHER_KEY))
    assert exc.value.status_code == 400


def test_a_token_from_another_issuer_is_refused(stub_provider_network):
    with pytest.raises(OidcError):
        _verify(make_logout_token(iss="https://evil.example.test"))


def test_a_token_for_another_audience_is_refused(stub_provider_network):
    with pytest.raises(OidcError):
        _verify(make_logout_token(aud="some-other-client"))


def test_a_token_carrying_a_nonce_is_refused(stub_provider_network):
    """An ID token is not a logout token.

    Without this clause, a token captured during a *login* could be posted here
    to end the session it was issued for.
    """
    with pytest.raises(OidcError) as exc:
        _verify(make_logout_token(nonce="from-a-login"))
    assert "nonce" in exc.value.detail


def test_a_token_without_the_logout_event_is_refused(stub_provider_network):
    with pytest.raises(OidcError):
        _verify(make_logout_token(events=_ABSENT))


def test_a_token_whose_event_value_is_not_an_object_is_refused(stub_provider_network):
    # The specification requires a JSON object here. A string that happens to
    # contain the event name is not one.
    with pytest.raises(OidcError):
        _verify(make_logout_token(events={BACKCHANNEL_LOGOUT_EVENT: "yes"}))


def test_a_stale_token_is_refused(stub_provider_network):
    """Freshness is what makes a captured token worthless without a jti store.

    A replay is otherwise idempotent and harmless — right up until the user has
    signed in again, at which point the old token would end the new session.
    """
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    with pytest.raises(OidcError) as exc:
        _verify(make_logout_token(iat=old))
    assert "too old" in exc.value.detail


def test_a_token_naming_nobody_is_refused(stub_provider_network):
    with pytest.raises(OidcError):
        _verify(make_logout_token(sub=_ABSENT))


def test_a_sid_only_token_validates_but_names_no_subject(stub_provider_network):
    named = _verify(make_logout_token(sub=_ABSENT, sid="provider-session-9"))
    assert named.subject is None
    assert named.session_id == "provider-session-9"


def test_unreachable_signing_keys_are_a_retryable_failure(monkeypatch):
    """503, not 400.

    Fail closed — acting on a token we cannot verify would let anyone end any
    session during a key-server outage. But the provider must retry, and it will
    not retry a 400. ``ProviderLogoutEventuallyEndsEverySession`` is exactly this
    claim: refusing during an outage is only safe because the retry converges.
    """

    class _Broken:
        def __init__(self, *a, **kw):
            pass

        def get_signing_key_from_jwt(self, token):
            raise ConnectionError("jwks unreachable")

    oidc_module.clear_discovery_cache()
    monkeypatch.setattr(oidc_module, "PyJWKClient", _Broken)

    with pytest.raises(OidcError) as exc:
        _verify(make_logout_token())
    assert exc.value.status_code == 503


# ─── the endpoint ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_valid_notification_ends_every_session_for_that_identity():
    tenant_id = await create_test_tenant()
    slug = await create_provider()
    await link_identity(tenant_id, slug, "provider-subject-123")
    token_hash = await give_refresh_token(tenant_id)

    # An access token minted before the notification, as a signed-in browser has.
    access, _jti, _exp = create_access_token(
        user_id=owner_user_id(tenant_id),
        tenant_id=tenant_id,
        email=f"owner-{tenant_id}@example.test",
        role="owner",
    )

    try:
        response = await post_logout(slug, make_logout_token())
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-store"

        assert not await refresh_token_is_live(token_hash)

        # The half that was missing. Revoking refresh tokens only stops *renewal*;
        # the access token already in the browser stayed valid for its remaining
        # twelve hours, so the session the provider ended kept working.
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            me = await ac.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"}
            )
        assert me.status_code == 401
    finally:
        await drop_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_session_started_after_the_notification_works():
    """The cutoff must not lock the account out permanently.

    Signing back in issues a token with a later ``iat``, which is on the right
    side of the cutoff.
    """
    tenant_id = await create_test_tenant()
    slug = await create_provider()
    await link_identity(tenant_id, slug, "provider-subject-123")

    try:
        assert (await post_logout(slug, make_logout_token())).status_code == 200

        async with async_session_maker() as session:
            cutoff = (
                await session.execute(
                    select(User.sessions_valid_from).where(
                        User.id == owner_user_id(tenant_id)
                    )
                )
            ).scalar_one()
        assert cutoff is not None

        # Wind the cutoff back rather than dating a token into the future: `iat`
        # is validated by PyJWT and a future one is rejected outright, so forging
        # the token would test the wrong thing. Moving the cutoff models the same
        # situation — time passes, the user signs in again — and keeps the token
        # a perfectly ordinary one.
        async with async_session_maker() as session:
            await session.execute(
                update(User)
                .where(User.id == owner_user_id(tenant_id))
                .values(sessions_valid_from=cutoff - timedelta(minutes=5))
            )
            await session.commit()

        fresh, _jti, _exp = create_access_token(
            user_id=owner_user_id(tenant_id),
            tenant_id=tenant_id,
            email=f"owner-{tenant_id}@example.test",
            role="owner",
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            me = await ac.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {fresh}"}
            )
        assert me.status_code == 200
    finally:
        await drop_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_another_users_session_is_untouched():
    """Over-revoking across accounts would be a far worse bug than the one fixed."""
    victim = await create_test_tenant()
    bystander = await create_test_tenant()
    slug = await create_provider()
    await link_identity(victim, slug, "provider-subject-123")
    bystander_hash = await give_refresh_token(bystander)

    try:
        assert (await post_logout(slug, make_logout_token())).status_code == 200
        assert await refresh_token_is_live(bystander_hash)
    finally:
        await drop_provider(slug)
        await cleanup_test_tenant(victim)
        await cleanup_test_tenant(bystander)


@pytest.mark.asyncio
async def test_a_forged_token_ends_nothing():
    tenant_id = await create_test_tenant()
    slug = await create_provider()
    await link_identity(tenant_id, slug, "provider-subject-123")
    token_hash = await give_refresh_token(tenant_id)

    try:
        response = await post_logout(slug, make_logout_token(key=_OTHER_KEY))
        assert response.status_code == 400
        assert await refresh_token_is_live(token_hash)
    finally:
        await drop_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_unknown_subject_is_accepted_and_does_nothing():
    """200, not 404.

    The provider is telling us something true and there is simply nothing to do.
    A 404 would have it retry an event that can never apply, and would also turn
    this endpoint into an oracle for which subjects have accounts here.
    """
    slug = await create_provider()
    try:
        response = await post_logout(slug, make_logout_token(sub="nobody-here"))
        assert response.status_code == 200
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_a_sid_only_notification_is_refused_rather_than_guessed():
    """We do not bind sessions to a provider `sid`, so we cannot honour one.

    Refusing says so. Treating it as "log everyone out" would end sessions the
    provider never named.
    """
    slug = await create_provider()
    try:
        response = await post_logout(
            slug, make_logout_token(sub=_ABSENT, sid="provider-session-9")
        )
        assert response.status_code == 400
        assert "sub" in response.json()["detail"]
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_the_wrong_content_type_is_refused():
    slug = await create_provider()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            response = await ac.post(
                f"/api/v1/auth/oidc/{slug}/backchannel-logout",
                json={"logout_token": make_logout_token()},
            )
        assert response.status_code == 400
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_a_missing_token_is_refused():
    slug = await create_provider()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            response = await ac.post(
                f"/api/v1/auth/oidc/{slug}/backchannel-logout",
                content="",
                headers=FORM,
            )
        assert response.status_code == 400
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_a_disabled_provider_does_not_accept_notifications():
    """Disabling a provider must actually stop it acting on this deployment."""
    slug = await create_provider(enabled=False)
    try:
        response = await post_logout(slug, make_logout_token())
        assert response.status_code == 404
    finally:
        await drop_provider(slug)


@pytest.mark.asyncio
async def test_the_endpoint_needs_no_session_of_its_own():
    """A regression guard on the middleware exemption.

    The provider has no cookie and no bearer token. If this path ever stopped
    being exempt, every notification would 401 and the feature would fail
    silently — the provider retries, gives up, and nothing is logged here.
    """
    slug = await create_provider()
    try:
        response = await post_logout(slug, make_logout_token(sub="nobody-here"))
        assert response.status_code != 401
    finally:
        await drop_provider(slug)
