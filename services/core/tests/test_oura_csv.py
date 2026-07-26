"""Tests for the Oura CSV import normalization layer."""

from datetime import timezone

import pytest

from core.db.tenant import set_current_tenant_id
from core.main import OuraCsvUploadRequest, import_oura_csv
from core.oura_csv import CsvImportValidationError, make_idempotency_key, parse_oura_csv


class _ScalarResult:
    def scalars(self):
        return self

    def first(self):
        return None


class _WriteResult:
    rowcount = 1


class _CsvImportSession:
    """Minimal isolated session double for the upload endpoint."""

    def __init__(self):
        self.added = []
        self.committed = False

    async def execute(self, statement):
        if statement.is_insert:
            return _WriteResult()
        return _ScalarResult()

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.committed = True


def test_oura_csv_normalizes_native_export_columns():
    """Verifies Fizzbee Invariant: CsvUploadDataIntegrity."""
    points = parse_oura_csv(
        "day,score,contributors\n2026-07-25,87,good\n",
        default_metric_type="sleep_score",
    )

    assert len(points) == 1
    assert points[0].timestamp.tzinfo == timezone.utc
    assert points[0].metric_type == "sleep_score"
    assert points[0].value == 87.0
    assert points[0].metadata == {"contributors": "good"}


def test_oura_csv_rejects_rows_without_a_numeric_value():
    """Verifies Fizzbee Invariant: CsvUploadDataIntegrity."""
    with pytest.raises(CsvImportValidationError, match="non-numeric"):
        parse_oura_csv("timestamp,value\n2026-07-25T00:00:00Z,unknown\n", "sleep_score")


def test_oura_csv_idempotency_key_is_deterministic():
    """Verifies Fizzbee Invariant: CsvUploadNoDuplicateData."""
    point = parse_oura_csv("date,value\n2026-07-25,87\n", "sleep_score")[0]

    first = make_idempotency_key("tenant-1", "source-1", point.metric_type, point.timestamp)
    second = make_idempotency_key("tenant-1", "source-1", point.metric_type, point.timestamp)

    assert first == second
    assert len(first) == 64


@pytest.mark.asyncio
async def test_oura_csv_import_is_tenant_scoped():
    """Verifies Fizzbee Invariant: CsvUploadTenantIsolation."""
    session = _CsvImportSession()
    tenant_id = "00000000-0000-0000-0000-000000000001"
    set_current_tenant_id(tenant_id)
    response = await import_oura_csv(
        OuraCsvUploadRequest(
            file_name="oura-sleep.csv",
            csv_content="day,score\n2026-07-25,87\n",
            default_metric_type="sleep_score",
        ),
        session,
    )

    assert response["inserted"] == 1
    assert session.added[0].tenant_id == tenant_id
    assert session.added[0].source_type == "oura_csv"
    assert session.committed
