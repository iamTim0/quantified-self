"""Uploading the emailed Whoop export through the importer's own endpoint.

`test_export_archive.py` covers what the CSVs mean. What matters here is the boundary:
who may upload, into which connector, and what the history shows while it happens.

Maps to Fizzbee Invariants:
- TenantIsolationEnforced
- NoDuplicateRecords
"""

import io
import json
import zipfile
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from whoop_importer import web
from whoop_importer.core_client import UploadTarget
from whoop_importer.web import _import_archive, _publish, app

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


def _many_cycles(rows: int) -> str:
    lines = [
        "Cycle start time,Day Strain,Energy burned (cal),Average HR (bpm),Recovery score %"
    ]
    for index in range(rows):
        day = index // 24 + 1
        hour = index % 24
        lines.append(f"2026-08-{day:02d} {hour:02d}:00:00,14.2,2450,62,71")
    return "\n".join(lines) + "\n"


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
    with patch.object(web.app.state, "nats_client", _FakeNats(), create=True):
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "qs-importer-whoop"
    assert payload["version"]
    assert payload["commit"]
    assert response.headers["cache-control"] == "no-store"


def test_an_upload_without_a_session_is_refused():
    """The importer sits on an internal network; a bare header is not a credential."""
    response = client.post(f"/upload?source_id={SOURCE}", content=_archive())
    assert response.status_code == 401


@patch("whoop_importer.web.open_sync_run", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_upload_target", new_callable=AsyncMock)
@patch("whoop_importer.web.resolve_session", new_callable=AsyncMock)
def test_an_upload_is_accepted_without_counting_points_up_front(
    mock_session, mock_target, mock_open
):
    """Acceptance does not require materialising the archive to count its points."""
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
    assert body["received"] > 0
    assert body["points_expected"] is None


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
def test_a_file_that_is_not_a_whoop_export_says_so(
    mock_close, mock_open, mock_session, mock_target
):
    """A wrong file becomes a failed run instead of blocking the upload response."""
    mock_session.return_value = TENANT
    mock_target.return_value = UploadTarget(TENANT, SOURCE, "whoop")
    mock_open.return_value = "run-invalid"

    response = client.post(
        f"/upload?source_id={SOURCE}",
        content=_archive({"holiday.txt": "not a csv"}),
        headers={"Authorization": "Bearer session-token"},
    )

    assert response.status_code == 202
    assert response.json()["sync_run_id"] == "run-invalid"


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


@pytest.mark.asyncio
@patch("whoop_importer.web.send_field_report", new_callable=AsyncMock)
@patch("whoop_importer.web.report_sync_progress", new_callable=AsyncMock)
@patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock)
async def test_archive_publishing_never_exceeds_the_configured_batch(
    mock_close, mock_progress, mock_report, tmp_path
):
    """A whole-history archive is transformed and published in bounded batches."""
    path = tmp_path / "whoop-export.zip"
    path.write_bytes(_archive({"physiological_cycles.csv": _many_cycles(300)}))
    fake = _FakeNats()
    batch_sizes: list[int] = []
    original_publish_events = web._publish_events

    async def record_batch_size(js, events, **kwargs):
        batch_sizes.append(len(events))
        return await original_publish_events(js, events, **kwargs)

    with patch.object(web, "_publish_events", side_effect=record_batch_size):
        await _import_archive(
            path,
            nc=fake,
            tenant_id=TENANT,
            source_id=SOURCE,
            sync_run_id="run-bounded",
            req_id="req-bounded",
        )

    assert batch_sizes
    assert max(batch_sizes) <= web.PUBLISH_BATCH_SIZE
    assert len(batch_sizes) > 1
    assert len(fake.js.published) == len(batch_sizes)
    assert sum(len(json.loads(payload)["events"]) for _, payload in fake.js.published) == 1_200
    assert all(json.loads(payload)["schema_version"] == 2 for _, payload in fake.js.published)
    assert not path.exists()
    assert mock_close.await_args.kwargs["status"] == "idle"
    assert mock_close.await_args.kwargs["points_received"] == 1_200
    assert mock_progress.await_args.kwargs["points_received"] == 1_200
    mock_report.assert_awaited_once()


@pytest.mark.asyncio
@patch("whoop_importer.web.send_field_report", new_callable=AsyncMock)
@patch("whoop_importer.web.close_sync_run", new_callable=AsyncMock)
async def test_broker_loss_does_not_mark_a_real_import_as_successful(
    mock_close, mock_report, tmp_path
):
    """A disconnected production broker closes the run as an error, never as a dry run."""
    path = tmp_path / "whoop-export.zip"
    path.write_bytes(_archive())

    await _import_archive(
        path,
        nc=None,
        tenant_id=TENANT,
        source_id=SOURCE,
        sync_run_id="run-broker-loss",
        req_id="req-broker-loss",
    )

    assert not path.exists()
    assert mock_close.await_args.kwargs["status"] == "error"
    assert mock_close.await_args.kwargs["points_received"] == 0
    mock_report.assert_awaited_once()
