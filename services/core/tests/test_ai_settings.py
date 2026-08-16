"""Integration tests for per-workspace AI settings.

Verifies:
- GET /api/v1/data/ai/settings
- PUT /api/v1/data/ai/settings

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- SecretMaskedInReadResponse
- StrictTenantIsolationOnRead
"""

import pytest
from core.db.models import WorkspaceAiSettings
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True

SECRET = "sk-litellm-not-a-real-key-000000"


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_ai_is_off_for_a_workspace_that_has_never_configured_it():
    """The default is off, and it is off without a row having to exist.

    Health data leaving the instance for a third-party model changes what the
    privacy policy has to say. That is a decision an operator makes, not a
    default they discover afterwards.
    """
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            body = (
                await client.get(
                    "/api/v1/data/ai/settings", headers=auth_headers(tenant_id)
                )
            ).json()
        assert body["enabled"] is False
        assert body["api_key_set"] is False
        assert body["masked_api_key"] is None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_api_key_is_encrypted_at_rest_and_never_returned():
    """Verifies Fizzbee Invariants: SecretsAlwaysEncryptedAtRest, SecretMaskedInReadResponse."""
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            saved = await client.put(
                "/api/v1/data/ai/settings",
                json={
                    "enabled": True,
                    "provider": "litellm",
                    "api_key": SECRET,
                    "base_url": "http://127.0.0.1:4000",
                    "embedding_model": "text-embedding-3-small",
                },
                headers=auth_headers(tenant_id),
            )
        assert saved.status_code == 200
        body = saved.json()
        assert body["enabled"] is True
        assert body["api_key_set"] is True
        # Masked, and the plaintext appears nowhere in the response body.
        assert SECRET not in saved.text
        assert body["masked_api_key"].endswith(SECRET[-4:])

        async with async_session_maker() as session:
            row = (
                await session.execute(
                    select(WorkspaceAiSettings).where(
                        WorkspaceAiSettings.tenant_id == tenant_id
                    )
                )
            ).scalars().first()
        assert row is not None
        # Stored ciphertext, not the key.
        assert row.encrypted_api_key
        assert SECRET not in row.encrypted_api_key
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_saving_a_model_change_does_not_clear_the_stored_key():
    """An omitted key means "unchanged", not "delete it".

    Otherwise changing the model through the interface silently disables the
    feature, and the reason would be invisible.
    """
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            headers = auth_headers(tenant_id)
            await client.put(
                "/api/v1/data/ai/settings",
                json={
                    "enabled": True,
                    "provider": "litellm",
                    "api_key": SECRET,
                    "base_url": "http://127.0.0.1:4000",
                },
                headers=headers,
            )
            updated = await client.put(
                "/api/v1/data/ai/settings",
                json={
                    "enabled": True,
                    "provider": "litellm",
                    "base_url": "http://127.0.0.1:4000",
                    "chat_model": "gpt-4o-mini",
                },
                headers=headers,
            )
        assert updated.json()["api_key_set"] is True
        assert updated.json()["chat_model"] == "gpt-4o-mini"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_litellm_cannot_be_enabled_without_an_endpoint_and_a_key():
    """A configuration that cannot work is refused where it is entered.

    Accepting it would move the failure to the first scheduled run, where the
    only trace is a log line nobody is reading.
    """
    tenant_id = await create_test_tenant()
    try:
        async with await _client() as client:
            response = await client.put(
                "/api/v1/data/ai/settings",
                json={"enabled": True, "provider": "litellm"},
                headers=auth_headers(tenant_id),
            )
        assert response.status_code == 422
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_one_workspaces_ai_settings_are_invisible_to_another():
    """Verifies Fizzbee Invariant: StrictTenantIsolationOnRead."""
    owner = await create_test_tenant()
    intruder = await create_test_tenant()
    try:
        async with await _client() as client:
            await client.put(
                "/api/v1/data/ai/settings",
                json={
                    "enabled": True,
                    "provider": "litellm",
                    "api_key": SECRET,
                    "base_url": "http://127.0.0.1:4000",
                },
                headers=auth_headers(owner),
            )
            seen = (
                await client.get(
                    "/api/v1/data/ai/settings", headers=auth_headers(intruder)
                )
            ).json()
        assert seen["enabled"] is False
        assert seen["api_key_set"] is False
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(intruder)
