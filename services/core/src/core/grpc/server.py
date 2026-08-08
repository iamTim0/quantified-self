"""gRPC server for the Core Data Service.

This was an eleven-line `pass` stub. It is the transport AGENTS.md rule 3 requires
between the Analysis Service and Core -- Analysis owns no database connection and
must read everything through here -- so while it was a stub there was no way to
build Analysis as a separate deployable at all, and the analyses ended up living
inside Core.

Two invariants are load-bearing in every handler below:

* **Tenant isolation (rule 2).** Every query filters on the `tenant_id` from the
  request, and it is validated as a UUID before it reaches SQL. A handler that
  forgets the filter would expose every tenant's data to any caller that can
  reach the port.
* **Authentication.** The port is on the internal network, but "internal" is not
  a security boundary -- the same assumption is what let a bare `X-Tenant-ID`
  header read any tenant over HTTP. Every call must carry a service credential in
  the `authorization` metadata key, checked with the same
  `verify_service_credential` the internal HTTP routes use.

Maps to Fizzbee Invariants:
- TenantIsolation
- NoUnauthorizedAccess
- ServiceTokenScopedToInternalPaths
"""

from __future__ import annotations

import logging
import uuid
from concurrent import futures
from datetime import datetime, timezone

import grpc
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from quantified_self.v1 import core_service_pb2 as pb
from quantified_self.v1 import core_service_pb2_grpc as pb_grpc
from quantified_self.v1 import data_point_pb2 as dp_pb
from sqlalchemy import distinct, select

from core.config import settings
from core.db.models import DataPoint, DataSource
from core.db.session import async_session_maker
from core.security.tokens import TokenError, verify_service_credential
from core.tracing import get_current_request_id, set_current_request_id

logger = logging.getLogger(__name__)

# A page has to be bounded or one query can pull a tenant's entire history into
# memory. Analysis pages through; it does not ask for everything at once.
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 5000

AUTH_METADATA_KEY = "authorization"
REQUEST_ID_METADATA_KEY = "x-request-id"


class _AuthError(Exception):
    """Raised to abort a call with UNAUTHENTICATED."""


def _metadata_value(context: grpc.aio.ServicerContext, key: str) -> str | None:
    for name, value in context.invocation_metadata() or ():
        if name.lower() == key:
            return value
    return None


def _authenticate(context: grpc.aio.ServicerContext) -> None:
    """Require a valid internal service credential on every call."""
    raw = _metadata_value(context, AUTH_METADATA_KEY) or ""
    if raw.lower().startswith("bearer "):
        raw = raw[7:]
    raw = raw.strip()
    if not raw:
        raise _AuthError("Missing service credential")
    try:
        verify_service_credential(raw)
    except TokenError as exc:
        raise _AuthError(exc.detail) from exc


def _bind_request_id(context: grpc.aio.ServicerContext) -> None:
    """Continue the caller's correlation id, or start one (rule 13)."""
    incoming = _metadata_value(context, REQUEST_ID_METADATA_KEY)
    set_current_request_id(incoming or f"req_{uuid.uuid4().hex[:12]}")


def _require_tenant(tenant_id: str) -> str:
    """Reject anything that is not a UUID before it reaches a query."""
    if not tenant_id:
        raise ValueError("tenant_id is required")
    try:
        uuid.UUID(tenant_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("tenant_id must be a UUID") from exc
    return tenant_id


def _to_timestamp(value: datetime | None) -> Timestamp | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    stamp = Timestamp()
    stamp.FromDatetime(value.astimezone(timezone.utc))
    return stamp


def _from_timestamp(stamp: Timestamp | None) -> datetime | None:
    if stamp is None or (stamp.seconds == 0 and stamp.nanos == 0):
        return None
    return stamp.ToDatetime().replace(tzinfo=timezone.utc)


def _to_proto(row: DataPoint) -> dp_pb.DataPoint:
    metadata = Struct()
    # `metadata_` on the model: `metadata` is reserved by SQLAlchemy's declarative
    # base, so the column is mapped under a trailing underscore.
    if isinstance(row.metadata_, dict):
        try:
            ParseDict(row.metadata_, metadata)
        except Exception:  # noqa: BLE001 - metadata is free-form; never fail a read over it
            logger.warning(
                "[req_id=%s] Unserialisable metadata on data point %s; sending it empty",
                get_current_request_id(),
                row.id,
            )

    point = dp_pb.DataPoint(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        source_id=str(row.source_id) if row.source_id else "",
        metric_type=row.metric_type or "",
        value=float(row.value) if row.value is not None else 0.0,
        idempotency_key=row.idempotency_key or "",
        metadata=metadata,
    )
    if (timestamp := _to_timestamp(row.timestamp)) is not None:
        point.timestamp.CopyFrom(timestamp)
    if (created := _to_timestamp(getattr(row, "created_at", None))) is not None:
        point.created_at.CopyFrom(created)
    return point


class CoreDataServicer(pb_grpc.CoreDataServiceServicer):
    """Read-only projection of Core's data for other services."""

    async def QueryDataPoints(
        self, request: pb.QueryDataPointsRequest, context: grpc.aio.ServicerContext
    ) -> pb.QueryDataPointsResponse:
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)

            page_size = request.pagination.page_size or DEFAULT_PAGE_SIZE
            page_size = max(1, min(page_size, MAX_PAGE_SIZE))
            offset = _decode_page_token(request.pagination.page_token)

            stmt = select(DataPoint).where(DataPoint.tenant_id == tenant_id)
            if request.HasField("metric_type"):
                stmt = stmt.where(DataPoint.metric_type == request.metric_type)
            if request.HasField("source_id"):
                stmt = stmt.where(DataPoint.source_id == request.source_id)
            if (start := _from_timestamp(request.start_time)) is not None:
                stmt = stmt.where(DataPoint.timestamp >= start)
            if (end := _from_timestamp(request.end_time)) is not None:
                stmt = stmt.where(DataPoint.timestamp <= end)

            # Ordered so paging is stable; id breaks ties between points sharing
            # a timestamp, which is common for a daily summary metric.
            stmt = stmt.order_by(DataPoint.timestamp, DataPoint.id)
            # One extra row tells us whether another page exists without a
            # second COUNT query over the whole window.
            stmt = stmt.offset(offset).limit(page_size + 1)

            async with async_session_maker() as session:
                rows = (await session.execute(stmt)).scalars().all()

            has_more = len(rows) > page_size
            page = rows[:page_size]

            response = pb.QueryDataPointsResponse(
                data_points=[_to_proto(row) for row in page]
            )
            if has_more:
                response.pagination.next_page_token = str(offset + page_size)
            return response

    async def GetDataPoint(
        self, request: pb.GetDataPointRequest, context: grpc.aio.ServicerContext
    ) -> dp_pb.DataPoint:
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            async with async_session_maker() as session:
                row = (
                    await session.execute(
                        select(DataPoint).where(
                            DataPoint.tenant_id == tenant_id,
                            DataPoint.id == request.data_point_id,
                        )
                    )
                ).scalars().first()

            if row is None:
                # NOT_FOUND for a point in another tenant as well as one that does
                # not exist: distinguishing them would confirm the id is real.
                await context.abort(grpc.StatusCode.NOT_FOUND, "Data point not found")
            return _to_proto(row)

    async def ListMetricTypes(
        self, request: pb.ListMetricTypesRequest, context: grpc.aio.ServicerContext
    ) -> pb.ListMetricTypesResponse:
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            async with async_session_maker() as session:
                rows = await session.execute(
                    select(distinct(DataPoint.metric_type)).where(
                        DataPoint.tenant_id == tenant_id
                    )
                )
            return pb.ListMetricTypesResponse(
                metric_types=sorted(m for m in rows.scalars() if m)
            )

    async def ListDataSources(
        self, request: pb.ListDataSourcesRequest, context: grpc.aio.ServicerContext
    ) -> pb.ListDataSourcesResponse:
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            async with async_session_maker() as session:
                rows = (
                    await session.execute(
                        select(DataSource).where(DataSource.tenant_id == tenant_id)
                    )
                ).scalars().all()

            # Deliberately no `config` and no credentials of any kind, encrypted
            # or otherwise. This response crosses a service boundary; rule 12
            # says secrets do not.
            return pb.ListDataSourcesResponse(
                sources=[
                    pb.DataSourceSummary(
                        id=str(row.id),
                        source_type=row.source_type or "",
                    )
                    for row in rows
                ]
            )


class _guard:
    """Authenticate, bind the correlation id, and map errors to status codes."""

    def __init__(self, context: grpc.aio.ServicerContext) -> None:
        self._context = context

    async def __aenter__(self) -> None:
        _bind_request_id(self._context)
        try:
            _authenticate(self._context)
        except _AuthError as exc:
            await self._context.abort(grpc.StatusCode.UNAUTHENTICATED, str(exc))

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            return False
        if isinstance(exc, ValueError):
            await self._context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return True
        if isinstance(exc, grpc.RpcError) or exc_type.__name__ == "AbortError":
            return False
        logger.exception(
            "[req_id=%s] gRPC handler failed", get_current_request_id()
        )
        await self._context.abort(grpc.StatusCode.INTERNAL, "Internal error")
        return True


def _decode_page_token(token: str) -> int:
    """Page tokens are opaque to callers but are just an offset."""
    if not token:
        return 0
    try:
        offset = int(token)
    except ValueError as exc:
        raise ValueError("Invalid page token") from exc
    if offset < 0:
        raise ValueError("Invalid page token")
    return offset


async def serve_grpc(port: int | None = None) -> grpc.aio.Server:
    """Start the gRPC server and return it (already started)."""
    port = port or settings.GRPC_PORT
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_CoreDataServiceServicer_to_server(CoreDataServicer(), server)
    server.add_insecure_port(f"0.0.0.0:{port}")
    await server.start()
    logger.info("Core gRPC server listening on :%s", port)
    return server


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        server = await serve_grpc()
        await server.wait_for_termination()

    asyncio.run(_main())
