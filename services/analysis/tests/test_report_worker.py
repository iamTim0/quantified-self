"""The worker that computes queued insight runs off the request path.

Maps to Fizzbee Invariants:
- ReportSingleFlight
- ReportNeverServesFutureData
"""

from __future__ import annotations

import pytest
from analysis import report_worker
from analysis.core_client import CoreUnavailable, DueAnalysisReport


class _FakeCore:
    """Records what the worker claimed and what it handed back."""

    def __init__(self, queued: list[DueAnalysisReport]) -> None:
        self._queued = list(queued)
        self.claims = 0
        self.written: list[dict[str, object]] = []

    async def claim_due_analysis_reports(self, *, limit, request_id):
        self.claims += 1
        taken, self._queued = self._queued[:limit], self._queued[limit:]
        return taken

    async def put_analysis_report(
        self, *, run_id, tenant_id, payload, request_id, error_code=""
    ):
        self.written.append(
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "payload": payload,
                "error_code": error_code,
            }
        )
        return "STORED"


def _run(run_id: str = "run-1", **params) -> DueAnalysisReport:
    return DueAnalysisReport(
        run_id=run_id,
        tenant_id="22222222-2222-2222-2222-222222222222",
        params=params,
        request_id="req_worker_test",
    )


@pytest.mark.asyncio
async def test_a_claimed_run_is_computed_and_handed_back(monkeypatch):
    """The bundle Core stores is the one this service computed for that run."""
    fake = _FakeCore([])
    monkeypatch.setattr(report_worker, "core_client", fake)

    seen: dict[str, object] = {}

    async def fake_bundle(tenant_id, **kwargs):
        seen.update({"tenant_id": tenant_id, **kwargs})
        return {"tenant_id": tenant_id, "correlations": []}

    monkeypatch.setattr("analysis.main.build_insights_bundle", fake_bundle)

    await report_worker._compute_one(_run(days=30, min_strength=0.2))

    # The run's stored parameters drive the computation, not a default.
    assert seen["days"] == 30
    assert seen["min_strength"] == 0.2
    assert len(fake.written) == 1
    assert fake.written[0]["run_id"] == "run-1"
    assert fake.written[0]["error_code"] == ""
    assert fake.written[0]["payload"]["correlations"] == []


@pytest.mark.asyncio
async def test_a_failing_run_is_reported_rather_than_swallowed(monkeypatch):
    """Core is told the run failed, so it keeps serving the last good bundle.

    A worker that simply dropped the failure would leave the run in flight until
    Core's timeout, which delays the next attempt by half an hour for no reason.
    """
    fake = _FakeCore([])
    monkeypatch.setattr(report_worker, "core_client", fake)

    async def exploding_bundle(*_args, **_kwargs):
        raise ValueError("not enough data")

    monkeypatch.setattr("analysis.main.build_insights_bundle", exploding_bundle)

    await report_worker._compute_one(_run("run-boom"))

    assert len(fake.written) == 1
    assert fake.written[0]["run_id"] == "run-boom"
    assert fake.written[0]["payload"] is None
    assert fake.written[0]["error_code"] == "insights_failed_ValueError"


@pytest.mark.asyncio
async def test_an_unreachable_core_leaves_the_run_for_its_timeout(monkeypatch):
    """Nothing is written when Core is the thing that is down.

    Core is where a failure would have to be recorded, so there is nowhere to
    report it. Raising leaves the run in flight for Core's own timeout, which is
    the only mechanism that can still act.
    """
    fake = _FakeCore([])
    monkeypatch.setattr(report_worker, "core_client", fake)

    async def unavailable(*_args, **_kwargs):
        raise CoreUnavailable("core is down")

    monkeypatch.setattr("analysis.main.build_insights_bundle", unavailable)

    with pytest.raises(CoreUnavailable):
        await report_worker._compute_one(_run("run-offline"))

    assert fake.written == []
