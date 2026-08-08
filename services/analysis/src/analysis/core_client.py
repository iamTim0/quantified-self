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
from dataclasses import dataclass
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
    ) -> list[MetricPoint]:
        """Every data point for a tenant in a window, following pagination."""
        points: list[MetricPoint] = []
        token = ""

        try:
            async with grpc.aio.insecure_channel(self._target) as channel:
                stub = pb_grpc.CoreDataServiceStub(channel)

                for _ in range(MAX_PAGES):
                    response = await stub.QueryDataPoints(
                        pb.QueryDataPointsRequest(
                            tenant_id=tenant_id,
                            start_time=_timestamp(start),
                            end_time=_timestamp(end),
                            pagination=common_pb.PaginationRequest(
                                page_size=PAGE_SIZE, page_token=token
                            ),
                        ),
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
                            )
                        )
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
            raise CoreUnavailable(
                f"Core gRPC query failed: {exc.code().name}"
            ) from exc

        return points

    async def fetch_source_types(self, tenant_id: str, *, request_id: str) -> list[str]:
        """Connector types configured for the tenant, for the provenance block."""
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

        return sorted({s.source_type for s in response.sources if s.source_type})
