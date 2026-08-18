"""Uploading the Whoop export in parts.

The mechanism is shared with every other file importer (`shared_schemas.upload_spool`,
whose own tests cover the offset rules), so what is checked here is that this service
wires it up: parts reassemble into the archive its parser reads, and the import that
follows is the same one a single request would have produced.

Maps to Fizzbee Invariants:
- TenantIsolationEnforced
- NoDuplicateRecords
"""

import asyncio
import io
import os
import zipfile
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from whoop_importer.core_client import UploadTarget
from whoop_importer.web import _spool_request, _uploads, app

app.state.testing = True
client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "99999999-9999-9999-9999-999999999999"
SOURCE = "22222222-2222-2222-2222-222222222222"

AUTH = {"Authorization": "Bearer session-token"}


class _StreamingRequest:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def stream(self):
        for chunk in self.chunks:
            yield chunk

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


@pytest.mark.asyncio
async def test_single_request_body_is_streamed_to_a_private_spool():
    """The direct route uses the same bounded disk spool as chunked uploads."""
    from whoop_importer import web

    chunks = [b"first", b" second", b" third"]
    session = await _spool_request(_StreamingRequest(chunks), TENANT, SOURCE)
    try:
        assert session.path.read_bytes() == b"".join(chunks)
        if os.name != "nt":
            # NTFS has no POSIX mode bits: `os.chmod` sets read-only and nothing
            # else, so this reads 0o666 however the spool was created. The spool
            # is no less private there — `%LOCALAPPDATA%\Temp` is already scoped
            # to the user by inherited ACLs — but the property cannot be stated
            # this way, and asserting it anyway made the suite permanently red on
            # a Windows checkout. The importer only ever runs on Linux.
            assert session.path.stat().st_mode & 0o777 == 0o600
    finally:
        session.path.unlink(missing_ok=True)
        assert not any(item.source_id == SOURCE for item in web._uploads.sessions())


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
    assert done.json()["received"] == len(payload)
    assert done.json()["points_expected"] is None
    # The run is opened when the archive is complete, not when the session opened: a
    # run open for the length of an upload marks the connector busy for that long.
    assert mock_open.await_count == 1


@pytest.mark.asyncio
@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
async def test_the_assembled_file_does_not_outlive_the_import(mock_session, mock_target):
    """A Whoop export is somebody's history; the spool is not where it lives.

    Driven through `httpx` in this test's own event loop rather than `TestClient`,
    and the import is *awaited*. `/upload/complete` answers 202 the moment the
    background task exists — deletion is that task's job, so a bare assertion after
    the response was reading a file the importer had not finished with. `TestClient`
    tears its loop down with the response, which cancelled the import mid-read; the
    assertion then depended on whether cleanup won that race, and on Windows it lost
    and left the export on disk. A test for "the archive does not survive the import"
    has to let the import happen.
    """
    from whoop_importer import web

    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")

    payload = _archive()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        begin = await ac.post(f"/upload/begin?source_id={SOURCE}", headers=AUTH)
        upload_id = begin.json()["upload_id"]
        await ac.post(
            f"/upload/chunk?upload_id={upload_id}&offset=0", content=payload, headers=AUTH
        )
        spooled = _uploads.session(upload_id, TENANT).path
        assert spooled.exists()

        with (
            patch("whoop_importer.web.open_sync_run", new_callable=AsyncMock) as mock_open,
            patch("whoop_importer.web.report_sync_progress", new_callable=AsyncMock),
            patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock),
        ):
            mock_open.return_value = "run-2"
            accepted = await ac.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)
            assert accepted.status_code == 202
            # The handler hands the archive to a task and returns. That task is what
            # owns the file from here on, so this is the thing to wait for.
            await asyncio.gather(*tuple(web._running_imports), return_exceptions=True)

    assert not spooled.exists()


@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_target_lookup_failure_still_removes_the_finished_archive(mock_session, mock_target):
    """A finished upload remains disposable even when its connector disappeared."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")

    payload = _archive()
    upload_id = client.post(f"/upload/begin?source_id={SOURCE}", headers=AUTH).json()[
        "upload_id"
    ]
    client.post(f"/upload/chunk?upload_id={upload_id}&offset=0", content=payload, headers=AUTH)
    spooled = _uploads.session(upload_id, TENANT).path
    mock_target.side_effect = HTTPException(status_code=404, detail="Connector not found")

    completed = client.post(f"/upload/complete?upload_id={upload_id}", headers=AUTH)

    assert completed.status_code == 404
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
