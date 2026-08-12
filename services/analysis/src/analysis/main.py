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

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request

from analysis.auth import resolve_tenant
from analysis.chat_api import codex
from analysis.chat_api import router as chat_router
from analysis.config import settings
from analysis.core_client import CoreClient, CoreUnavailable, MetricPoint
from analysis.insights import (
    Provenance,
    compare_periods,
    correlation_pairs,
    detect_anomalies,
    lagged_correlations,
    series_quality,
    trend_for_metric,
    weekday_pattern,
)
from analysis.mcp_server import mcp_asgi_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [qs-analysis] [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the mounted MCP transport manager with the Analysis application."""
    async with mcp_asgi_app.lifespan():
        try:
            yield
        finally:
            await codex.close()


app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)
app.include_router(chat_router)

core_client = CoreClient()


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"


def build_daily_series(points: list[MetricPoint]) -> dict[str, dict[str, float]]:
    """Collapse points to one value per metric per day.

    Last write wins within a day, matching the previous in-Core behaviour: the
    metrics involved are daily summaries, so a day with several points is a
    re-import rather than genuinely finer resolution.
    """
    series: dict[str, dict[str, float]] = {}
    for point in sorted(points, key=lambda p: p.timestamp):
        series.setdefault(point.metric_type, {})[point.timestamp.date().isoformat()] = (
            float(point.value)
        )
    return series


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "service": settings.SERVICE_NAME}


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
    tenant_id: str = Depends(resolve_tenant),
) -> dict[str, Any]:
    """Full analysis bundle for the dashboard, with provenance on every result.

    One endpoint rather than several because the analyses share the same aligned
    daily series; recomputing it per call would be wasteful and could return
    mutually inconsistent windows.

    Everything reported is an *association*. Nothing here establishes causation,
    and analyses whose input is too thin are omitted rather than shown weakly.
    """
    request_id = _request_id(request)
    now = datetime.now(UTC)
    window_start = now - timedelta(days=days)

    try:
        points = await core_client.fetch_points(
            tenant_id, start=window_start, end=now, request_id=request_id
        )
        source_types = await core_client.fetch_source_types(
            tenant_id, request_id=request_id
        )
    except CoreUnavailable as exc:
        logger.warning("[req_id=%s] %s", request_id, exc)
        # 503, not an empty result set: "no correlations found" and "we could not
        # read the data" must not look the same to the dashboard.
        raise HTTPException(
            status_code=503, detail="Analysis data is temporarily unavailable"
        ) from exc

    series = build_daily_series([p for p in points if p.value is not None])

    provenance = Provenance(
        computed_at=now.isoformat(),
        window_start=window_start.isoformat(),
        window_end=now.isoformat(),
        sources=source_types,
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

    excluded = sorted(set(series) - set(usable))

    return {
        "tenant_id": tenant_id,
        "provenance": provenance.to_dict(),
        "disclaimer": (
            "Every result describes a statistical relationship, not cause and "
            "effect. None of it is medical advice."
        ),
        "metrics_analysed": sorted(usable),
        "metrics_excluded_for_quality": excluded,
        "data_quality": quality,
        "correlations": correlations,
        "lagged_correlations": lagged_correlations(usable),
        "trends": trends,
        "anomalies": anomalies,
        "routines": routines,
        "period_comparisons": comparisons,
        "docs_url": "/docs/features/correlations/",
    }


# Keep the MCP app last so the service's ordinary FastAPI routes win before the
# catch-all mount delegates `/mcp` to the protocol implementation.
app.mount("/", mcp_asgi_app, name="mcp")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
