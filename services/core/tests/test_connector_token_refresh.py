"""The internal token endpoint refreshes an expiring credential before handing it out.

The unit tests in test_oauth_refresh.py cover the refresh mechanics. This covers
the wiring: that an importer asking for a WHOOP token near expiry gets a *fresh*
one, that the rotated refresh token is written back encrypted, and that neither
the refresh token nor the client secret is ever in the response.

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- TokenRefreshEnforced
- SecretMaskedInReadResponse
"""

import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from core.db.models import DataSource
from core.db.session import async_session_maker
from core.main import app
from core.security.crypto import decrypt_secret, encrypt_secret
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import cleanup_test_tenant, create_test_tenant, service_headers

app.state.testing = True


async def _whoop_connector(tenant_id: str, *, expires_at: datetime) -> str:
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type="whoop",
                display_name="Whoop",
                config={
                    "status": "active",
                    "encrypted_token": encrypt_secret("expiring-access-token"),
                    "masked_token": "••••••••oken",
                    "encrypted_refresh_token": encrypt_secret("stored-refresh-token"),
                    "encrypted_client_secret": encrypt_secret("stored-client-secret"),
                    "client_id": "whoop-client-id",
                    "token_expires_at": expires_at.isoformat(),
                },
            )
        )
        await session.commit()
    return source_id


def _patch_token_endpoint(monkeypatch, handler):
    real_init = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        # Only the outbound provider call is mocked; the ASGI transport the test
        # client uses is left alone.
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(handler)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)


@pytest.mark.asyncio
async def test_an_expiring_token_is_refreshed_and_persisted(monkeypatch):
    """The importer receives the new token; the new refresh token is stored."""
    tenant_id = await create_test_tenant()
    try:
        await _whoop_connector(
            tenant_id, expires_at=datetime.now(timezone.utc) + timedelta(seconds=30)
        )

        def handler(request: httpx.Request) -> httpx.Response:
            assert "whoop.com" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "access_token": "freshly-minted-token",
                    "refresh_token": "rotated-refresh-token",
                    "expires_in": 3600,
                },
            )

        _patch_token_endpoint(monkeypatch, handler)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/internal/data/sources/whoop/token",
                headers=service_headers(tenant_id),
            )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["access_token"] == "freshly-minted-token"

        # The rotated refresh token is persisted, encrypted. WHOOP invalidates the
        # previous one, so losing this write means the next refresh fails.
        async with async_session_maker() as session:
            source = (
                await session.execute(
                    DataSource.__table__.select().where(
                        DataSource.tenant_id == tenant_id
                    )
                )
            ).first()
        stored = source.config
        assert decrypt_secret(stored["encrypted_refresh_token"]) == "rotated-refresh-token"
        assert decrypt_secret(stored["encrypted_token"]) == "freshly-minted-token"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_response_never_carries_the_refresh_token_or_client_secret(monkeypatch):
    """Only the short-lived access token crosses to the importer (rule 12).

    Verifies Fizzbee Invariant: SecretMaskedInReadResponse
    """
    tenant_id = await create_test_tenant()
    try:
        await _whoop_connector(
            tenant_id, expires_at=datetime.now(timezone.utc) + timedelta(hours=5)
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/internal/data/sources/whoop/token",
                headers=service_headers(tenant_id),
            )

        assert res.status_code == 200, res.text
        raw = res.text
        assert "stored-refresh-token" not in raw
        assert "stored-client-secret" not in raw
        config = res.json()["config"]
        assert "encrypted_refresh_token" not in config
        assert "encrypted_client_secret" not in config
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_valid_token_is_not_refreshed(monkeypatch):
    """Refreshing early would spend a single-use refresh token for nothing."""
    tenant_id = await create_test_tenant()
    try:
        await _whoop_connector(
            tenant_id, expires_at=datetime.now(timezone.utc) + timedelta(hours=5)
        )

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("refresh must not be attempted for a valid token")

        _patch_token_endpoint(monkeypatch, handler)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/internal/data/sources/whoop/token",
                headers=service_headers(tenant_id),
            )

        assert res.status_code == 200
        assert res.json()["access_token"] == "expiring-access-token"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_dead_refresh_token_reports_a_reconnect_rather_than_an_expired_token(
    monkeypatch,
):
    """Handing back a token already known to be expired just moves the failure."""
    tenant_id = await create_test_tenant()
    try:
        await _whoop_connector(
            tenant_id, expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)
        )

        _patch_token_endpoint(
            monkeypatch,
            lambda request: httpx.Response(400, json={"error": "invalid_grant"}),
        )

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as ac:
            res = await ac.get(
                "/api/v1/internal/data/sources/whoop/token",
                headers=service_headers(tenant_id),
            )

        assert res.status_code == 409
        assert "connect it again" in res.json()["detail"].lower()
    finally:
        await cleanup_test_tenant(tenant_id)
