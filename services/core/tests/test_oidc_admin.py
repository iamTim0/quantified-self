"""Administration of OIDC providers, and RP-initiated logout.

Providers were configurable only by inserting a row by hand, so the feature
worked but nobody without database access could turn it on. Logging out ended
only the local session, leaving the provider's alive -- the next "sign in with…"
completed instantly with no prompt, which reads as logout having done nothing.

Maps to Fizzbee Invariants:
- SecretMaskedInReadResponse
- NoUnauthorizedAccess
- SessionRevocationIsComplete
"""

import uuid

import pytest
from core.db.models import OidcProvider, UserIdentity
from core.db.session import async_session_maker
from core.main import app
from core.security import oidc as oidc_module
from core.security.crypto import decrypt_secret
from core.security.oidc import end_session_url
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from tests.db_helpers import (
    as_platform_tenant,
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
)

app.state.testing = True

ISSUER = "https://issuer.example.test"


@pytest.fixture(autouse=True)
def _stub_discovery(monkeypatch):
    """Provider validation must not depend on a live identity provider."""

    async def fake_discovery(issuer: str) -> dict:
        return {
            "issuer": issuer.rstrip("/"),
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/jwks",
            "end_session_endpoint": f"{issuer}/logout",
        }

    monkeypatch.setattr(oidc_module, "fetch_discovery", fake_discovery)
    import core.main as core_main

    monkeypatch.setattr(core_main, "fetch_discovery", fake_discovery)
    yield


async def _cleanup_provider(slug: str) -> None:
    async with async_session_maker() as session:
        await session.execute(delete(OidcProvider).where(OidcProvider.slug == slug))
        await session.commit()


def _payload(slug: str, **overrides) -> dict:
    body = {
        "slug": slug,
        "display_name": "Example IdP",
        "issuer": ISSUER,
        "client_id": "client-abc",
        "client_secret": "super-secret-value",
        "scopes": "openid email profile",
        "redirect_uri": "https://app.example.test/auth/callback",
        "claims_mapping": {},
        "enabled": True,
        "allow_signup": False,
        "require_verified_email": True,
    }
    body.update(overrides)
    return body


# ── The end_session URL itself ───────────────────────────────────────────────


def test_end_session_url_is_none_when_the_provider_offers_none():
    """Guessing one would send the user to a 404 on somebody else's domain."""
    assert (
        end_session_url(
            {"issuer": ISSUER},
            post_logout_redirect_uri="https://app.example.test/",
            client_id="client-abc",
        )
        is None
    )


def test_end_session_url_carries_the_redirect_and_client_but_no_token():
    """No id_token_hint: it would put the user's identity in browser history."""
    url = end_session_url(
        {"end_session_endpoint": f"{ISSUER}/logout"},
        post_logout_redirect_uri="https://app.example.test/",
        client_id="client-abc",
    )
    assert url is not None
    assert url.startswith(f"{ISSUER}/logout?")
    assert "post_logout_redirect_uri=https%3A%2F%2Fapp.example.test%2F" in url
    assert "client_id=client-abc" in url
    assert "id_token_hint" not in url


def test_end_session_url_appends_to_an_endpoint_that_already_has_a_query():
    url = end_session_url(
        {"end_session_endpoint": f"{ISSUER}/logout?realm=main"},
        post_logout_redirect_uri="https://app.example.test/",
        client_id="c",
    )
    assert "?realm=main&" in url


# ── Admin endpoints ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_stores_the_secret_encrypted_and_never_returns_it(monkeypatch: pytest.MonkeyPatch):
    """Verifies Fizzbee Invariant: SecretMaskedInReadResponse"""
    tenant_id = await create_test_tenant()
    # Providers belong to the deployment, not to a workspace.
    as_platform_tenant(monkeypatch, tenant_id)
    slug = f"idp-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )

        assert res.status_code == 201, res.text
        body = res.json()
        assert body["has_client_secret"] is True
        assert "client_secret" not in body
        assert "super-secret-value" not in res.text

        async with async_session_maker() as session:
            stored = (
                await session.execute(
                    select(OidcProvider).where(OidcProvider.slug == slug)
                )
            ).scalars().first()
        assert stored.encrypted_client_secret != "super-secret-value"
        assert decrypt_secret(stored.encrypted_client_secret) == "super-secret-value"
    finally:
        await _cleanup_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_editing_without_a_secret_keeps_the_stored_one(monkeypatch: pytest.MonkeyPatch):
    """Otherwise toggling a checkbox would require re-entering the secret."""
    tenant_id = await create_test_tenant()
    # Providers belong to the deployment, not to a workspace.
    as_platform_tenant(monkeypatch, tenant_id)
    slug = f"idp-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )
            updated = await ac.put(
                f"/api/v1/data/oidc/providers/{slug}",
                headers=auth_headers(tenant_id),
                json=_payload(slug, client_secret=None, enabled=False),
            )

        assert updated.status_code == 200, updated.text
        assert updated.json()["enabled"] is False
        assert updated.json()["has_client_secret"] is True

        async with async_session_maker() as session:
            stored = (
                await session.execute(
                    select(OidcProvider).where(OidcProvider.slug == slug)
                )
            ).scalars().first()
        assert decrypt_secret(stored.encrypted_client_secret) == "super-secret-value"
    finally:
        await _cleanup_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_member_cannot_manage_providers():
    """Verifies Fizzbee Invariant: NoUnauthorizedAccess"""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id, role="member"),
            )
        assert res.status_code == 403
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_duplicate_slug_is_refused(monkeypatch: pytest.MonkeyPatch):
    tenant_id = await create_test_tenant()
    # Providers belong to the deployment, not to a workspace.
    as_platform_tenant(monkeypatch, tenant_id)
    slug = f"idp-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            first = await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )
            assert first.status_code == 201
            second = await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )
        assert second.status_code == 409
    finally:
        await _cleanup_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_provider_in_use_cannot_be_deleted(monkeypatch: pytest.MonkeyPatch):
    """Deleting it would orphan an OIDC-only account that has no password.

    Disabling is the reversible action; deletion is for one never used.
    """
    tenant_id = await create_test_tenant()
    # Providers belong to the deployment, not to a workspace.
    as_platform_tenant(monkeypatch, tenant_id)
    slug = f"idp-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )

            async with async_session_maker() as session:
                from tests.db_helpers import owner_user_id

                session.add(
                    UserIdentity(
                        user_id=owner_user_id(tenant_id),
                        tenant_id=tenant_id,
                        provider_slug=slug,
                        subject="subject-123",
                    )
                )
                await session.commit()

            res = await ac.delete(
                f"/api/v1/data/oidc/providers/{slug}",
                headers=auth_headers(tenant_id),
            )

        assert res.status_code == 409
        assert "disable it" in res.json()["detail"].lower()
    finally:
        async with async_session_maker() as session:
            await session.execute(
                delete(UserIdentity).where(UserIdentity.provider_slug == slug)
            )
            await session.commit()
        await _cleanup_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_unused_provider_can_be_deleted(monkeypatch: pytest.MonkeyPatch):
    tenant_id = await create_test_tenant()
    # Providers belong to the deployment, not to a workspace.
    as_platform_tenant(monkeypatch, tenant_id)
    slug = f"idp-{uuid.uuid4().hex[:8]}"
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )
            res = await ac.delete(
                f"/api/v1/data/oidc/providers/{slug}",
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 204
    finally:
        await _cleanup_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_logout_returns_the_provider_end_session_url_for_a_federated_user(monkeypatch: pytest.MonkeyPatch):
    """The local logout is not enough on its own.

    Without this the provider session stays live and the next "sign in with…"
    completes with no prompt, so logging out appears to have done nothing.

    This also covers the wiring: the handler builds a JSONResponse, and
    JSONResponse was not imported -- every federated logout would have raised
    NameError inside the endpoint.

    Verifies Fizzbee Invariant: SessionRevocationIsComplete
    """
    tenant_id = await create_test_tenant()
    # Providers belong to the deployment, not to a workspace.
    as_platform_tenant(monkeypatch, tenant_id)
    slug = f"idp-{uuid.uuid4().hex[:8]}"
    try:
        from tests.db_helpers import owner_user_id

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            await ac.post(
                "/api/v1/data/oidc/providers",
                headers=auth_headers(tenant_id),
                json=_payload(slug),
            )
            async with async_session_maker() as session:
                session.add(
                    UserIdentity(
                        user_id=owner_user_id(tenant_id),
                        tenant_id=tenant_id,
                        provider_slug=slug,
                        subject="subject-456",
                    )
                )
                await session.commit()

            res = await ac.post(
                "/api/v1/auth/logout",
                headers=auth_headers(tenant_id),
                json={},
            )

        assert res.status_code == 200, res.text
        assert res.json()["end_session_url"].startswith(f"{ISSUER}/logout?")
        # The cookies are still cleared alongside it.
        assert any(
            c.startswith("qs_access=") for c in res.headers.get_list("set-cookie")
        )
    finally:
        async with async_session_maker() as session:
            await session.execute(
                delete(UserIdentity).where(UserIdentity.provider_slug == slug)
            )
            await session.commit()
        await _cleanup_provider(slug)
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_logout_for_a_password_user_is_still_a_plain_204():
    """No provider involved, nothing to redirect to."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/auth/logout", headers=auth_headers(tenant_id), json={}
            )
        assert res.status_code == 204
    finally:
        await cleanup_test_tenant(tenant_id)
