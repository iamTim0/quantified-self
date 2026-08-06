"""Integration tests for tenant-bound inbound API keys.

The contract these pin down: an external pusher sends nothing but the key, the
tenant is recovered from the key's hash, and the plaintext key exists in exactly
one response and nowhere else.

Maps to Fizzbee Invariants:
- WebhookMappedToCorrectTenant
- UnauthenticatedWebhookRejected
- SecretMaskedInReadResponse
"""

from datetime import datetime, timedelta, timezone

import pytest
from core.db.models import ApiKey
from core.db.session import async_session_maker
from core.main import app
from core.security.tokens import hash_token
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import (
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
    service_headers,
)

app.state.testing = True


async def _create_key(ac: AsyncClient, tenant_id: str, **overrides) -> dict:
    body = {"name": "Health Auto Export", "source_type": "apple_health"}
    body.update(overrides)
    res = await ac.post(
        "/api/v1/data/api-keys", json=body, headers=auth_headers(tenant_id)
    )
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_created_key_is_returned_once_and_stored_hashed():
    """The plaintext key must never be persisted or re-exposed."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id)
            raw = created["api_key"]
            assert raw.startswith("qsk_")
            assert created["key_prefix"] == raw[:12]

            listed = await ac.get("/api/v1/data/api-keys", headers=auth_headers(tenant_id))

        keys = listed.json()["api_keys"]
        assert len(keys) == 1
        # The listing exposes the prefix only.
        assert raw not in listed.text
        assert keys[0]["key_prefix"] == raw[:12]

        async with async_session_maker() as session:
            res = await session.execute(
                select(ApiKey).where(ApiKey.tenant_id == tenant_id)
            )
            stored = res.scalars().first()
            assert stored.key_hash == hash_token(raw)
            assert raw not in stored.key_hash
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_key_resolves_to_its_owning_tenant_without_any_header():
    """The whole point: identity comes from the key, not from X-Tenant-ID."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id)

            res = await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(created["api_key"]),
                    "source_type": "apple_health",
                },
                headers=service_headers(),  # deliberately no X-Tenant-ID
            )

        assert res.status_code == 200, res.text
        assert res.json()["tenant_id"] == tenant_id
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_resolution_requires_a_service_credential():
    """A user token must not be able to resolve keys."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id)
            res = await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(created["api_key"]),
                    "source_type": "apple_health",
                },
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 401
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_unknown_key_is_rejected():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        res = await ac.post(
            "/api/v1/internal/auth/api-keys/resolve",
            json={"key_hash": "0" * 64, "source_type": "apple_health"},
            headers=service_headers(),
        )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_key_cannot_be_replayed_against_another_connector():
    """A key minted for apple_health must not work on the streak endpoint."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id, source_type="apple_health")
            res = await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(created["api_key"]),
                    "source_type": "streak",
                },
                headers=service_headers(),
            )
        assert res.status_code == 403
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_revoked_key_stops_resolving():
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id)
            revoked = await ac.post(
                f"/api/v1/data/api-keys/{created['id']}/revoke",
                headers=auth_headers(tenant_id),
            )
            assert revoked.status_code == 200
            assert revoked.json()["status"] == "revoked"

            res = await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(created["api_key"]),
                    "source_type": "apple_health",
                },
                headers=service_headers(),
            )
        assert res.status_code == 401
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_expired_key_stops_resolving():
    """Expiry is enforced at resolution, not only at creation."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id, expires_in_days=1)

            async with async_session_maker() as session:
                res = await session.execute(
                    select(ApiKey).where(ApiKey.id == created["id"])
                )
                key = res.scalars().first()
                key.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                await session.commit()

            resolved = await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(created["api_key"]),
                    "source_type": "apple_health",
                },
                headers=service_headers(),
            )
        assert resolved.status_code == 401
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_rotation_leaves_both_keys_usable_until_revocation():
    """Rotation must not create an ingest gap while the pusher is reconfigured."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            original = await _create_key(ac, tenant_id)
            rotated = await ac.post(
                f"/api/v1/data/api-keys/{original['id']}/rotate",
                headers=auth_headers(tenant_id),
            )
            assert rotated.status_code == 200
            new_key = rotated.json()
            assert new_key["api_key"] != original["api_key"]
            assert new_key["rotated_from_id"] == original["id"]

            for key in (original["api_key"], new_key["api_key"]):
                res = await ac.post(
                    "/api/v1/internal/auth/api-keys/resolve",
                    json={"key_hash": hash_token(key), "source_type": "apple_health"},
                    headers=service_headers(),
                )
                assert res.status_code == 200, f"{key[:12]} should still resolve"

            await ac.post(
                f"/api/v1/data/api-keys/{original['id']}/revoke",
                headers=auth_headers(tenant_id),
            )
            old = await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(original["api_key"]),
                    "source_type": "apple_health",
                },
                headers=service_headers(),
            )
        assert old.status_code == 401
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_keys_are_not_visible_to_another_tenant():
    """Verifies Fizzbee Invariant: TenantSecretIsolation."""
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_a)

            listed = await ac.get("/api/v1/data/api-keys", headers=auth_headers(tenant_b))
            assert listed.json()["api_keys"] == []

            hijack = await ac.post(
                f"/api/v1/data/api-keys/{created['id']}/revoke",
                headers=auth_headers(tenant_b),
            )
        assert hijack.status_code == 404
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


@pytest.mark.asyncio
async def test_members_may_not_mint_keys():
    """Key creation is an owner/admin operation."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/api-keys",
                json={"name": "sneaky", "source_type": "apple_health"},
                headers=auth_headers(tenant_id, role="member"),
            )
        assert res.status_code == 403
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_key_for_a_pull_connector_is_refused():
    """Only push sources need an inbound key; anything else is a configuration error."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            res = await ac.post(
                "/api/v1/data/api-keys",
                json={"name": "wrong", "source_type": "whoop"},
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 400
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_resolution_records_last_used():
    """Operators need to see whether a key is still in use before revoking it."""
    tenant_id = await create_test_tenant()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            created = await _create_key(ac, tenant_id)
            assert created["last_used_at"] is None

            await ac.post(
                "/api/v1/internal/auth/api-keys/resolve",
                json={
                    "key_hash": hash_token(created["api_key"]),
                    "source_type": "apple_health",
                },
                headers=service_headers(),
            )

            listed = await ac.get("/api/v1/data/api-keys", headers=auth_headers(tenant_id))

        assert listed.json()["api_keys"][0]["last_used_at"] is not None
    finally:
        await cleanup_test_tenant(tenant_id)
