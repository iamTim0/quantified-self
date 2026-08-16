"""Computes the insights bundle off the request path.

The bundle is a derivation over a tenant's whole window — paged reads from Core,
then correlations, lagged correlations, trends, anomalies, weekday patterns and
period comparisons in Python. It was recomputed on every page load, which meant
the cost of opening the analysis tab grew with the amount of data a workspace
held, and two readers opening it at once paid it twice for the same answer.

It is now computed once per data change. Core decides *when* — it owns the
sync history and can see that a tenant's data has moved on (`core.reports`) —
and queues a run. This worker claims the run, computes, and hands the result
back. Core stores it; the dashboard reads the stored run.

**Why a worker rather than Core calling this service.** Core may not compute the
bundle (rule 3: data science lives here) and this service may not store it
(rule 1: Core owns the database). The two constraints leave exactly one shape:
work is *pulled* over the gRPC contract the services already share, and pushed
back the same way. Nothing new is introduced — no HTTP between internal
services, no second broker connection, no database URL in this service.

**Failure is reported, not swallowed.** A run that raises is handed back with an
error code, and Core keeps serving the previous successful bundle rather than
showing an empty page. A run this worker never returns is timed out by Core
(`core.reports.STALE_RUN_AFTER`), so a crash here delays a report instead of
wedging one.

Maps to Fizzbee Invariants:
- ReportSingleFlight
- ReportNeverServesFutureData
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from analysis.config import settings
from analysis.core_client import CoreClient, CoreUnavailable, DueAnalysisReport

logger = logging.getLogger(__name__)

# Its own client, like every other module here. A `CoreClient` holds a target
# address and nothing else; the channel is opened per call.
core_client = CoreClient()

#: How often to ask Core for queued work when the last poll came back empty.
#: Not how often a report is computed — that follows the data. This only bounds
#: how late a manual refresh can feel.
IDLE_POLL_SECONDS = 15

#: How long to wait after Core could not be reached. Longer than the idle poll,
#: because a broker or a Core that is down is not helped by being asked faster.
BACKOFF_SECONDS = 60

#: Runs claimed per poll. Bounded because each one is a full bundle: claiming
#: fifty would hold them all in `running` while this worker computed them one at
#: a time, and Core would time out the tail.
CLAIM_LIMIT = 3


async def _compute_one(report: DueAnalysisReport) -> None:
    """Compute one claimed run and hand the outcome back to Core."""
    # Imported here rather than at module scope: `analysis.main` imports this
    # module to start the worker, so importing it back at load time would be a
    # cycle. The call itself is what matters, not when the name is bound.
    from analysis.main import build_insights_bundle

    params = report.params or {}
    request_id = report.request_id or f"report_{uuid.uuid4().hex[:12]}"

    try:
        bundle = await build_insights_bundle(
            report.tenant_id,
            days=int(params.get("days") or 90),
            metric_type=params.get("metric_type") or None,
            min_strength=float(params.get("min_strength") or 0.0),
            compare_to_previous=bool(params.get("compare_to_previous") or False),
            source_id=params.get("source_id") or None,
            request_id=request_id,
        )
    except CoreUnavailable as exc:
        # Core is the thing that would have to store the failure, so there is
        # nowhere to report it. Left in flight for Core's own timeout to fail.
        logger.warning("[req_id=%s] Core unavailable while computing: %s", request_id, exc)
        raise
    except Exception as exc:
        logger.exception("[req_id=%s] Insights run %s failed", request_id, report.run_id)
        await core_client.put_analysis_report(
            run_id=report.run_id,
            tenant_id=report.tenant_id,
            payload=None,
            error_code=f"insights_failed_{type(exc).__name__}"[:64],
            request_id=request_id,
        )
        return

    code = await core_client.put_analysis_report(
        run_id=report.run_id,
        tenant_id=report.tenant_id,
        payload=bundle,
        request_id=request_id,
    )
    if code != "STORED":
        # RUN_ALREADY_FINISHED is the ordinary case for a run Core timed out
        # while this was computing. Worth a line, not an alarm.
        logger.info(
            "[req_id=%s] Core did not store insights run %s: %s",
            request_id,
            report.run_id,
            code,
        )


async def run_report_worker(*, poll_seconds: int = IDLE_POLL_SECONDS) -> None:
    """Claim and compute queued insight runs. Cancelled by the caller on shutdown."""
    logger.info("Insights report worker started (poll=%ss)", poll_seconds)
    while True:
        try:
            request_id = f"reportpoll_{uuid.uuid4().hex[:12]}"
            claimed = await core_client.claim_due_analysis_reports(
                limit=CLAIM_LIMIT, request_id=request_id
            )
            if not claimed:
                await asyncio.sleep(poll_seconds)
                continue

            logger.info("Claimed %s insights run(s)", len(claimed))
            for report in claimed:
                # Sequential, not gathered: each bundle is CPU-bound Python on
                # this service's event loop, so running three at once would only
                # interleave them and make all three late.
                try:
                    await _compute_one(report)
                except CoreUnavailable:
                    break
        except asyncio.CancelledError:
            logger.info("Insights report worker stopped")
            raise
        except CoreUnavailable as exc:
            logger.warning("Core unreachable; retrying in %ss (%s)", BACKOFF_SECONDS, exc)
            await asyncio.sleep(BACKOFF_SECONDS)
        except Exception:
            # A worker that dies on one bad poll is worse than no worker: it
            # looks like it is running. Same reasoning as the sync scheduler.
            logger.exception("Report worker poll failed; continuing")
            await asyncio.sleep(BACKOFF_SECONDS)


def worker_enabled() -> bool:
    """Whether this process should run the worker.

    Off by default in a local checkout with no Core to talk to would be wrong —
    the poll simply fails and backs off. It is a setting so a deployment running
    several Analysis replicas can keep the work on one of them if it wants to;
    running it on all of them is safe, because claiming is single-flight.
    """
    return bool(getattr(settings, "REPORT_WORKER_ENABLED", True))
