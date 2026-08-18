"""The worker that computes queued insight runs off the request path.

Maps to Fizzbee Invariants:
- ReportSingleFlight
- ReportNeverServesFutureData
"""

from __future__ import annotations

import pytest
from analysis import report_worker
from analysis.core_client import CoreRejected, CoreUnavailable, DueAnalysisReport


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


@pytest.mark.asyncio
async def test_a_refused_run_is_recorded_instead_of_retried_forever(monkeypatch):
    """The opposite decision to the test above, for the opposite condition.

    Both were `CoreUnavailable` until now, because every gRPC status became that one
    exception. So an INVALID_ARGUMENT — a deterministic refusal of a call that would
    be identical on the next attempt — took the "leave it in flight" branch. The run
    expired, the next tick claimed it again, and one over-strict metric-count limit
    produced eighty-five identical failures across seven days with no error code ever
    stored and a dashboard that said "temporarily unavailable" throughout.

    The assertion is that something is *written*: a refusal Core can record is a
    refusal a reader can see, and it stops the run being claimed again.
    """
    fake = _FakeCore([])
    monkeypatch.setattr(report_worker, "core_client", fake)

    async def refused(*_args, **_kwargs):
        raise CoreRejected("Core gRPC metric series query failed: INVALID_ARGUMENT")

    monkeypatch.setattr("analysis.main.build_insights_bundle", refused)

    # Does not raise: unlike an unreachable Core, this one can be told.
    await report_worker._compute_one(_run("run-refused"))

    assert len(fake.written) == 1
    assert fake.written[0]["payload"] is None
    # A code of its own, because "try again later" and "this cannot succeed as
    # configured" call for different actions from whoever reads it.
    assert fake.written[0]["error_code"] == "insights_rejected"


def test_a_permanent_status_is_not_reported_as_unavailability():
    """The classifier, directly: the name of the exception has to be true.

    `CoreRejected` is deliberately not a subclass of `CoreUnavailable`, so this also
    asserts that the retry branches cannot catch it by accident — which is exactly how
    the original conflation survived.
    """
    import grpc
    from analysis.core_client import _PERMANENT_STATUSES, _rpc_failure

    class _Err(grpc.aio.AioRpcError):
        def __init__(self, code: grpc.StatusCode) -> None:
            self._code = code

        def code(self):
            return self._code

        def details(self):
            return "at most 100 metric types"

    assert isinstance(_rpc_failure(_Err(grpc.StatusCode.INVALID_ARGUMENT), "x"), CoreRejected)
    assert isinstance(_rpc_failure(_Err(grpc.StatusCode.UNAVAILABLE), "x"), CoreUnavailable)
    # A just-expired service credential produces UNAUTHENTICATED and the next call
    # carries a fresh one, so it is precisely a retry that helps.
    assert isinstance(_rpc_failure(_Err(grpc.StatusCode.UNAUTHENTICATED), "x"), CoreUnavailable)
    assert isinstance(
        _rpc_failure(_Err(grpc.StatusCode.RESOURCE_EXHAUSTED), "x"), CoreUnavailable
    )
    assert not issubclass(CoreRejected, CoreUnavailable)
    assert grpc.StatusCode.UNAUTHENTICATED not in _PERMANENT_STATUSES
