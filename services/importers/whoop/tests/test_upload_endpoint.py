"""Uploading the emailed Whoop export through the importer's own endpoint.

`test_export_archive.py` covers what the CSVs mean. What matters here is the boundary:
who may upload, into which connector, and what the history shows while it happens.

Maps to Fizzbee Invariants:
- TenantIsolationEnforced
- NoDuplicateRecords
"""

import io
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from whoop_importer.core_client import UploadTarget
from whoop_importer.web import _publish, app

app.state.testing = True
client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"

CYCLES_CSV = (
    "Cycle start time,Day Strain,Energy burned (cal),Average HR (bpm),Recovery score %\n"
    "2026-08-05 06:00:00,14.2,2450,62,71\n"
)


def _archive(files: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, body in (files or {"physiological_cycles.csv": CYCLES_CSV}).items():
            archive.writestr(name, body)
    return buffer.getvalue()


class _FakeJetStream:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        self.published.append((subject, payload))


class _FakeNats:
    is_connected = True

    def __init__(self) -> None:
        self.js = _FakeJetStream()

    def jetstream(self) -> _FakeJetStream:
        return self.js


def test_health_check_reports_the_broker_connection():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "qs-importer-whoop"


def test_an_upload_without_a_session_is_refused():
    """The importer sits on an internal network; a bare header is not a credential."""
    response = client.post(f"/upload?source_id={SOURCE}", content=_archive())
    assert response.status_code == 401


@patch("whoop_importer.web.open_sync_run", new_callable=AsyncMock)
@patch("whoop_importer.web.report_sync_progress", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_an_upload_is_accepted_with_the_count_it_will_publish(
    mock_session, mock_target, mock_progress, mock_open
):
    """A CSV export is small enough to count up front, so the progress bar has a total."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")
    mock_open.return_value = "run-1"

    response = client.post(
        f"/upload?source_id={SOURCE}",
        content=_archive(),
        headers={"Authorization": "Bearer session-token"},
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["sync_run_id"] == "run-1"
    assert body["points_expected"] == mock_progress.await_args.kwargs["points_expected"] > 0


@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_a_connector_belonging_to_somebody_else_is_a_404(mock_session, mock_target):
    """Core resolves connectors inside one workspace; this endpoint repeats that verdict."""
    mock_session.return_value = TENANT
    mock_target.side_effect = HTTPException(status_code=404, detail="Connector not found.")

    response = client.post(
        f"/upload?source_id={SOURCE}",
        content=_archive(),
        headers={"Authorization": "Bearer session-token"},
    )
    assert response.status_code == 404


@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
@patch("whoop_importer.web.open_sync_run", new_callable=AsyncMock)
@patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock)
def test_a_file_that_is_not_a_whoop_export_says_so(mock_close, mock_open, mock_session, mock_target):
    """A wrong file is a mistake to correct, not a silent import of nothing."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")

    response = client.post(
        f"/upload?source_id={SOURCE}",
        content=_archive({"holiday.txt": "not a csv"}),
        headers={"Authorization": "Bearer session-token"},
    )

    assert response.status_code == 400
    assert "Whoop CSV" in response.json()["detail"]


@pytest.mark.asyncio
@patch("whoop_importer.web.send_field_report", new_callable=AsyncMock)
@patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock)
async def test_publishing_closes_the_run_with_what_it_sent(mock_close, mock_report):
    from shared_schemas import FieldReportCollector

    fake = _FakeNats()
    events = [{"tenant_id": TENANT, "metric_type": "whoop_strain", "value": 14.2}]

    await _publish(
        events,
        nc=fake,
        tenant_id=TENANT,
        source_id=SOURCE,
        sync_run_id="run-1",
        req_id="req-1",
        report=FieldReportCollector(),
    )

    assert [subject for subject, _ in fake.js.published] == ["qs.ingest.whoop"]
    assert mock_close.await_args.kwargs["status"] == "idle"
    assert mock_close.await_args.kwargs["points_received"] == 1
    mock_report.assert_awaited_once()


@pytest.mark.asyncio
@patch("whoop_importer.web.send_field_report", new_callable=AsyncMock)
@patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock)
async def test_a_broker_failure_mid_publish_reaches_the_history(mock_close, mock_report):
    """The response has already been sent, so the run is the only place left to say so."""
    from shared_schemas import FieldReportCollector

    class _Failing(_FakeNats):
        def jetstream(self):
            raise RuntimeError("broker gone")

    await _publish(
        [{"tenant_id": TENANT}],
        nc=_Failing(),
        tenant_id=TENANT,
        source_id=SOURCE,
        sync_run_id="run-1",
        req_id="req-1",
        report=FieldReportCollector(),
    )

    assert mock_close.await_args.kwargs["status"] == "error"
    mock_report.assert_not_awaited()
