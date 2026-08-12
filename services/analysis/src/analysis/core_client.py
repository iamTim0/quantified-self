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
    ) -> list[MetricPoint]:
        """Every data point for a tenant in a window, following pagination."""
        return (
            await self.fetch_points_bounded(
                tenant_id,
                start=start,
                end=end,
                request_id=request_id,
                metric_type=metric_type,
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
