"""Uploading an `export.zip` in parts.

The single-request route (`test_upload_endpoint.py`) is the right shape for a script and
the wrong one for a browser: Cloudflare refuses a request body over 100 MB at the edge,
so a whole-history export never reached this service at all. These tests cover the shape
that does — a session, parts at explicit offsets, then "that was everything" — and the
properties that make it as safe as the one request it replaces.

Maps to Fizzbee Invariants:
- TenantIsolationEnforced
- NoDuplicateRecords
"""

import io
import zipfile
from unittest.mock import AsyncMock, patch

from apple_health_importer.client import UploadTarget
from apple_health_importer.main import _uploads, app
from fastapi import HTTPException
from fastapi.testclient import TestClient

app.state.testing = True
client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "99999999-9999-9999-9999-999999999999"
SOURCE = "22222222-2222-2222-2222-222222222222"

AUTH = {"Authorization": "Bearer session-token"}

EXPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_GB">
 <Record type="HKQuantityTypeIdentifierStepCount" sourceName="iPhone" unit="count"
         startDate="2026-08-05 06:00:00 +0200" endDate="2026-08-05 07:00:00 +0200" value="1240"/>
</HealthData>
"""


def _archive() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("apple_health_export/export.xml", EXPORT_XML)
    return buffer.getvalue()


def _begin(total: int | None = None) -> str:
    query = f"/upload/begin?source_id={SOURCE}"
    if total is not None:
        query += f"&total_bytes={total}"
    response = client.post(query, headers=AUTH)
    assert response.status_code == 201, response.text
    return response.json()["upload_id"]


def test_a_session_cannot_be_opened_without_one():
    """The importer sits on an internal network; a bare header is not a credential."""
    assert client.post(f"/upload/begin?source_id={SOURCE}").status_code == 401
    assert client.post("/upload/chunk?upload_id=x&offset=0", content=b"abc").status_code == 401
    assert client.post("/upload/complete?upload_id=x").status_code == 401


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_the_server_names_the_part_size(mock_session, mock_target):
    """A client that hardcoded the limit would need redeploying when a proxy changes."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")

    body = client.post(f"/upload/begin?source_id={SOURCE}", headers=AUTH).json()

    assert body["chunk_bytes"] > 0
    # Small enough to pass the strictest hop in front of this service.
    assert body["chunk_bytes"] <= 100 * 1024 * 1024
    assert body["received"] == 0


@patch("apple_health_importer.main.open_sync_run", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_parts_reassemble_into_an_archive_the_importer_reads(mock_session, mock_target, mock_open):
    """The end of the session is the start of an import, run id and all."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")
    mock_open.return_value = "run-1"

    payload = _archive()
    upload_id = _begin(len(payload))
    middle = len(payload) // 2

    first = client.post(
        f"/upload/chunk?upload_id={upload_id}&offset=0", content=payload[:middle], headers=AUTH
    )
    assert first.status_code == 200, first.text
    assert first.json()["received"] == middle

    second = client.post(
        f"/upload/chunk?upload_id={upload_id}&offset={middle}",
        content=payload[middle:],
        headers=AUTH,
    )
    assert second.json()["received"] == len(payload)

    with patch("apple_health_importer.main._import_archive", new_callable=AsyncMock) as mock_import:
        done = client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert done.status_code == 202, done.text
    assert done.json()["sync_run_id"] == "run-1"
    assert done.json()["received"] == len(payload)
    mock_import.assert_awaited_once()
    # The run belongs to the import, not to the upload: opening it when the session
    # opened would have shown an import that imports nothing for as long as a browser
    # takes to send, and Core's scheduler would have treated the connector as busy.
    assert mock_open.await_count == 1


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_target_lookup_failure_still_removes_the_finished_archive(mock_session, mock_target):
    """A finished upload remains disposable even when its connector disappeared."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")

    upload_id = _begin()
    client.post(
        f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abc", headers=AUTH
    )
    spooled = _uploads.session(upload_id, TENANT).path
    mock_target.side_effect = HTTPException(status_code=404, detail="Connector not found")

    completed = client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert completed.status_code == 404
    assert not spooled.exists()


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_a_part_that_arrives_twice_is_refused_with_the_offset_that_is_wanted(
    mock_session, mock_target
):
    """The retry of a request whose response was lost must not append twice."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")

    upload_id = _begin()
    client.post(f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abcdef", headers=AUTH)

    repeat = client.post(
        f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abcdef", headers=AUTH
    )

    assert repeat.status_code == 409
    assert repeat.json()["expected_offset"] == 6


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_an_unfinished_upload_cannot_be_completed(mock_session, mock_target):
    """A truncated archive is not an import; the response says where to continue."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")

    upload_id = _begin(64)
    client.post(f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abc", headers=AUTH)

    early = client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert early.status_code == 409
    assert early.json()["expected_offset"] == 3


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_an_archive_larger_than_this_importer_accepts_is_refused_before_it_is_sent(
    mock_session, mock_target
):
    """A quarter of an hour of uploading is a poor way to learn a file is too large."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")

    refused = client.post(
        f"/upload/begin?source_id={SOURCE}&total_bytes={_uploads.max_bytes + 1}", headers=AUTH
    )

    assert refused.status_code == 413


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_a_session_is_invisible_to_another_workspace(mock_session, mock_target):
    """AGENTS.md rule 2: another tenant's upload id is not an upload that exists."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")
    upload_id = _begin()

    mock_session.return_value = OTHER_TENANT
    stolen = client.post(
        f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abc", headers=AUTH
    )
    completed = client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert stolen.status_code == 404
    assert completed.status_code == 404


@patch("apple_health_importer.main.resolve_upload_target", new_callable=AsyncMock)
@patch("apple_health_importer.main.resolve_session", new_callable=AsyncMock)
def test_cancelling_deletes_the_parts_that_arrived(mock_session, mock_target):
    """Health data goes when the user says so, not at the next sweep."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "apple_health")

    upload_id = _begin()
    client.post(f"/upload/chunk?upload_id={upload_id}&offset=0", content=b"abc", headers=AUTH)
    spooled = _uploads.session(upload_id, TENANT).path

    aborted = client.post(f"/upload/abort?upload_id={upload_id}", headers=AUTH)

    assert aborted.status_code == 200
    assert not spooled.exists()
    # Aborting twice is the same intent, not an error the client has to handle.
    assert client.post(f"/upload/abort?upload_id={upload_id}", headers=AUTH).status_code == 200
