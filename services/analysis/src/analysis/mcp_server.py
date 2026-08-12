"""Stateless MCP 2026-07-28 surface for tenant-scoped personal analytics.

The protocol carries no identity in tool arguments and no session state between
requests. Each HTTP request is authenticated independently, and every data read
continues through Core's tenant-filtered gRPC API.
"""

from __future__ import annotations

import json
import math
import uuid
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from statistics import fmean
from typing import Annotated, Any, Literal

from fastapi import HTTPException
from mcp.server import MCPServer
from mcp.server.context import HandlerResult, ServerRequestContext
from mcp.server.mcpserver.context import Context
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CallToolResult,
    DiscoverResult,
    ServerCapabilities,
    TextContent,
    ToolAnnotations,
    ToolsCapability,
)
from pydantic import BaseModel, ConfigDict, Field
from shared_schemas.metrics import (
    Aggregation,
    Cadence,
    UnknownMetricTypeError,
    canonical_metric_type,
    describe,
)
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from analysis.auth import McpPrincipal, mcp_principal_resolver
from analysis.config import settings
from analysis.core_client import CoreClient, CoreUnavailable, MetricPoint, PointBatch
from analysis.insights import correlation_pairs, series_quality, trend_for_metric

PROTOCOL_VERSION = "2026-07-28"
MCP_PATH = "/mcp"
MAX_REQUEST_BODY_SIZE = 256 * 1024
MAX_WINDOW_DAYS = 365
DEFAULT_WINDOW_DAYS = 90
MAX_QUERY_SOURCE_POINTS = 100_000
MAX_ANALYSIS_SOURCE_POINTS = 50_000
ALLOWED_METHODS = frozenset({"server/discover", "tools/list", "tools/call"})

core_client = CoreClient()


class StrictModel(BaseModel):
    """Stable structured-output base with no undeclared response fields."""

    model_config = ConfigDict(extra="forbid")


class Provenance(StrictModel):
    schema_version: Literal["1"] = "1"
    request_id: str
    computed_at: datetime
    window_start: datetime
    window_end: datetime
    sources: list[str]
    point_count: int
    truncated: bool = False


class MetricCatalogItem(StrictModel):
    metric_type: str
    unit: str
    aggregation: str
    category: str
    cadence: str
    label: str
    observed_count: int
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None


class ListMetricsResult(StrictModel):
    metrics: list[MetricCatalogItem]
    provenance: Provenance


class SeriesPoint(StrictModel):
    timestamp: datetime
    value: float


class MetricSeriesResult(StrictModel):
    metric_type: str
    unit: str
    aggregation: str
    bucket: Literal["raw", "hour", "day", "week"]
    points: list[SeriesPoint]
    provenance: Provenance


class AnalyzeMetricsResult(StrictModel):
    metric_types: list[str]
    summaries: dict[str, dict[str, Any]]
    trends: dict[str, dict[str, Any]]
    correlations: list[dict[str, Any]]
    disclaimer: str
    provenance: Provenance


class MetricQuality(StrictModel):
    metric_type: str
    unit: str
    observed_points: int
    observed_days: int
    window_days: int
    coverage_pct: float
    cadence: str
    sufficient: bool
    missing_expected_days: int | None
    plausible_outlier_count: int
    source_point_counts: dict[str, int]
    note: str


class DataQualityResult(StrictModel):
    metrics: list[MetricQuality]
    provenance: Provenance


READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

mcp_server = MCPServer(
    "quantified-self-analysis",
    description="Read-only, tenant-scoped personal metric queries and deterministic analysis.",
    version="1.0.0",
)


async def _limit_advertised_capabilities(
    ctx: ServerRequestContext, call_next: Any
) -> HandlerResult:
    """Keep discovery aligned with the modern-only routing allowlist."""
    result = await call_next(ctx)
    is_tool_error = (isinstance(result, CallToolResult) and result.is_error) or (
        isinstance(result, dict)
        and bool(result.get("isError", result.get("is_error", False)))
    )
    if ctx.method == "tools/call" and is_tool_error:
        request_id = "unknown"
        if ctx.request is not None:
            request_id = ctx.request.headers.get("x-request-id") or request_id
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"code": "INTERNAL_TOOL_ERROR", "request_id": request_id}
                    ),
                )
            ],
            is_error=True,
        )
    if ctx.method == "server/discover" and isinstance(result, DiscoverResult):
        return result.model_copy(
            update={
                "capabilities": ServerCapabilities(
                    tools=ToolsCapability(list_changed=False)
                )
            }
        )
    if ctx.method == "server/discover" and isinstance(result, dict):
        return {
            **result,
            "capabilities": ServerCapabilities(
                tools=ToolsCapability(list_changed=False)
            ).model_dump(by_alias=True, exclude_none=True),
        }
    return result


mcp_server.middleware.append(_limit_advertised_capabilities)


def _request_context(ctx: Context) -> tuple[McpPrincipal, str]:
    request = ctx.request_context.request
    if request is None:
        raise MCPError(
            -32001, "Authentication required", {"code": "AUTHENTICATION_REQUIRED"}
        )
    state = request.scope.get("state", {})
    principal = state.get("mcp_principal")
    if not isinstance(principal, McpPrincipal):
        raise MCPError(
            -32001, "Authentication required", {"code": "AUTHENTICATION_REQUIRED"}
        )
    headers = request.headers
    request_id = headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"
    return principal, request_id


def _window(start: datetime | None, end: datetime | None) -> tuple[datetime, datetime]:
    finish = end or datetime.now(UTC)
    begin = start or (finish - timedelta(days=DEFAULT_WINDOW_DAYS))
    if begin.tzinfo is None or finish.tzinfo is None:
        raise MCPError(
            -32602,
            "Timestamps must include a timezone",
            {"code": "TIMEZONE_REQUIRED"},
        )
    begin = begin.astimezone(UTC)
    finish = finish.astimezone(UTC)
    if begin >= finish:
        raise MCPError(
            -32602, "start must be before end", {"code": "INVALID_TIME_RANGE"}
        )
    if finish - begin > timedelta(days=MAX_WINDOW_DAYS):
        raise MCPError(
            -32602,
            f"Time range must not exceed {MAX_WINDOW_DAYS} days",
            {"code": "TIME_RANGE_TOO_LARGE", "max_days": MAX_WINDOW_DAYS},
        )
    return begin, finish


def _metric_definition(metric_type: str):
    if metric_type != metric_type.strip():
        raise MCPError(
            -32602,
            "Metric type must not contain padding whitespace",
            {"code": "INVALID_METRIC_NAME", "metric_type": metric_type},
        )
    raw = metric_type
    try:
        canonical = canonical_metric_type(raw)
    except UnknownMetricTypeError as exc:
        raise MCPError(
            -32602,
            "Unknown metric type",
            {"code": "UNKNOWN_METRIC_TYPE", "metric_type": raw},
        ) from exc
    if canonical != raw:
        raise MCPError(
            -32602,
            "Metric aliases cannot be queried; use the canonical name",
            {
                "code": "CANONICAL_METRIC_REQUIRED",
                "metric_type": raw,
                "canonical_metric_type": canonical,
            },
        )
    return describe(canonical)


async def _sources(tenant_id: str, request_id: str) -> list[str]:
    try:
        return await core_client.fetch_source_types(tenant_id, request_id=request_id)
    except CoreUnavailable as exc:
        raise MCPError(
            -32000,
            "Analysis data is temporarily unavailable",
            {"code": "CORE_UNAVAILABLE"},
        ) from exc


async def _points(
    principal: McpPrincipal,
    request_id: str,
    *,
    start: datetime,
    end: datetime,
    metric_type: str | None,
    max_points: int,
) -> PointBatch:
    try:
        batch = await core_client.fetch_points_bounded(
            principal.tenant_id,
            start=start,
            end=end,
            request_id=request_id,
            metric_type=metric_type,
            max_points=max_points,
        )
    except CoreUnavailable as exc:
        raise MCPError(
            -32000,
            "Analysis data is temporarily unavailable",
            {"code": "CORE_UNAVAILABLE"},
        ) from exc
    if batch.truncated:
        raise MCPError(
            -32003,
            "The source result is too large; request a shorter time range",
            {"code": "SOURCE_RESULT_TOO_LARGE", "max_source_points": max_points},
        )
    return batch


def _result_unit(points: list[MetricPoint], definition: Any) -> str:
    if not definition.is_dynamic:
        # metadata.units is the provider's pre-conversion unit. Stored values
        # are already in the registry unit, so labelling them with provider
        # units would make a correct value appear wrong.
        return definition.unit.value
    units = {
        str(point.metadata.get("units"))
        for point in points
        if point.metadata.get("units") not in (None, "")
    }
    return units.pop() if len(units) == 1 else definition.unit.value


def _bucket_start(timestamp: datetime, bucket: str) -> datetime:
    stamp = timestamp.astimezone(UTC)
    if bucket == "hour":
        return stamp.replace(minute=0, second=0, microsecond=0)
    day = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    return day


def _reduce_points(points: list[MetricPoint], aggregation: Aggregation) -> float:
    if aggregation is Aggregation.SUM:
        return float(sum(point.value for point in points))
    if aggregation is Aggregation.MAX:
        return float(max(point.value for point in points))
    if aggregation is Aggregation.LAST:
        return float(max(points, key=lambda point: point.timestamp).value)
    return float(fmean(point.value for point in points))


def _reduce_values(values: list[float], aggregation: Aggregation) -> float:
    if aggregation is Aggregation.SUM:
        return float(sum(values))
    if aggregation is Aggregation.MAX:
        return float(max(values))
    if aggregation is Aggregation.LAST:
        return float(values[-1])
    return float(fmean(values))


def _series_points(
    points: list[MetricPoint],
    *,
    bucket: Literal["raw", "hour", "day", "week"],
    definition: Any,
    max_points: int,
) -> tuple[list[SeriesPoint], bool]:
    ordered = sorted(points, key=lambda point: point.timestamp)
    if bucket == "raw":
        result = [
            SeriesPoint(timestamp=point.timestamp, value=point.value)
            for point in ordered
        ]
    elif bucket == "hour":
        if definition.cadence is Cadence.DAILY:
            raise MCPError(
                -32602,
                "Daily metrics cannot be bucketed by hour",
                {"code": "HOURLY_BUCKETING_UNSUPPORTED", "metric_type": definition.key},
            )
        grouped: dict[datetime, list[MetricPoint]] = defaultdict(list)
        for point in ordered:
            grouped[_bucket_start(point.timestamp, bucket)].append(point)
        result = [
            SeriesPoint(
                timestamp=timestamp,
                value=round(_reduce_points(group, definition.aggregation), 6),
            )
            for timestamp, group in sorted(grouped.items())
        ]
    else:
        daily = _daily_values(ordered, definition)
        daily_points = [
            SeriesPoint(
                timestamp=datetime.fromisoformat(day).replace(tzinfo=UTC),
                value=value,
            )
            for day, value in sorted(daily.items())
        ]
        if bucket == "day":
            result = daily_points
        else:
            weekly: dict[datetime, list[float]] = defaultdict(list)
            for series_point in daily_points:
                weekly[_bucket_start(series_point.timestamp, "week")].append(
                    series_point.value
                )
            result = [
                SeriesPoint(
                    timestamp=timestamp,
                    value=round(_reduce_values(values, definition.aggregation), 6),
                )
                for timestamp, values in sorted(weekly.items())
            ]

    if len(result) <= max_points:
        return result, False
    # Deterministic display sampling preserves both endpoints. Aggregated values
    # are never recomputed from this sample, so a SUM metric cannot be double-counted.
    step = (len(result) - 1) / (max_points - 1)
    indexes = sorted({round(index * step) for index in range(max_points)})
    return [result[index] for index in indexes], True


def _daily_values(points: list[MetricPoint], definition: Any) -> dict[str, float]:
    grouped: dict[str, list[MetricPoint]] = defaultdict(list)
    for point in points:
        grouped[point.timestamp.astimezone(UTC).date().isoformat()].append(point)
    if definition.cadence is Cadence.DAILY:
        # Daily summaries imported twice or reported by overlapping connectors
        # represent the same quantity. Last-write-wins matches the established
        # Analysis endpoint and avoids summing a day twice.
        return {
            day: round(max(day_points, key=lambda point: point.timestamp).value, 6)
            for day, day_points in sorted(grouped.items())
        }
    return {
        day: round(_reduce_points(day_points, definition.aggregation), 6)
        for day, day_points in sorted(grouped.items())
    }


def _provenance(
    *,
    request_id: str,
    start: datetime,
    end: datetime,
    sources: list[str],
    point_count: int,
    truncated: bool,
) -> Provenance:
    return Provenance(
        request_id=request_id,
        computed_at=datetime.now(UTC),
        window_start=start,
        window_end=end,
        sources=sources,
        point_count=point_count,
        truncated=truncated,
    )


@mcp_server.tool(
    name="list_metrics",
    description="List metric types present for the authenticated user and their canonical units.",
    annotations=READ_ONLY,
    structured_output=True,
)
async def list_metrics(
    ctx: Context,
    start: datetime | None = None,
    end: datetime | None = None,
    search: Annotated[str | None, Field(max_length=128)] = None,
    limit: Annotated[int, Field(ge=1, le=200)] = 100,
) -> ListMetricsResult:
    """List only metrics observed inside the caller's tenant."""
    principal, request_id = _request_context(ctx)
    begin, finish = _window(start, end)
    batch = await _points(
        principal,
        request_id,
        start=begin,
        end=finish,
        metric_type=None,
        max_points=MAX_QUERY_SOURCE_POINTS,
    )
    by_metric: dict[str, list[MetricPoint]] = defaultdict(list)
    for point in batch.points:
        by_metric[point.metric_type].append(point)

    needle = (search or "").strip().lower()
    selected = [
        name for name in sorted(by_metric) if not needle or needle in name.lower()
    ][:limit]

    metrics: list[MetricCatalogItem] = []
    for metric_type in selected:
        definition = _metric_definition(metric_type)
        observed = sorted(by_metric[metric_type], key=lambda point: point.timestamp)
        metrics.append(
            MetricCatalogItem(
                metric_type=metric_type,
                unit=_result_unit(observed, definition),
                aggregation=(
                    "runtime" if definition.is_dynamic else definition.aggregation.value
                ),
                category=definition.category.value,
                cadence=definition.cadence.value,
                label=definition.label_en,
                observed_count=len(observed),
                first_observed_at=observed[0].timestamp if observed else None,
                last_observed_at=observed[-1].timestamp if observed else None,
            )
        )

    sources = await _sources(principal.tenant_id, request_id)
    return ListMetricsResult(
        metrics=metrics,
        provenance=_provenance(
            request_id=request_id,
            start=begin,
            end=finish,
            sources=sources,
            point_count=len(batch.points),
            truncated=batch.truncated,
        ),
    )


@mcp_server.tool(
    name="query_metric_series",
    description="Return a chart-ready time series for one canonical metric.",
    annotations=READ_ONLY,
    structured_output=True,
)
async def query_metric_series(
    metric_type: Annotated[str, Field(min_length=1, max_length=128)],
    ctx: Context,
    start: datetime | None = None,
    end: datetime | None = None,
    bucket: Literal["raw", "hour", "day", "week"] = "day",
    max_points: Annotated[int, Field(ge=2, le=2000)] = 500,
) -> MetricSeriesResult:
    """Query one bounded metric series with registry-correct aggregation."""
    principal, request_id = _request_context(ctx)
    begin, finish = _window(start, end)
    definition = _metric_definition(metric_type)
    if definition.is_dynamic and bucket != "raw":
        raise MCPError(
            -32602,
            "Dynamic metrics can be queried only as raw points",
            {"code": "DYNAMIC_METRIC_REQUIRES_RAW", "metric_type": metric_type},
        )
    batch = await _points(
        principal,
        request_id,
        start=begin,
        end=finish,
        metric_type=metric_type,
        max_points=MAX_QUERY_SOURCE_POINTS,
    )
    series, sampled = _series_points(
        batch.points,
        bucket=bucket,
        definition=definition,
        max_points=max_points,
    )
    sources = await _sources(principal.tenant_id, request_id)
    return MetricSeriesResult(
        metric_type=metric_type,
        unit=_result_unit(batch.points, definition),
        aggregation="runtime"
        if definition.is_dynamic
        else definition.aggregation.value,
        bucket=bucket,
        points=series,
        provenance=_provenance(
            request_id=request_id,
            start=begin,
            end=finish,
            sources=sources,
            point_count=len(batch.points),
            truncated=batch.truncated or sampled,
        ),
    )


@mcp_server.tool(
    name="analyze_metrics",
    description="Compute deterministic summaries, trends, and correlations for canonical metrics.",
    annotations=READ_ONLY,
    structured_output=True,
)
async def analyze_metrics(
    metric_types: Annotated[list[str], Field(min_length=1, max_length=10)],
    ctx: Context,
    start: datetime | None = None,
    end: datetime | None = None,
    analyses: Annotated[
        tuple[Literal["summary", "trend", "correlation"], ...],
        Field(min_length=1, max_length=3),
    ] = ("summary", "trend", "correlation"),
) -> AnalyzeMetricsResult:
    """Analyze tenant data without producing diagnoses or causal claims."""
    principal, request_id = _request_context(ctx)
    begin, finish = _window(start, end)
    unique_metrics = list(dict.fromkeys(metric_types))
    definitions = {name: _metric_definition(name) for name in unique_metrics}
    dynamic = [
        name for name, definition in definitions.items() if definition.is_dynamic
    ]
    if dynamic:
        raise MCPError(
            -32602,
            "Dynamic metrics have no registry aggregation and cannot be analysed",
            {"code": "DYNAMIC_METRIC_ANALYSIS_UNAVAILABLE", "metric_types": dynamic},
        )
    batches: dict[str, PointBatch] = {}
    daily: dict[str, dict[str, float]] = {}
    for name in unique_metrics:
        batch = await _points(
            principal,
            request_id,
            start=begin,
            end=finish,
            metric_type=name,
            max_points=MAX_ANALYSIS_SOURCE_POINTS,
        )
        batches[name] = batch
        daily[name] = _daily_values(batch.points, definitions[name])

    requested = set(analyses)
    summaries: dict[str, dict[str, Any]] = {}
    trends: dict[str, dict[str, Any]] = {}
    if "summary" in requested:
        for name, values_by_day in daily.items():
            ordered = sorted(values_by_day.items())
            values = [value for _, value in ordered]
            summaries[name] = {
                "unit": _result_unit(batches[name].points, definitions[name]),
                "sample_size": len(values),
                "minimum": round(min(values), 6) if values else None,
                "maximum": round(max(values), 6) if values else None,
                "mean": round(fmean(values), 6) if values else None,
                "latest": round(ordered[-1][1], 6) if ordered else None,
                "latest_at": ordered[-1][0] if ordered else None,
            }
    if "trend" in requested:
        for name, values_by_day in daily.items():
            ordered = sorted(values_by_day.items())
            trend = trend_for_metric(
                [day for day, _ in ordered], [value for _, value in ordered]
            )
            if trend is not None:
                trends[name] = trend

    correlations = correlation_pairs(daily) if "correlation" in requested else []
    point_count = sum(len(batch.points) for batch in batches.values())
    truncated = any(batch.truncated for batch in batches.values())
    sources = await _sources(principal.tenant_id, request_id)
    return AnalyzeMetricsResult(
        metric_types=unique_metrics,
        summaries=summaries,
        trends=trends,
        correlations=correlations,
        disclaimer=(
            "Results describe statistical associations, not cause and effect. "
            "They are general information, not medical diagnosis or treatment advice."
        ),
        provenance=_provenance(
            request_id=request_id,
            start=begin,
            end=finish,
            sources=sources,
            point_count=point_count,
            truncated=truncated,
        ),
    )


@mcp_server.tool(
    name="get_data_quality",
    description="Assess coverage and analysis sufficiency for canonical metrics.",
    annotations=READ_ONLY,
    structured_output=True,
)
async def get_data_quality(
    ctx: Context,
    metric_types: Annotated[list[str] | None, Field(max_length=20)] = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> DataQualityResult:
    """Report quality using each registry metric's expected cadence."""
    principal, request_id = _request_context(ctx)
    begin, finish = _window(start, end)
    if metric_types is None:
        try:
            names = (
                await core_client.fetch_metric_types(
                    principal.tenant_id, request_id=request_id
                )
            )[:20]
        except CoreUnavailable as exc:
            raise MCPError(
                -32000,
                "Analysis data is temporarily unavailable",
                {"code": "CORE_UNAVAILABLE"},
            ) from exc
    else:
        names = list(dict.fromkeys(metric_types))

    window_days = max(1, math.ceil((finish - begin).total_seconds() / 86_400))
    try:
        source_map = await core_client.fetch_source_map(
            principal.tenant_id, request_id=request_id
        )
    except CoreUnavailable as exc:
        raise MCPError(
            -32000,
            "Analysis data is temporarily unavailable",
            {"code": "CORE_UNAVAILABLE"},
        ) from exc
    results: list[MetricQuality] = []
    point_count = 0
    truncated = False
    for name in names:
        definition = _metric_definition(name)
        batch = await _points(
            principal,
            request_id,
            start=begin,
            end=finish,
            metric_type=name,
            max_points=MAX_ANALYSIS_SOURCE_POINTS,
        )
        daily = _daily_values(batch.points, definition)
        quality = series_quality(daily, window_days, name)
        source_counts: dict[str, int] = defaultdict(int)
        for point in batch.points:
            source_counts[source_map.get(point.source_id, "unknown")] += 1
        plausible_outliers = sum(
            1
            for point in batch.points
            if (
                definition.plausible_min is not None
                and point.value < definition.plausible_min
            )
            or (
                definition.plausible_max is not None
                and point.value > definition.plausible_max
            )
        )
        results.append(
            MetricQuality(
                metric_type=name,
                unit=_result_unit(batch.points, definition),
                observed_points=len(batch.points),
                observed_days=quality["observed_days"],
                window_days=quality["window_days"],
                coverage_pct=quality["coverage_pct"],
                cadence=quality["cadence"],
                sufficient=quality["sufficient"],
                missing_expected_days=(
                    max(0, window_days - quality["observed_days"])
                    if definition.cadence is Cadence.DAILY
                    else None
                ),
                plausible_outlier_count=plausible_outliers,
                source_point_counts=dict(sorted(source_counts.items())),
                note=quality["note"],
            )
        )
        point_count += len(batch.points)
        truncated = truncated or batch.truncated

    sources = await _sources(principal.tenant_id, request_id)
    return DataQualityResult(
        metrics=results,
        provenance=_provenance(
            request_id=request_id,
            start=begin,
            end=finish,
            sources=sources,
            point_count=point_count,
            truncated=truncated,
        ),
    )


class ModernOnlyMcpApp:
    """Authenticate and enforce the sessionless MCP 2026-07-28 HTTP contract."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != MCP_PATH:
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:12]}"

        async def reject(
            status: int, protocol_code: int, code: str, message: str
        ) -> None:
            response = JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": protocol_code,
                        "message": message,
                        "data": {"code": code, "request_id": request_id},
                    },
                },
                status_code=status,
                headers={"X-Request-ID": request_id},
            )
            await response(scope, receive, send)

        if scope.get("method") != "POST":
            await reject(405, -32600, "POST_REQUIRED", "MCP accepts POST requests only")
            return
        if headers.get("mcp-session-id") is not None:
            await reject(
                400,
                -32022,
                "SESSION_PROTOCOL_REJECTED",
                "Mcp-Session-Id is not valid for protocol 2026-07-28",
            )
            return
        if headers.get("mcp-protocol-version") != PROTOCOL_VERSION:
            await reject(
                400,
                -32022,
                "UNSUPPORTED_PROTOCOL_VERSION",
                f"Only MCP protocol {PROTOCOL_VERSION} is supported",
            )
            return

        method = headers.get("mcp-method") or ""
        if method not in ALLOWED_METHODS:
            await reject(
                400,
                -32601,
                "METHOD_NOT_ALLOWED",
                "This server exposes discovery and read-only tools only",
            )
            return
        if method == "tools/call" and not headers.get("mcp-name"):
            await reject(
                400, -32600, "MCP_NAME_REQUIRED", "Mcp-Name is required for tools/call"
            )
            return

        try:
            principal = mcp_principal_resolver.resolve(
                headers.get("authorization") or ""
            )
        except HTTPException as exc:
            await reject(
                exc.status_code, -32001, "AUTHENTICATION_FAILED", str(exc.detail)
            )
            return
        claimed_tenant = headers.get("x-tenant-id")
        if claimed_tenant and claimed_tenant != principal.tenant_id:
            await reject(
                403,
                -32001,
                "TENANT_HEADER_MISMATCH",
                "X-Tenant-ID does not match the authenticated tenant",
            )
            return
        try:
            valid, session_code = await core_client.validate_user_session(
                principal.tenant_id,
                user_id=principal.user_id,
                jti=principal.jti,
                issued_at=principal.issued_at,
                request_id=request_id,
            )
        except CoreUnavailable:
            await reject(
                503,
                -32000,
                "CORE_UNAVAILABLE",
                "Session validation is temporarily unavailable",
            )
            return
        if not valid:
            await reject(401, -32001, session_code, "Session is no longer valid")
            return

        state = dict(scope.get("state") or {})
        state["mcp_principal"] = principal
        scope["state"] = state
        mutable_headers = MutableHeaders(scope=scope)
        mutable_headers["x-request-id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["x-request-id"] = request_id
            await send(message)

        await self._app(scope, receive, send_with_request_id)


transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=settings.mcp_allowed_hosts,
    allowed_origins=settings.mcp_allowed_origins,
)


class McpApplication:
    """Re-creatable transport lifecycle around the stable tool registry.

    The SDK's transport manager is intentionally single-use. Production starts
    it once, while independent TestClient contexts restart application lifespan;
    constructing the transport per lifespan supports both without persisting an
    MCP protocol session.
    """

    def __init__(self) -> None:
        self._app: ASGIApp | None = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        http_app = mcp_server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            json_response=True,
            stateless_http=False,
            max_request_body_size=MAX_REQUEST_BODY_SIZE,
            transport_security=transport_security,
            host="0.0.0.0",
        )
        self._app = ModernOnlyMcpApp(http_app)
        try:
            async with http_app.router.lifespan_context(http_app):
                yield
        finally:
            self._app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            response = JSONResponse(
                {"error": {"code": "MCP_NOT_READY", "message": "MCP is not ready"}},
                status_code=503,
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


mcp_asgi_app = McpApplication()
