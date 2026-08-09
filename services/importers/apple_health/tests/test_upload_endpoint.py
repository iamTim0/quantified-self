"""Uploading an `export.zip` through the importer's own endpoint.

What matters here is not the parsing — `test_export_archive.py` covers that — but the
boundary: who may upload, into which connector, and what the file leaves behind.

Maps to Fizzbee Invariants:
- TenantIsolationEnforced
- NoDuplicateRecords
"""

import io
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from apple_health_importer.client import UploadTarget
from apple_health_importer.main import _import_archive, app
from fastapi import HTTPException
from fastapi.testclient import TestClient

app.state.testing = True
client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"

EXPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_GB">
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count"
         startDate="2026-08-05 06:00:00 +0200" endDate="2026-08-05 07:00:00 +0200" value="1240"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Watch" unit="count/min"
         startDate="2026-08-05 06:30:00 +0200" endDate="2026-08-05 06:30:10 +0200" value="61"/>
</HealthData>
"""


def _spooled(content: bytes) -> str:
    """A file where the upload endpoint would have put one, for the reader to consume."""
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    handle.write(content)
    handle.close()
    return handle.name


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("apple_health_export/export.xml", EXPORT_XML)
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


def test_an_upload_without_a_session_is_refused():
    """The importer sits on an internal network; a bare header is not a credential."""
    response = client.post(f"/upload?source_id={SOURCE}", content=_archive())
    assert response.status_code == 401


@patch("apple_health_importer.main.open_sync_run", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_an_upload_is_accepted_and_opens_a_run(mock_session, mock_target, mock_open):
    """The response is the run to watch, not the result — the archive is read after it."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")
    mock_open.return_value = "run-1"

    response = client.post(
        f"/upload?source_id={SOURCE}",
        content=_archive(),
        headers={"Authorization": "Bearer session-token"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["sync_run_id"] == "run-1"
    # Opened before the response went out, so there is no window in which the upload
    # has been accepted and nothing in the interface says so.
    assert mock_open.await_count == 1


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
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


@pytest.mark.asyncio
@patch("apple_health_importer.main.send_field_report", new_callable=AsyncMock)
@patch("apple_health_importer.main.close_sync_run", new_callable=AsyncMock)
async def test_the_archive_is_published_then_deleted(mock_close, mock_report):
    """An archive is somebody's whole medical history; it lives on disk only to be read."""
    path = _spooled(_archive())

    fake = _FakeNats()
    with patch("apple_health_importer.main.nc_client", fake):
        await _import_archive(
            path, tenant_id=TENANT, source_id=SOURCE, sync_run_id="run-1", req_id="req-1"
        )

    subjects = {subject for subject, _ in fake.js.published}
    assert subjects == {"qs.ingest.apple_health"}
    assert len(fake.js.published) == 2
    assert not Path(path).exists()

    mock_close.assert_awaited_once()
    assert mock_close.await_args.kwargs["status"] == "idle"
    assert mock_close.await_args.kwargs["points_received"] == 2
    mock_report.assert_awaited_once()


@pytest.mark.asyncio
@patch("apple_health_importer.main.send_field_report", new_callable=AsyncMock)
@patch("apple_health_importer.main.close_sync_run", new_callable=AsyncMock)
async def test_an_unreadable_archive_closes_the_run_as_an_error(mock_close, mock_report):
    """A failure has to reach the history: the response has already been sent."""
    path = _spooled(b"this is not a zip")

    with patch("apple_health_importer.main.nc_client", _FakeNats()):
        await _import_archive(
            path, tenant_id=TENANT, source_id=SOURCE, sync_run_id="run-1", req_id="req-1"
        )

    assert mock_close.await_args.kwargs["status"] == "error"
    assert not Path(path).exists()
    mock_report.assert_not_awaited()
