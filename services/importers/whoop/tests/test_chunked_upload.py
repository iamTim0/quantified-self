"""Uploading the Whoop export in parts.

The mechanism is shared with every other file importer (`shared_schemas.upload_spool`,
whose own tests cover the offset rules), so what is checked here is that this service
wires it up: parts reassemble into the archive its parser reads, and the import that
follows is the same one a single request would have produced.

Maps to Fizzbee Invariants:
- TenantIsolationEnforced
- NoDuplicateRecords
"""

import io
import zipfile
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from whoop_importer.core_client import UploadTarget
from whoop_importer.web import _uploads, app

app.state.testing = True
client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "99999999-9999-9999-9999-999999999999"
SOURCE = "22222222-2222-2222-2222-222222222222"

AUTH = {"Authorization": "Bearer session-token"}

CYCLES_CSV = (
    "Cycle start time,Day Strain,Energy burned (cal),Average HR (bpm),Recovery score %\n"
    "2026-08-05 06:00:00,14.2,2450,62,71\n"
)


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("physiological_cycles.csv", CYCLES_CSV)
    return buffer.getvalue()


def test_a_session_cannot_be_opened_without_one():
    assert client.post(f"/upload/begin?source_id={SOURCE}").status_code == 401
    assert client.post("/upload/chunk?upload_id=x&offset=0", content=b"abc").status_code == 401


@patch("whoop_importer.web.open_sync_run", new_callable=AsyncMock)
@patch("whoop_importer.web.report_sync_progress", new_callable=AsyncMock)
@patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_parts_reassemble_into_the_export_the_parser_reads(
    mock_session, mock_target, mock_close, mock_progress, mock_open
):
    """Two parts, one archive, and the same accepted response as one request gives."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")
    mock_open.return_value = "run-1"

    payload = _archive()
    middle = len(payload) // 2
    opened = client.post(
        f"/upload/begin?source_id={SOURCE}&total_bytes={len(payload)}", headers=AUTH
    )
    assert opened.status_code == 201, opened.text
    upload_id = opened.json()["upload_id"]

    client.post(
        f"/upload/chunk?upload_id={upload_id}&offset=0", content=payload[:middle], headers=AUTH
    )
    last = client.post(
        f"/upload/chunk?upload_id={upload_id}&offset={middle}",
        content=payload[middle:],
        headers=AUTH,
    )
    assert last.json()["received"] == len(payload)

    done = client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert done.status_code == 202, done.text
    assert done.json()["sync_run_id"] == "run-1"
    assert done.json()["points_expected"] > 0
    # The run is opened when the archive is complete, not when the session opened: a
    # run open for the length of an upload marks the connector busy for that long.
    assert mock_open.await_count == 1


@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_the_assembled_file_does_not_outlive_the_import(mock_session, mock_target):
    """A Whoop export is somebody's history; the spool is not where it lives."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")

    payload = _archive()
    upload_id = client.post(f"/upload/begin?source_id={SOURCE}", headers=AUTH).json()["upload_id"]
    client.post(f"/upload/chunk?upload_id={upload_id}&offset=0", content=payload, headers=AUTH)
    spooled = _uploads.session(upload_id, TENANT).path

    with (
        patch("whoop_importer.web.open_sync_run", new_callable=AsyncMock) as mock_open,
        patch("whoop_importer.web.report_sync_progress", new_callable=AsyncMock),
        patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock),
    ):
        mock_open.return_value = "run-2"
        client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert not spooled.exists()


@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_a_session_is_invisible_to_another_workspace(mock_session, mock_target):
    """AGENTS.md rule 2: another tenant's upload id is not an upload that exists."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")
    upload_id = client.post(f"/upload/begin?source_id={SOURCE}", headers=AUTH).json()["upload_id"]

    mock_session.return_value = OTHER_TENANT

    assert (
        client.post(
            f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abc", headers=AUTH
        ).status_code
        == 404
    )
    assert client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH).status_code == 404
