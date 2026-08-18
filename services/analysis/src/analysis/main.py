"""Analysis Service.

A reader. It computes correlations, trends, anomalies, routines and period
comparisons, and it obtains every input through Core's gRPC API. It holds no
database connection, no SQLAlchemy import and no database URL -- AGENTS.md rules
1 and 3.

This used to be a 22-line placeholder that returned
`{"message": "Correlation analysis results."}` and was in neither compose file,
while the real analyses ran inside Core and were served over REST from there.
The statistics are unchanged; what moved is where they run and how they get data.

Tenant resolution follows the same rule as everywhere else: the tenant comes from
the validated Bearer token, never from a client-supplied header. The Gateway
verifies the user's JWT and forwards it; this service re-validates rather than
trusting the hop, for the same reason Core stopped trusting X-Tenant-ID.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from shared_schemas import health_payload

from analysis.auth import resolve_tenant
from analysis.chat_api import codex
from analysis.chat_api import router as chat_router
from analysis.config import settings
from analysis.core_client import (
    CoreClient,
    CoreRejected,
    CoreUnavailable,
    MetricSeriesBucket,
    MetricSeriesResponse,
)
from analysis.insights import (
    Provenance,
    compare_periods,
    correlation_pairs,
    detect_anomalies,
    lagged_correlations,
    series_quality,
    strength_progression,
    trend_for_metric,
    weekday_pattern,
)
from analysis.mcp_server import mcp_asgi_app
from analysis.report_worker import run_report_worker, worker_enabled

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-analysis] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# This service re-validates the user's Bearer token itself rather than trusting
# the Gateway hop, so it holds the same JWT_SECRET and inherits the same problem:
# the secret has a default that is printed in this repository, and a process
# started without one would verify real sessions against a value anyone can read.
#
# Duplicated rather than imported from Core: the two services share no code by
# design (AGENTS.md rule 6), and the check is a dozen lines. Core and the Gateway
# carry the same one -- `core.security.secret_audit` explains why the compose
# `${VAR:?}` guard is not enough on its own: it only covers `docker compose up`,
# not every other way a process gets launched.
PUBLISHED_DEFAULTS = {
    "dev-secret-key-quantified-self-2026",
    "dev-secret-shared-encryption-key-qs-2026",
    "dev-encryption-key-quantified-self-2026",
}
PRODUCTION_ENVIRONMENTS = {"production", "prod", "staging"}


def audit_secrets() -> None:
    """Refuse to serve in production with a published JWT_SECRET; warn otherwise.

    Raises:
        RuntimeError: in a production-like ENVIRONMENT.
    """
    if settings.JWT_SECRET and settings.JWT_SECRET not in PUBLISHED_DEFAULTS:
        return

    detail = (
        "JWT_SECRET is unset or a value published in this repository. Generate "
        'one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
    )
    if settings.ENVIRONMENT.strip().lower() in PRODUCTION_ENVIRONMENTS:
        raise RuntimeError(f"analysis refuses to start: {detail}")
    logger.warning("[analysis] insecure default in use: %s", detail)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the mounted MCP transport manager with the Analysis application.

    Checked at startup, not at import: the test suite imports this module without
    starting it, and an import-time check would refuse to load it at all.
    """
    audit_secrets()
    async with mcp_asgi_app.lifespan():
        # The insights bundle is computed here but scheduled by Core, which owns
        # the sync history that says when a tenant's data has changed. The worker
        # claims that queued work over the same gRPC contract this service
        # already reads through. See `analysis.report_worker`.
        worker_task = (
            asyncio.create_task(run_report_worker()) if worker_enabled() else None
        )
        try:
            yield
        finally:
            if worker_task is not None:
                worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await worker_task
            await codex.close()


app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)
app.include_router(chat_router)

core_client = CoreClient()


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"


def build_daily_series(
    buckets: list[MetricSeriesBucket],
) -> dict[str, dict[str, float]]:
    """Convert Core's daily buckets into the pure-analysis series shape."""
    series: dict[str, dict[str, float]] = {}
    for bucket in buckets:
        if bucket.value is None or bucket.sample_count == 0:
            continue
        day = bucket.bucket_start.astimezone(UTC).date().isoformat()
        series.setdefault(bucket.metric_type, {})[day] = float(bucket.value)
    return series


@app.get("/health")
async def health_check(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return health_payload(settings.SERVICE_NAME)


@app.get("/api/v1/analysis/insights")
async def get_insights(
    request: Request,
    days: int = Query(90, ge=14, le=365, description="Analysis window in days"),
    metric_type: str | None = Query(
        None, description="Restrict trends/anomalies to one metric"
    ),
    min_strength: float = Query(
        0.0, ge=0.0, le=1.0, description="Minimum |coefficient|"
    ),
    compare_to_previous: bool = Query(
        False,
        description="Also compare the window with the equally long window before it",
    ),
    source_id: str | None = Query(
        None,
        description="Restrict analysis to one connector instance",
    ),
    tenant_id: str = Depends(resolve_tenant),
) -> dict[str, Any]:
    """Full analysis bundle for one caller's parameters, computed now.

    The dashboard does not use this: it reads the scheduled run through Core's
    `/api/v1/data/reports/insights`, which is this same bundle computed once per
    data change. This endpoint stays because the parameters are real — a caller
    may ask for a window, a metric or a connector the scheduled run did not.
    """
    try:
        return await build_insights_bundle(
            tenant_id,
            days=days,
            metric_type=metric_type,
            min_strength=min_strength,
            compare_to_previous=compare_to_previous,
            source_id=source_id,
            request_id=_request_id(request),
        )
    except CoreUnavailable as exc:
        # 503, not an empty result set: "no correlations found" and "we could not
        # read the data" must not look the same to the dashboard.
        raise HTTPException(
            status_code=503, detail="Analysis data is temporarily unavailable"
        ) from exc
    except CoreRejected as exc:
        # Not a 503. Core is up and answered; it refused what this service asked
        # for, so "temporarily" would be a lie and a reader who waits waits forever.
        # 500 because the wrong request is ours to fix, and logged at error level
        # because nothing else about this condition is loud.
        logger.error("[req_id=%s] Core refused the insights request: %s", _request_id(request), exc)
        raise HTTPException(
            status_code=500, detail="Analysis could not be computed for this workspace"
        ) from exc


async def build_insights_bundle(
    tenant_id: str,
    *,
    days: int = 90,
    metric_type: str | None = None,
    min_strength: float = 0.0,
    compare_to_previous: bool = False,
    source_id: str | None = None,
    request_id: str,
) -> dict[str, Any]:
    """Full analysis bundle for a tenant, with provenance on every result.

    One function rather than several because the analyses share the same aligned
    daily series; recomputing it per call would be wasteful and could return
    mutually inconsistent windows.

    Called both by the HTTP endpoint above and by the background worker in
    `analysis.report_worker`, so that a scheduled bundle and an ad-hoc one cannot
    drift apart — there is one implementation and two ways to reach it.

    Everything reported is an *association*. Nothing here establishes causation,
    and analyses whose input is too thin are omitted rather than shown weakly.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(days=days)

    try:
        series_response = await core_client.fetch_metric_series(
            tenant_id,
            start=window_start,
            end=now,
            request_id=request_id,
            source_id=source_id,
        )
        source_map = await core_client.fetch_source_map(
            tenant_id,
            request_id=request_id,
        )
    except CoreUnavailable:
        # Raised on, not translated here. This function has two callers and only
        # one of them is an HTTP request: turning an unreachable Core into a 503
        # in here meant the background worker could never recognise the condition
        # it has a branch for, so it wrote every run back as a permanent failure
        # and hammered a Core that was merely restarting. The HTTP concern belongs
        # at the HTTP edge — see `get_insights`.
        logger.warning("[req_id=%s] Core unavailable while building insights", request_id)
        raise

    # A canonical metric can be reported by several connector instances. Core
    # returns those source series separately and marks the metric ambiguous. Do
    # not merge them here: summing two step counters would produce a plausible,
    # wrong value, and averaging two overlapping sensors would change the sample
    # weighting without the reader being able to tell.
    if isinstance(series_response, MetricSeriesResponse):
        buckets = series_response.buckets
        source_issues = [
            {
                "code": issue.code,
                "metric_type": issue.metric_type,
                "source_ids": list(issue.source_ids),
                "primary_source_id": issue.primary_source_id,
                "primary_reason": issue.primary_reason,
            }
            for issue in series_response.issues
        ]
    else:
        # Keep test doubles and older in-process callers readable during a
        # rolling deployment where the new response wrapper is not available.
        buckets = series_response
        source_issues = []

    # A metric several connectors report is answered by one of them, not dropped.
    #
    # Dropping was the safe half of a correct observation: the two series must not
    # be merged, because adding two step counters double counts and averaging two
    # overlapping sensors reweights the samples invisibly. But "do not merge" does
    # not imply "do not answer" — it implies "say which one". Core makes that
    # choice, because it holds the tenant's stated preference and the coverage
    # figures the choice needs, and names it in `primary_source_id`.
    #
    # A metric stays excluded only when Core named no primary — an older Core that
    # does not send the field. Picking one here would be a guess, and a guess about
    # which of two step counters is real is exactly the wrong thing to hide.
    primary_by_metric = {
        issue["metric_type"]: issue["primary_source_id"]
        for issue in source_issues
        if issue["code"] == "AMBIGUOUS_METRIC_SOURCE" and issue.get("primary_source_id")
    }
    unresolved_metrics = {
        issue["metric_type"]
        for issue in source_issues
        if issue["code"] == "AMBIGUOUS_METRIC_SOURCE"
        and not issue.get("primary_source_id")
    }
    usable_buckets = [
        bucket
        for bucket in buckets
        if bucket.metric_type not in unresolved_metrics
        and (
            bucket.metric_type not in primary_by_metric
            or bucket.source_id == primary_by_metric[bucket.metric_type]
        )
    ]
    series = build_daily_series(usable_buckets)
    selected_source_ids: dict[str, list[str]] = {}
    for bucket in usable_buckets:
        if bucket.value is not None and bucket.sample_count > 0 and bucket.source_id:
            selected_source_ids.setdefault(bucket.metric_type, [])
            if bucket.source_id not in selected_source_ids[bucket.metric_type]:
                selected_source_ids[bucket.metric_type].append(bucket.source_id)

    contributing_source_types = sorted(
        {
            source_map.get(source_id, "unknown")
            for source_ids in selected_source_ids.values()
            for source_id in source_ids
        }
    )

    provenance = Provenance(
        computed_at=now.isoformat(),
        window_start=window_start.isoformat(),
        window_end=now.isoformat(),
        sources=contributing_source_types,
    )

    quality = {
        metric: series_quality(daily, days, metric)
        for metric, daily in sorted(series.items())
    }
    # Analyses only run on series with a defensible amount of data.
    usable = {m: d for m, d in series.items() if quality[m]["sufficient"]}

    correlations = [
        c for c in correlation_pairs(usable) if abs(c["coefficient"]) >= min_strength
    ]

    trends: dict[str, Any] = {}
    anomalies: dict[str, Any] = {}
    routines: dict[str, Any] = {}
    for metric, daily in usable.items():
        if metric_type and metric != metric_type:
            continue
        ordered_days = sorted(daily)
        values = [daily[d] for d in ordered_days]
        if (trend := trend_for_metric(ordered_days, values)) is not None:
            trends[metric] = trend
        if (anomaly := detect_anomalies(daily)) is not None:
            anomalies[metric] = anomaly
        if (routine := weekday_pattern(daily)) is not None:
            routines[metric] = routine

    comparisons: dict[str, Any] = {}
    if compare_to_previous:
        mid = now - timedelta(days=days // 2)
        earlier = (
            (now - timedelta(days=days)).date().isoformat(),
            mid.date().isoformat(),
        )
        later = (mid.date().isoformat(), now.date().isoformat())
        for metric, daily in usable.items():
            if metric_type and metric != metric_type:
                continue
            if (
                cmp := compare_periods(daily, period_a=earlier, period_b=later)
            ) is not None:
                comparisons[metric] = cmp

    excluded = sorted((set(series) - set(usable)) | unresolved_metrics)

    # Strength is asked for separately, because it is the one analysis whose
    # grouping key is a metadata field rather than a metric name. Core reads it
    # (rule 1) and hands over sets; the maths here is arithmetic over those rows.
    #
    # A failure to fetch is not a failure of the bundle: a workspace with no
    # resistance training is the common case, and a correlation report should not
    # disappear because a strength query did. `CoreUnavailable` still propagates —
    # the worker distinguishes "Core is restarting" from "this run failed", and
    # swallowing it here would make every run look successful during an outage.
    strength: dict[str, Any] = strength_progression([])
    try:
        strength_sets = await core_client.fetch_strength_sets(
            tenant_id,
            start=window_start,
            end=now,
            request_id=request_id,
            source_id=source_id,
        )
        strength = strength_progression(
            strength_sets.sets, truncated=strength_sets.truncated
        )
    except CoreUnavailable:
        raise
    except CoreRejected:
        # Swallowed on purpose, and loudly. A refused *strength* query is one
        # analysis failing, not the bundle: the correlations and trends are already
        # computed and a workspace with no resistance training is the common case.
        # Distinguished from the generic case below so the decision is written down
        # rather than inherited from whichever `except` happened to catch it.
        logger.exception("Core refused the strength query; bundle continues without it")
    except Exception:  # one analysis must not take the whole bundle down
        logger.warning("Strength progression could not be computed", exc_info=True)

    return {
        "tenant_id": tenant_id,
        "provenance": provenance.to_dict(),
        "disclaimer": (
            "Every result describes a statistical relationship, not cause and "
            "effect. None of it is medical advice."
        ),
        "metrics_analysed": sorted(usable),
        "metrics_excluded_for_quality": excluded,
        "metric_source_ids": selected_source_ids,
        "source_issues": source_issues,
        "data_quality": quality,
        "correlations": correlations,
        "lagged_correlations": lagged_correlations(usable),
        "trends": trends,
        "anomalies": anomalies,
        "routines": routines,
        "period_comparisons": comparisons,
        "strength": strength,
        "docs_url": "/docs/features/correlations/",
    }


# Keep the MCP app last so the service's ordinary FastAPI routes win before the
# catch-all mount delegates `/mcp` to the protocol implementation.
app.mount("/", mcp_asgi_app, name="mcp")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
