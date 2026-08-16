"""Integration tests for Core Data Service Connector Configuration & Secret Encryption endpoints.

Verifies:
- POST /api/v1/data/sources/configure
- GET /api/v1/data/sources

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- SecretMaskedInReadResponse
- InstanceNamesUniquePerTenantType
"""

import pytest
from core.main import app
from httpx import ASGITransport, AsyncClient

from tests.db_helpers import (
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
    service_headers,
)

app.state.testing = True

@pytest.mark.asyncio
async def test_configure_and_list_connectors():
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    # Step 1: Configure Oura Ring connector
    payload = {
        "source_type": "oura",
        "display_name": "Oura Ring",
        "access_token": "oura_personal_token_secret_9999",
        "status": "active"
    }

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            config_res = await ac.post("/api/v1/data/sources/configure", json=payload, headers=headers)
    
        assert config_res.status_code == 200
        config_data = config_res.json()
        assert config_data["status"] == "success"
        assert config_data["source_type"] == "oura"
        assert config_data["masked_token"] == "••••••••9999"
        assert "oura_personal_token" not in config_data["masked_token"]

    # Step 2: List connectors for tenant and verify secret is masked
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            list_res = await ac.get("/api/v1/data/sources", headers=headers)

        assert list_res.status_code == 200
        list_data = list_res.json()
        assert "connectors" in list_data
        assert len(list_data["connectors"]) >= 1

        source_id = config_data["source_id"]
        oura_conn = next(c for c in list_data["connectors"] if c["id"] == source_id)
        assert oura_conn["masked_token"] == "••••••••9999"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_push_connector_configures_without_a_provider_credential():
    """Apple Health and Streak authenticate per-request with tenant-bound API keys.

    They hold no provider credential of their own, so requiring one at setup made the
    connector impossible to configure once the key flow replaced the token flow.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={"source_type": "apple_health", "display_name": "Phone", "status": "active"},
                headers=headers,
            )
            assert res.status_code == 200, res.text

            listed = await ac.get("/api/v1/data/sources", headers=headers)

        # Must still appear in the list even though it has no encrypted_token.
        types = [c["source_type"] for c in listed.json()["connectors"]]
        assert "apple_health" in types
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_two_connectors_of_one_type_coexist():
    """The point of the whole change: several calendars, told apart by name.

    `UNIQUE (tenant_id, source_type)` made the second configure overwrite the
    first, silently, so a user who added a family calendar lost their work one.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            work = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "display_name": "Work",
                    "status": "active",
                    "config": {"ics_url": "https://example.com/work.ics"},
                },
                headers=headers,
            )
            family = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "display_name": "Family",
                    "status": "active",
                    "config": {"ics_url": "https://example.com/family.ics"},
                },
                headers=headers,
            )
            assert work.status_code == 200, work.text
            assert family.status_code == 200, family.text

            work_id = work.json()["source_id"]
            family_id = family.json()["source_id"]
            assert work_id != family_id

            listed = await ac.get("/api/v1/data/sources", headers=headers)

            # Each instance hands out its own configuration, not the other's.
            work_token = await ac.get(
                f"/api/v1/internal/data/sources/{work_id}/token",
                headers=service_headers(tenant_id),
            )
            family_token = await ac.get(
                f"/api/v1/internal/data/sources/{family_id}/token",
                headers=service_headers(tenant_id),
            )

        calendars = [c for c in listed.json()["connectors"] if c["source_type"] == "calendar"]
        assert sorted(c["display_name"] for c in calendars) == ["Family", "Work"]

        assert work_token.json()["config"]["ics_url"] == "https://example.com/work.ics"
        assert family_token.json()["config"]["ics_url"] == "https://example.com/family.ics"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_two_connectors_may_not_share_a_name():
    """Verifies Fizzbee Invariant: InstanceNamesUniquePerTenantType.

    Otherwise the list a user picks from shows two identical rows.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)
    body = {
        "source_type": "calendar",
        "display_name": "Work",
        "status": "active",
        "config": {"ics_url": "https://example.com/work.ics"},
    }

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            first = await ac.post("/api/v1/data/sources/configure", json=body, headers=headers)
            second = await ac.post("/api/v1/data/sources/configure", json=body, headers=headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 409, second.text
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_deleted_connector_name_can_be_reused():
    """Verifies Fizzbee Invariant: InstanceNamesUniquePerTenantType.

    Deletion preserves the historical source row, but only active connector
    names participate in the uniqueness rule.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)
    body = {
        "source_type": "calendar",
        "display_name": "Work",
        "status": "active",
        "config": {"ics_url": "https://example.com/work.ics"},
    }

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            first = await ac.post(
                "/api/v1/data/sources/configure", json=body, headers=headers
            )
            assert first.status_code == 200, first.text

            deleted = await ac.delete(
                f"/api/v1/data/sources/{first.json()['source_id']}", headers=headers
            )
            assert deleted.status_code == 200, deleted.text

            replacement = await ac.post(
                "/api/v1/data/sources/configure", json=body, headers=headers
            )
            assert replacement.status_code == 200, replacement.text
            assert replacement.json()["source_id"] != first.json()["source_id"]

            listed = await ac.get("/api/v1/data/sources", headers=headers)
            assert listed.status_code == 200, listed.text
            assert [item["display_name"] for item in listed.json()["connectors"]] == [
                "Work"
            ]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_creating_a_connector_requires_a_name():
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "status": "active",
                    "config": {"ics_url": "https://example.com/work.ics"},
                },
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 422, res.text
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_editing_by_id_updates_that_instance_only():
    """Editing used to mean "overwrite whichever row has this type"."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            work = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "display_name": "Work",
                    "status": "active",
                    "config": {"ics_url": "https://example.com/work.ics"},
                },
                headers=headers,
            )
            family = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "display_name": "Family",
                    "status": "active",
                    "config": {"ics_url": "https://example.com/family.ics"},
                },
                headers=headers,
            )
            family_id = family.json()["source_id"]

            await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "source_id": family_id,
                    "status": "active",
                    "config": {"ics_url": "https://example.com/family-v2.ics"},
                },
                headers=headers,
            )

            work_token = await ac.get(
                f"/api/v1/internal/data/sources/{work.json()['source_id']}/token",
                headers=service_headers(tenant_id),
            )
            family_token = await ac.get(
                f"/api/v1/internal/data/sources/{family_id}/token",
                headers=service_headers(tenant_id),
            )

        assert family_token.json()["config"]["ics_url"] == "https://example.com/family-v2.ics"
        assert work_token.json()["config"]["ics_url"] == "https://example.com/work.ics"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_calendar_ics_url_configures_without_an_api_key():
    """A public ICS URL is a complete configuration on its own."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)
    ics_url = "https://outlook.office365.com/owa/calendar/public/calendar.ics"

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "calendar",
                    "display_name": "Work calendar",
                    "status": "active",
                    "config": {"ics_url": ics_url},
                },
                headers=headers,
            )
            assert res.status_code == 200, res.text

            # The importer must be able to read the feed config back with a null token.
            internal = await ac.get(
                "/api/v1/internal/data/sources/calendar/token",
                headers=service_headers(tenant_id),
            )

        assert internal.status_code == 200, internal.text
        data = internal.json()
        assert data["access_token"] is None
        assert data["config"]["ics_url"] == ics_url
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_weather_configures_and_lists_without_an_api_key():
    """Open-Meteo issues no keys, so demanding one made weather unconfigurable.

    The listing assertion is the half that mattered most: a weather connector
    saved without a token used to be filtered out of `GET /sources` as
    "unconfigured", so it could not even be found again to be repaired.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "weather",
                    "display_name": "Home",
                    "status": "active",
                    "config": {"latitude": 52.52, "longitude": 13.41},
                },
                headers=headers,
            )
            assert res.status_code == 200, res.text

            listed = await ac.get("/api/v1/data/sources", headers=headers)
            internal = await ac.get(
                "/api/v1/internal/data/sources/weather/token",
                headers=service_headers(tenant_id),
            )

        assert listed.status_code == 200, listed.text
        assert any(c["source_type"] == "weather" for c in listed.json()["connectors"])

        assert internal.status_code == 200, internal.text
        data = internal.json()
        assert data["access_token"] is None
        assert data["config"]["latitude"] == 52.52
        assert data["config"]["longitude"] == 13.41
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_weather_without_coordinates_is_rejected():
    """The importer cannot work without them, so saving one is a 422, not a surprise."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "weather",
                    "display_name": "Home",
                    "status": "active",
                    "config": {"base_url": "https://api.open-meteo.com"},
                },
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 422, res.text
        assert "latitude" in res.json()["detail"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_weather_coordinates_out_of_range_are_rejected():
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={
                    "source_type": "weather",
                    "display_name": "Home",
                    "status": "active",
                    "config": {"latitude": 991.0, "longitude": 13.41},
                },
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 422, res.text
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_pull_connector_still_requires_a_credential():
    """The relaxation must not leak to connectors that genuinely need a token."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post(
                "/api/v1/data/sources/configure",
                json={"source_type": "whoop", "display_name": "Whoop band", "status": "active"},
                headers=auth_headers(tenant_id),
            )
        assert res.status_code == 400
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_configure_yazio_and_delete_connector(monkeypatch):
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()
    headers = auth_headers(tenant_id)

    # Step 1: Configure Yazio with direct Bearer Token
    payload = {
        "source_type": "yazio",
        "display_name": "Yazio",
        "access_token": "yazio_token_secret_1234",
        "status": "active"
    }

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            res = await ac.post("/api/v1/data/sources/configure", json=payload, headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert data["status"] == "success"
            assert data["source_type"] == "yazio"

            # Verify DELETE endpoint
            del_res = await ac.delete("/api/v1/data/sources/yazio", headers=headers)
            assert del_res.status_code == 200
            del_data = del_res.json()
            assert del_data["status"] == "success"

            # Verify list is empty
            list_res = await ac.get("/api/v1/data/sources", headers=headers)
            assert list_res.status_code == 200
            assert len(list_res.json()["connectors"]) == 0
    finally:
        await cleanup_test_tenant(tenant_id)
