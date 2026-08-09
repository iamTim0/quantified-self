"""Which provider fields an importer read, and which it saw and did not.

The feature exists because four families of Apple Health data were dropped
silently for months: nothing failed, so nothing said so, and the only way anyone
found out was by holding the provider's documentation against the transformer by
hand. These tests pin the two properties that make the report trustworthy — it
notices a gap, and it never carries a value.
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


async def _connector(ac: AsyncClient, tenant_id: str) -> str:
    res = await ac.post(
        "/api/v1/data/sources/configure",
        json={
            "source_type": "apple_health",
            "display_name": "Phone",
            "status": "active",
        },
        headers=auth_headers(tenant_id),
    )
    assert res.status_code == 200, res.text
    return res.json()["source_id"]


@pytest.mark.asyncio
async def test_an_unmapped_field_is_reported_and_a_mapped_one_is_not():
    """The list a user reads is "seen and not stored", not "seen"."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            source_id = await _connector(ac, tenant_id)

            posted = await ac.post(
                f"/api/v1/internal/data/sources/{source_id}/field-report",
                json={
                    "mapped": [
                        {"path": "metrics.steps.qty", "kind": "number",
                         "occurrences": 30, "metric_type": "steps"}
                    ],
                    "unmapped": [
                        {"path": "workouts.swolfScore", "kind": "number", "occurrences": 4}
                    ],
                },
                headers=service_headers(tenant_id),
            )
            assert posted.status_code == 202, posted.text

            listed = await ac.get(
                "/api/v1/data/quality/unsupported-fields", headers=auth_headers(tenant_id)
            )

        fields = listed.json()["fields"]
        paths = {f["field_path"] for f in fields}
        assert "workouts.swolfScore" in paths
        assert "metrics.steps.qty" not in paths

        entry = next(f for f in fields if f["field_path"] == "workouts.swolfScore")
        assert entry["occurrences"] == 4
        assert entry["connector_name"] == "Phone"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_report_never_carries_a_value():
    """The whole design rests on this: shapes, not payloads.

    Storing values would be a second copy of the most sensitive data in the system,
    with its own retention question — and would make account deletion incomplete
    unless it hunted that copy down too.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            source_id = await _connector(ac, tenant_id)
            await ac.post(
                f"/api/v1/internal/data/sources/{source_id}/field-report",
                json={
                    "unmapped": [
                        {
                            "path": "metrics.heart_rate.Avg",
                            "kind": "number",
                            "occurrences": 1,
                            # A client that tries to smuggle one in gets it dropped:
                            # the model has no such field.
                            "value": 61.5,
                        }
                    ]
                },
                headers=service_headers(tenant_id),
            )
            listed = await ac.get(
                "/api/v1/data/quality/unsupported-fields", headers=auth_headers(tenant_id)
            )

        entry = next(
            f for f in listed.json()["fields"] if f["field_path"] == "metrics.heart_rate.Avg"
        )
        assert "value" not in entry
        assert set(entry) == {
            "source_id", "source_type", "connector_name", "field_path",
            "value_kind", "occurrences", "first_seen_at", "last_seen_at",
        }
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_field_that_becomes_supported_stops_being_reported():
    """The regression net: fixing a transformer must empty this list for that field."""
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            source_id = await _connector(ac, tenant_id)
            url = f"/api/v1/internal/data/sources/{source_id}/field-report"

            # Before the fix: seen, not stored.
            await ac.post(
                url,
                json={"unmapped": [
                    {"path": "metrics.heart_rate.Avg", "kind": "number", "occurrences": 10}
                ]},
                headers=service_headers(tenant_id),
            )
            # After: the same path now becomes a metric.
            await ac.post(
                url,
                json={"mapped": [
                    {"path": "metrics.heart_rate.Avg", "kind": "number",
                     "occurrences": 10, "metric_type": "heart_rate"}
                ]},
                headers=service_headers(tenant_id),
            )

            listed = await ac.get(
                "/api/v1/data/quality/unsupported-fields", headers=auth_headers(tenant_id)
            )

        paths = {f["field_path"] for f in listed.json()["fields"]}
        assert "metrics.heart_rate.Avg" not in paths
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_reports_do_not_cross_tenants():
    """Verifies Fizzbee Invariant: TenantIsolation"""
    transport = ASGITransport(app=app)
    mine = await create_test_tenant()
    theirs = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            source_id = await _connector(ac, mine)
            await ac.post(
                f"/api/v1/internal/data/sources/{source_id}/field-report",
                json={"unmapped": [
                    {"path": "workouts.swolfScore", "kind": "number", "occurrences": 1}
                ]},
                headers=service_headers(mine),
            )
            listed = await ac.get(
                "/api/v1/data/quality/unsupported-fields", headers=auth_headers(theirs)
            )

        assert listed.json()["fields"] == []
    finally:
        await cleanup_test_tenant(mine)
        await cleanup_test_tenant(theirs)


@pytest.mark.asyncio
async def test_two_sightings_of_one_path_are_merged_not_rejected():
    """`ON CONFLICT DO UPDATE` cannot touch one row twice in a statement.

    Duplicates used to fail the whole request with an unhandled 500. The endpoint
    must not depend on the collector happening to deduplicate — that is a property
    of one client, not a guarantee.
    """
    transport = ASGITransport(app=app)
    tenant_id = await create_test_tenant()

    try:
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            source_id = await _connector(ac, tenant_id)
            posted = await ac.post(
                f"/api/v1/internal/data/sources/{source_id}/field-report",
                json={
                    "unmapped": [
                        {"path": "workouts.swolfScore", "kind": "number", "occurrences": 3},
                        {"path": "workouts.swolfScore", "kind": "number", "occurrences": 4},
                    ]
                },
                headers=service_headers(tenant_id),
            )
            assert posted.status_code == 202, posted.text

            listed = await ac.get(
                "/api/v1/data/quality/unsupported-fields", headers=auth_headers(tenant_id)
            )

        entry = next(
            f for f in listed.json()["fields"] if f["field_path"] == "workouts.swolfScore"
        )
        assert entry["occurrences"] == 7
    finally:
        await cleanup_test_tenant(tenant_id)
