"""gRPC client for the Core Data Service.

This is the **only** way this service obtains data. AGENTS.md rule 1 gives Core
sole ownership of the database, and rule 3 makes gRPC the transport between
Analysis and Core. There is no SQLAlchemy, no asyncpg and no database URL
anywhere in this service, and there must not be: the check is easy to state and
easy to grep for, which is the point.

Two things this has to get right that a naive client would not:

* **Paging.** A 90-day window for an active tenant is thousands of points. Core
  caps a page, so a client that issues one unpaged request silently analyses a
  truncated window and reports confident numbers about the wrong data.
* **Credentials.** Core's gRPC port requires an internal service credential on
  every call. It is minted here from the shared secret rather than stored, and it
  is short-lived.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import grpc
import jwt
from google.protobuf.timestamp_pb2 import Timestamp
from quantified_self.v1 import common_pb2 as common_pb
from quantified_self.v1 import core_service_pb2 as pb
from quantified_self.v1 import core_service_pb2_grpc as pb_grpc

from analysis.config import settings

logger = logging.getLogger(__name__)

# Matches core.security.tokens. Duplicated rather than imported: services share no
# code by design (rule 6), and importing Core's module here would mean importing
# Core's settings, and with them its database configuration.
ISSUER = "qs-core"
AUDIENCE_INTERNAL = "qs-internal"
TOKEN_TYPE_SERVICE = "service"

PAGE_SIZE = 1000
# A window is bounded by the API (14-365 days), so this only ever trips on a bug
# in paging -- a token that fails to advance would otherwise loop forever.
MAX_PAGES = 500

#: Pages of sets one bundle will read. A year of five sessions a week at twenty
#: sets is roughly five thousand, so this covers it without an unbounded loop.
MAX_SET_PAGES = 10


@dataclass(frozen=True)
class StrengthSet:
    """One resistance set, as Core reassembled it.

    A set is stored as up to four points sharing a `set_id`; Core puts them back
    together because the grouping key — the exercise name — lives in JSONB, which
    this service may not read (rules 1 and 3).
    """

    at: datetime
    session_id: str
    source_id: str
    exercise_title: str
    #: Canonical MuscleGroup identifier, or empty when the provider stated none.
    muscle_group: str
    weight_kg: float
    reps: float
    volume_kg: float
    set_number: int
    #: False for a bodyweight set. Not the same as `weight_kg == 0`, which a
    #: provider may legitimately state.
    has_weight: bool


@dataclass(frozen=True)
class StrengthSetsResponse:
    sets: list[StrengthSet]
    #: The window held more sets than the pages read. A shortened answer says so
    #: rather than reading as a quiet training block.
    truncated: bool


class CoreUnavailable(Exception):
    """Core could not be reached or refused the call."""


@dataclass(frozen=True)
class MetricPoint:
    metric_type: str
    timestamp: datetime
    value: float
    source_id: str = ""
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricSeriesBucket:
    """One server-side aggregate bucket; ``None`` represents a gap."""

    metric_type: str
    bucket_start: datetime
    value: float | None
    sample_count: int
    source_id: str = ""


@dataclass(frozen=True)
class MetricSeriesIssue:
    """A non-fatal condition attached to a server-side metric series."""

    code: str
    metric_type: str
    source_ids: list[str] = field(default_factory=list)
    # For AMBIGUOUS_METRIC_SOURCE: which source answers, and how Core decided.
    # Empty from a Core too old to send it, which is the one case this service
    # still has to drop the metric rather than pick a source at random.
    primary_source_id: str = ""
    primary_reason: str = ""


@dataclass(frozen=True)
class DueAnalysisReport:
    """One insight run Core has queued and this service has claimed."""

    run_id: str
    tenant_id: str
    params: dict[str, object] = field(default_factory=dict)
    request_id: str = ""


@dataclass(frozen=True)
class MetricSeriesResponse:
    """Source-scoped buckets plus machine-readable query conditions."""

    buckets: list[MetricSeriesBucket]
    issues: list[MetricSeriesIssue] = field(default_factory=list)


@dataclass(frozen=True)
class PointBatch:
    """A bounded Core query and whether more matching points existed."""

    points: list[MetricPoint]
    truncated: bool


def _service_token() -> str:
    """Mint a short-lived internal credential for this call."""
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": settings.SERVICE_NAME,
            "iss": ISSUER,
            "aud": AUDIENCE_INTERNAL,
            "token_type": TOKEN_TYPE_SERVICE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.internal_secret,
        algorithm="HS256",
    )


def _metadata(request_id: str) -> list[tuple[str, str]]:
    # X-Request-ID rides along so a slow analysis can be traced back through Core
    # to the query that caused it (rule 13).
    return [
        ("authorization", f"Bearer {_service_token()}"),
        ("x-request-id", request_id),
        ("x-service-name", settings.SERVICE_NAME),
    ]


def _timestamp(value: datetime) -> Timestamp:
    stamp = Timestamp()
    stamp.FromDatetime(value.astimezone(timezone.utc))
    return stamp


class CoreClient:
    """Thin async wrapper over CoreDataServiceStub."""

    def __init__(self, target: str | None = None) -> None:
        self._target = target or settings.CORE_GRPC_URL

    async def fetch_points(
        self,
        tenant_id: str,
        *,
        start: datetime,
        end: datetime,
        request_id: str,
        metric_type: str | None = None,
        source_id: str | None = None,
    ) -> list[MetricPoint]:
        """Every data point for a tenant in a window, following pagination."""
        return (
            await self.fetch_points_bounded(
                tenant_id,
                start=start,
                end=end,
                request_id=request_id,
                metric_type=metric_type,
                source_id=source_id,
                max_points=None,
            )
        ).points

    async def fetch_points_bounded(
        self,
        tenant_id: str,
        *,
        start: datetime,
        end: datetime,
        request_id: str,
        metric_type: str | None = None,
        source_id: str | None = None,
        max_points: int | None,
    ) -> PointBatch:
        """Read a bounded window without silently presenting a partial result as complete."""
        points: list[MetricPoint] = []
        token = ""

        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)

                for _ in range(MAX_PAGES):
                    query = pb.QueryDataPointsRequest(
                        tenant_id=tenant_id,
                        start_time=_timestamp(start),
                        end_time=_timestamp(end),
                        pagination=common_pb.PaginationRequest(
                            page_size=PAGE_SIZE, page_token=token
                        ),
                    )
                    if metric_type is not None:
                        query.metric_type = metric_type
                    if source_id is not None:
                        query.source_id = source_id
                    response = await stub.QueryDataPoints(
                        query,
                        metadata=_metadata(request_id),
                    )
                    for point in response.data_points:
                        points.append(
                            MetricPoint(
                                metric_type=point.metric_type,
                                timestamp=point.timestamp.ToDatetime().replace(
                                    tzinfo=timezone.utc
                                ),
                                value=point.value,
                                source_id=point.source_id,
                                metadata=dict(point.metadata),
                            )
                        )
                    if max_points is not None and len(points) > max_points:
                        return PointBatch(points=points[:max_points], truncated=True)
                    token = response.pagination.next_page_token
                    if not token:
                        break
                else:
                    # Reporting a truncated window as if it were complete is worse
                    # than failing: the numbers would look authoritative.
                    raise CoreUnavailable(
                        f"Pagination did not terminate after {MAX_PAGES} pages"
                    )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(f"Core gRPC query failed: {exc.code().name}") from exc

        return PointBatch(points=points, truncated=False)

    async def fetch_metric_series(
        self,
        tenant_id: str,
        *,
        start: datetime,
        end: datetime,
        request_id: str,
        metric_types: list[str] | None = None,
        resolution: int = pb.METRIC_SERIES_RESOLUTION_DAY,
        source_id: str | None = None,
    ) -> MetricSeriesResponse:
        """Read a bounded, registry-aware series from Core without raw points."""
        query = pb.QueryMetricSeriesRequest(
            tenant_id=tenant_id,
            start_time=_timestamp(start),
            end_time=_timestamp(end),
            resolution=resolution,
        )
        if metric_types:
            query.metric_types.extend(metric_types)
        if source_id is not None:
            query.source_id = source_id

        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                response = await stub.QueryMetricSeries(
                    query,
                    metadata=_metadata(request_id),
                )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC metric series query failed: {exc.code().name}"
            ) from exc

        return MetricSeriesResponse(
            buckets=[
                MetricSeriesBucket(
                    metric_type=bucket.metric_type,
                    bucket_start=bucket.bucket_start.ToDatetime().replace(
                        tzinfo=timezone.utc
                    ),
                    value=bucket.value if bucket.HasField("value") else None,
                    sample_count=int(bucket.sample_count),
                    source_id=bucket.source_id,
                )
                for bucket in response.buckets
            ],
            issues=[
                MetricSeriesIssue(
                    code=issue.code,
                    metric_type=issue.metric_type,
                    source_ids=list(issue.source_ids),
                    primary_source_id=issue.primary_source_id,
                    primary_reason=issue.primary_reason,
                )
                for issue in response.issues
            ],
        )

    async def fetch_strength_sets(
        self,
        tenant_id: str,
        *,
        start: datetime,
        end: datetime,
        request_id: str,
        source_id: str | None = None,
    ) -> StrengthSetsResponse:
        """Every resistance set in a bounded window, paged.

        The one call in this client that reads a *metadata* dimension. It exists as
        its own RPC rather than a grouping option on `fetch_metric_series` because
        that message is the interface every analysis depends on, and an
        almost-always-empty dimension there would be a field every future reader had
        to reason about.
        """
        collected: list[StrengthSet] = []
        token = ""
        truncated = False

        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                for _ in range(MAX_SET_PAGES):
                    query = pb.QueryStrengthSetsRequest(
                        tenant_id=tenant_id,
                        start_time=_timestamp(start),
                        end_time=_timestamp(end),
                        pagination=common_pb.PaginationRequest(page_token=token),
                    )
                    if source_id is not None:
                        query.source_id = source_id
                    response = await stub.QueryStrengthSets(
                        query, metadata=_metadata(request_id)
                    )
                    collected.extend(
                        StrengthSet(
                            at=row.at.ToDatetime().replace(tzinfo=timezone.utc),
                            session_id=row.session_id,
                            source_id=row.source_id,
                            exercise_title=row.exercise_title,
                            muscle_group=row.muscle_group,
                            weight_kg=row.weight_kg,
                            reps=row.reps,
                            volume_kg=row.volume_kg,
                            set_number=int(row.set_number),
                            has_weight=row.has_weight,
                        )
                        for row in response.sets
                    )
                    token = response.pagination.next_page_token
                    if not token:
                        break
                else:
                    # The loop ran out rather than the data. Reported, not raised:
                    # a partial training history still answers "am I getting
                    # stronger", where an exception answers nothing.
                    truncated = True
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC strength set query failed: {exc.code().name}"
            ) from exc

        return StrengthSetsResponse(sets=collected, truncated=truncated)


    async def fetch_metric_types(self, tenant_id: str, *, request_id: str) -> list[str]:
        """Canonical or registered dynamic metric names stored for one tenant."""
        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                response = await stub.ListMetricTypes(
                    pb.ListMetricTypesRequest(tenant_id=tenant_id),
                    metadata=_metadata(request_id),
                )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC metric listing failed: {exc.code().name}"
            ) from exc

        return sorted(set(response.metric_types))

    async def fetch_source_types(self, tenant_id: str, *, request_id: str) -> list[str]:
        """Connector types configured for the tenant, for the provenance block."""
        return sorted(
            set(
                (await self.fetch_source_map(tenant_id, request_id=request_id)).values()
            )
        )

    async def fetch_source_map(
        self, tenant_id: str, *, request_id: str
    ) -> dict[str, str]:
        """Map tenant-owned source identifiers to non-secret connector types."""
        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                response = await stub.ListDataSources(
                    pb.ListDataSourcesRequest(tenant_id=tenant_id),
                    metadata=_metadata(request_id),
                )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC source listing failed: {exc.code().name}"
            ) from exc

        return {
            source.id: source.source_type
            for source in response.sources
            if source.id and source.source_type
        }

    async def validate_user_session(
        self,
        tenant_id: str,
        *,
        user_id: str,
        jti: str,
        issued_at: datetime,
        request_id: str,
    ) -> tuple[bool, str]:
        """Ask Core whether a verified JWT session remains valid."""
        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                response = await stub.ValidateUserSession(
                    pb.ValidateUserSessionRequest(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        jti=jti,
                        issued_at=_timestamp(issued_at),
                    ),
                    metadata=_metadata(request_id),
                )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC session validation failed: {exc.code().name}"
            ) from exc
        return response.valid, response.code

    async def claim_due_analysis_reports(
        self, *, limit: int, request_id: str
    ) -> list[DueAnalysisReport]:
        """Take queued insight runs off Core's work list.

        Claiming and listing are one call on purpose: Core marks each run
        `running` in the transaction that returns it, so two Analysis replicas
        polling at the same moment cannot both compute the same tenant's bundle.
        """
        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                response = await stub.ListDueAnalysisReports(
                    pb.ListDueAnalysisReportsRequest(limit=limit),
                    metadata=_metadata(request_id),
                )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC report claim failed: {exc.code().name}"
            ) from exc

        claimed: list[DueAnalysisReport] = []
        for report in response.reports:
            try:
                params = json.loads(report.params_json or "{}")
            except ValueError:
                params = {}
            claimed.append(
                DueAnalysisReport(
                    run_id=report.run_id,
                    tenant_id=report.tenant_id,
                    params=params if isinstance(params, dict) else {},
                    request_id=report.request_id or request_id,
                )
            )
        return claimed

    async def put_analysis_report(
        self,
        *,
        run_id: str,
        tenant_id: str,
        payload: dict[str, object] | None,
        error_code: str = "",
        request_id: str,
    ) -> str:
        """Hand a finished bundle back to Core, which owns the storage (rule 1).

        Returns Core's machine code: STORED, RUN_NOT_FOUND, or
        RUN_ALREADY_FINISHED. The last is not an error — it means Core timed the
        run out while this one was still computing, and refusing the late result
        is correct because a replacement may already have been queued.
        """
        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)
                response = await stub.PutAnalysisReport(
                    pb.PutAnalysisReportRequest(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        payload_json=json.dumps(payload or {}),
                        error_code=error_code,
                    ),
                    metadata=_metadata(request_id),
                )
        except grpc.aio.AioRpcError as exc:
            raise CoreUnavailable(
                f"Core gRPC report write failed: {exc.code().name}"
            ) from exc
        return response.code
