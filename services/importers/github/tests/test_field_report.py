"""Filing the field report, which is bookkeeping that must not fail an import.

Verifies:
- What goes on the wire is JSON, not a Pydantic model. Handing `httpx` the model
  raised a `TypeError` that the surrounding `except` logged as a warning, so every
  run filed nothing and said so once, quietly (rule 19)
- The unsupported-field count is read off the built report rather than off a dict
  it never was -- the `AttributeError` that failed the run *after* its points were
  already published
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Self

import pytest
from github_importer import main as importer_main
from github_importer.sync_task import SyncTask
from shared_schemas.field_report import FieldReport, FieldReportCollector

TENANT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"


class _RecordingClient:
    """Stands in for `httpx.AsyncClient`, keeping whatever was posted."""

    posted: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, *, headers: dict[str, str], json: Any) -> None:
        type(self).posted.append({"url": url, "headers": headers, "json": json})


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingClient]:
    _RecordingClient.posted = []
    monkeypatch.setattr(importer_main.httpx, "AsyncClient", _RecordingClient)
    return _RecordingClient


def _task() -> SyncTask:
    return SyncTask(
        tenant_id=TENANT,
        source_id=SOURCE,
        source_type="github",
        request_id="req-1",
        sync_run_id="run-1",
    )


def _report() -> FieldReport:
    collector = FieldReportCollector()
    collector.mapped("contributionsCollection.code_commits", 3, "code_commits")
    collector.unmapped("repository.commit.additions", 12)
    return collector.build()


@pytest.mark.asyncio
async def test_the_report_goes_out_as_json(recorder: type[_RecordingClient]) -> None:
    await importer_main.publish_field_report(_task(), _report())

    assert len(recorder.posted) == 1
    payload = recorder.posted[0]["json"]
    # The whole defect in one assertion: a model here is a TypeError inside httpx,
    # and this `except` treats that as "Core was unreachable".
    json.dumps(payload)
    assert payload["sync_run_id"] == "run-1"
    assert [s["path"] for s in payload["unmapped"]] == ["repository.commit.additions"]
    assert [s["path"] for s in payload["mapped"]] == ["contributionsCollection.code_commits"]


@pytest.mark.asyncio
async def test_what_is_posted_is_what_core_accepts(recorder: type[_RecordingClient]) -> None:
    """Both ends of the contract, checked against the shared model."""
    await importer_main.publish_field_report(_task(), _report())

    payload = dict(recorder.posted[0]["json"])
    payload.pop("sync_run_id")
    assert FieldReport.model_validate(payload).unmapped[0].occurrences == 1


@pytest.mark.asyncio
async def test_the_report_is_addressed_to_the_connector(
    recorder: type[_RecordingClient],
) -> None:
    await importer_main.publish_field_report(_task(), _report())
    assert recorder.posted[0]["url"].endswith(f"/data/sources/{SOURCE}/field-report")


def test_the_unsupported_count_reads_the_built_report() -> None:
    """`len(built.unmapped)`, not `built.get("unmapped")` -- the latter is an
    AttributeError on a Pydantic model, raised after the points were published."""
    built = _report()
    assert len(built.unmapped) == 1
