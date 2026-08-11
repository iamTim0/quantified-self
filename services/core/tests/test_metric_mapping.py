"""Phase 8 tests for deferred ingestion and tenant-scoped mapping rules."""

import json
from datetime import date, datetime, timezone

import pytest
from core.analytics import detect_daily_gaps
from core.db.models import DataPoint, MetricMappingRule, QuarantinedDataPoint
from core.db.session import async_session_maker
from core.events.consumer import bounded_point_metadata, process_message
from core.main import _quarantine_capacity_warning, app
from httpx import ASGITransport, AsyncClient
from shared_schemas import idempotency_key
from shared_schemas.metrics import Aggregation, Cadence, MetricUnit
from sqlalchemy import select

from tests.db_helpers import auth_headers, cleanup_test_tenant, create_test_tenant

app.state.testing = True


class DummyMsg:
    def __init__(self, payload: dict):
        self.data = json.dumps(payload).encode("utf-8")
        self.acked = False
        self.terminated = False
        self.metadata = type("Meta", (), {"num_delivered": 1})()

    async def ack(self):
        self.acked = True

    async def term(self):
        self.terminated = True


async def _connector(tenant_id: str, display_name: str = "Phone") -> str:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        response = await ac.post(
            "/api/v1/data/sources/configure",
            json={"source_type": "apple_health", "display_name": display_name, "status": "active"},
            headers=auth_headers(tenant_id),
        )
    assert response.status_code == 200, response.text
    return response.json()["source_id"]


@pytest.mark.asyncio
async def test_unknown_event_is_quarantined_and_mapping_replays_it():
    """Verifies Fizzbee Invariant: APointHasOneTerminalOutcome."""
    tenant_id = await create_test_tenant()
    source_id = await _connector(tenant_id)
    timestamp = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    logical_source_id = f"{source_id}_event_123"
    event = {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "idempotency_source_id": logical_source_id,
        "source_type": "apple_health",
        "metric_type": "stepsInExportLanguage",
        "timestamp": timestamp.isoformat(),
        "value": 1234,
        "metadata": {"provider_value": 1234, "units": "count"},
        "idempotency_key": idempotency_key(
            tenant_id, logical_source_id, "stepsInExportLanguage", timestamp
        ),
    }

    try:
        message = DummyMsg(event)
        await process_message(message)
        assert message.acked is True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            quarantine = await ac.get(
                "/api/v1/data/quality/quarantine", headers=auth_headers(tenant_id)
            )
            assert quarantine.status_code == 200, quarantine.text
            assert quarantine.json()["metrics"][0]["raw_metric_type"] == "stepsInExportLanguage"
            capacity = quarantine.json()["capacity"]
            assert capacity[0]["active_rows"] == 1
            assert capacity[0]["active_names"] == 1
            assert capacity[0]["warning_code"] == "quarantine_has_pending"

            resolved = await ac.post(
                "/api/v1/data/quality/mapping-rules",
                json={
                    "source_id": source_id,
                    "raw_metric_type": "stepsInExportLanguage",
                    "action": "map",
                    "target_metric_type": "steps",
                    "source_unit": "count",
                    "target_unit": "count",
                },
                headers=auth_headers(tenant_id),
            )
            assert resolved.status_code == 202, resolved.text
            assert resolved.json()["accepted"] == 1
            assert resolved.json()["sync_run_id"]

        async with async_session_maker() as session:
            points = (
                await session.execute(
                    select(DataPoint).where(
                        DataPoint.tenant_id == tenant_id,
                        DataPoint.source_id == source_id,
                    )
                )
            ).scalars().all()
            held = (
                await session.execute(
                    select(QuarantinedDataPoint).where(
                        QuarantinedDataPoint.tenant_id == tenant_id,
                        QuarantinedDataPoint.source_id == source_id,
                    )
                )
            ).scalars().all()
        assert len(points) == 1
        assert points[0].metric_type == "steps"
        assert points[0].value == 1234
        assert points[0].idempotency_key == idempotency_key(
            tenant_id, logical_source_id, "steps", timestamp
        )
        assert points[0].metadata_["provider_value"] == 1234
        assert held[0].status == "promoted"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_mapping_rules_do_not_cross_tenants():
    """Verifies Fizzbee Invariant: ResolutionKeepsTenant."""
    mine = await create_test_tenant()
    theirs = await create_test_tenant()
    mine_source = await _connector(mine)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/data/quality/mapping-rules",
                json={
                    "source_id": mine_source,
                    "raw_metric_type": "private_metric",
                    "action": "keep",
                },
                headers=auth_headers(theirs),
            )
        assert response.status_code == 404
        async with async_session_maker() as session:
            rules = (
                await session.execute(
                    select(MetricMappingRule).where(MetricMappingRule.tenant_id == theirs)
                )
            ).scalars().all()
        assert rules == []
    finally:
        await cleanup_test_tenant(mine)
        await cleanup_test_tenant(theirs)


@pytest.mark.asyncio
async def test_mapping_changes_require_an_administrator():
    """A member may inspect quality, but cannot change the tenant's data semantics."""
    tenant_id = await create_test_tenant()
    source_id = await _connector(tenant_id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            response = await ac.post(
                "/api/v1/data/quality/mapping-rules",
                json={
                    "source_id": source_id,
                    "raw_metric_type": "member_attempted_mapping",
                    "action": "keep",
                },
                headers=auth_headers(tenant_id, role="member"),
            )
        assert response.status_code == 403
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_one_custom_metric_name_cannot_have_two_definitions():
    """Verifies the one-name-one-unit invariant for adopted tenant metrics."""
    tenant_id = await create_test_tenant()
    first_source = await _connector(tenant_id)
    second_source = await _connector(tenant_id, display_name="Second Phone")
    payload = {
        "action": "adopt",
        "target_metric_type": "custom_shared_score",
        "source_unit": "count",
        "target_unit": "count",
        "aggregation": "sum",
        "cadence": "daily",
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
            first = await ac.post(
                "/api/v1/data/quality/mapping-rules",
                json={**payload, "source_id": first_source, "raw_metric_type": "first_name"},
                headers=auth_headers(tenant_id),
            )
            second = await ac.post(
                "/api/v1/data/quality/mapping-rules",
                json={
                    **payload,
                    "source_id": second_source,
                    "raw_metric_type": "second_name",
                    "aggregation": "average",
                },
                headers=auth_headers(tenant_id),
            )
        assert first.status_code == 202, first.text
        assert second.status_code == 409, second.text
    finally:
        await cleanup_test_tenant(tenant_id)


def test_adoption_requires_a_dynamic_name_and_declared_shape():
    """Adoption cannot redefine a registry key or create an untyped custom metric."""
    from core.metric_mapping import validate_mapping

    with pytest.raises(ValueError, match="custom_"):
        validate_mapping(
            raw_metric_type="provider_metric",
            action="adopt",
            target_metric_type="provider_metric",
            source_unit="count",
            target_unit="count",
            aggregation="sum",
            cadence="daily",
        )


@pytest.mark.parametrize(
    ("active_rows", "active_names", "refused_occurrences", "expected"),
    [
        (1, 1, 0, "quarantine_has_pending"),
        (50_000, 10, 0, "quarantine_half_full"),
        (10, 50, 0, "quarantine_half_full"),
        (10, 75, 0, "quarantine_near_full"),
        (100_000, 10, 0, "quarantine_full"),
        (10, 100, 0, "quarantine_full"),
        (1, 1, 1, "quarantine_values_refused"),
    ],
)
def test_quarantine_capacity_warning_escalates_at_both_limits(
    active_rows: int,
    active_names: int,
    refused_occurrences: int,
    expected: str,
):
    """The UI warning level follows the stricter per-connector quarantine limit."""
    warning_code, _ = _quarantine_capacity_warning(
        active_rows=active_rows,
        active_names=active_names,
        refused_occurrences=refused_occurrences,
    )

    assert warning_code == expected


def test_large_metadata_keeps_provenance_without_archiving_the_payload():
    """The quarantine stores point provenance, never an attacker-sized raw payload."""
    from core.events.consumer import MAX_POINT_METADATA_BYTES

    compact = bounded_point_metadata(
        {"provider_value": 12, "units": "count", "payload": "x" * MAX_POINT_METADATA_BYTES},
        12,
    )

    assert compact == {
        "provider_value": 12,
        "units": "count",
        "metadata_truncated": True,
    }


def test_adopted_custom_definition_controls_gap_detection():
    """Tenant-declared cadence must be used instead of the dynamic EVENT default."""
    from core.metric_mapping import custom_metric_definition, validate_mapping

    mapping = validate_mapping(
        raw_metric_type="provider_daily_score",
        action="adopt",
        target_metric_type="custom_daily_score",
        source_unit="count",
        target_unit="count",
        aggregation="last",
        cadence="daily",
    )
    definition = custom_metric_definition(mapping)
    gaps = detect_daily_gaps(
        [("custom_daily_score", datetime(2026, 8, 10, tzinfo=timezone.utc))],
        date(2026, 8, 10),
        date(2026, 8, 11),
        cadence_overrides={"custom_daily_score": definition.cadence},
    )

    assert definition.unit is MetricUnit.COUNT
    assert definition.aggregation is Aggregation.LAST
    assert definition.cadence is Cadence.DAILY
    assert gaps == [{"metric_type": "custom_daily_score", "missing_dates": ["2026-08-11"]}]
    with pytest.raises(ValueError, match="target_unit"):
        validate_mapping(
            raw_metric_type="provider_metric",
            action="adopt",
            target_metric_type="custom_provider_metric",
            source_unit="count",
            aggregation="sum",
            cadence="daily",
        )
