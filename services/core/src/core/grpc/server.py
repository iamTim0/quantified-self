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

import base64
import binascii
import json
import logging
import uuid
from concurrent import futures
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import grpc
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from quantified_self.v1 import core_service_pb2 as pb
from quantified_self.v1 import core_service_pb2_grpc as pb_grpc
from quantified_self.v1 import data_point_pb2 as dp_pb
from shared_schemas.metrics import Aggregation, canonical_metric_type, describe
from sqlalchemy import and_, distinct, exists, func, or_, select

from core.config import settings
from core.db.models import (
    DataPoint,
    DataSource,
    MetricRollup,
    ReportRun,
    RevokedAccessToken,
    User,
)
from core.db.session import async_session_maker
from core.reports import (
    claim_due_analysis_runs,
    fail_report_run,
    finish_report_run,
    metric_source_coverage,
    primary_source_preferences,
    resolve_primary_source,
)
from core.rollup_coverage import may_hold_points_outside_day_rollups
from core.security.tokens import TokenError, verify_service_credential
from core.tracing import get_current_request_id, set_current_request_id

logger = logging.getLogger(__name__)

# A page has to be bounded or one query can pull a tenant's entire history into
# memory. Analysis pages through; it does not ask for everything at once.
DEFAULT_PAGE_SIZE = 500
MAX_PAGE_SIZE = 5000
#: How many metric names one *request* may list. A caller wrote that list, so
#: rejecting an over-long one costs nothing and happens before any query. This is
#: not a limit on how many metrics a tenant may have: see `QueryMetricSeries`,
#: where a caller that names none is asking for whatever exists.
MAX_SERIES_METRICS = 100
#: The real ceiling on a series response, in the unit the response is measured in.
#: Series times buckets, checked before any of them are serialised.
MAX_SERIES_BUCKETS = 100_000
MAX_SERIES_RANGE = timedelta(days=366)

#: Sets one `QueryStrengthSets` page may return, and the ceiling a caller may ask
#: for. A year of five sessions a week at twenty sets is about five thousand, so a
#: default page covers a training block and the maximum covers the year.
DEFAULT_SET_PAGE = 1000
MAX_SET_PAGE = 5000

AUTH_METADATA_KEY = "authorization"
REQUEST_ID_METADATA_KEY = "x-request-id"
SERVICE_NAME_METADATA_KEY = "x-service-name"


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
    service_name = _metadata_value(context, SERVICE_NAME_METADATA_KEY)
    try:
        verify_service_credential(raw, service_name=service_name)
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


def _require_source_id(source_id: str) -> str:
    """Validate and canonicalize a connector instance identifier."""
    if not source_id:
        raise ValueError("source_id must not be empty")
    try:
        return str(uuid.UUID(source_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("source_id must be a UUID") from exc


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


def _series_resolution(value: int) -> str:
    """Map the wire enum to the rollup resolution stored by Core."""
    if value in (
        pb.METRIC_SERIES_RESOLUTION_UNSPECIFIED,
        pb.METRIC_SERIES_RESOLUTION_DAY,
    ):
        return "day"
    if value == pb.METRIC_SERIES_RESOLUTION_HOUR:
        return "hour"
    raise ValueError("Unsupported metric series resolution")


def _series_bucket_start(value: datetime, resolution: str) -> datetime:
    """Return the UTC boundary containing a timestamp."""
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if resolution == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _series_buckets(start: datetime, end: datetime, resolution: str) -> list[datetime]:
    """Return all bucket starts intersecting the half-open query interval."""
    current = _series_bucket_start(start, resolution)
    step = timedelta(hours=1) if resolution == "hour" else timedelta(days=1)
    buckets: list[datetime] = []
    while current < end:
        buckets.append(current)
        current += step
    return buckets


def _metric_aggregation(metric_type: str) -> Aggregation:
    """Resolve a metric's registry aggregation with a safe legacy fallback."""
    try:
        return describe(metric_type).aggregation
    except ValueError:
        # Older rows may contain a name that is no longer in the registry. They
        # remain queryable, but must not make the whole tenant's series fail.
        return Aggregation.AVERAGE


def _canonical_metric_types(raw_types: list[str]) -> list[str]:
    """Validate requested names and return unique canonical metric keys."""
    metric_types: list[str] = []
    for raw_type in raw_types:
        try:
            metric_type = canonical_metric_type(raw_type)
        except ValueError as exc:
            raise ValueError(f"Unknown metric_type: {raw_type}") from exc
        if metric_type not in metric_types:
            metric_types.append(metric_type)
    if len(metric_types) > MAX_SERIES_METRICS:
        raise ValueError(f"At most {MAX_SERIES_METRICS} metric types may be requested")
    return metric_types


def _rollup_covers_point(resolution: str):
    """Exclude raw points already represented by an incremental rollup."""
    bucket = func.date_trunc(resolution, DataPoint.timestamp)
    return exists(
        select(MetricRollup.id).where(
            MetricRollup.tenant_id == DataPoint.tenant_id,
            MetricRollup.source_id == DataPoint.source_id,
            MetricRollup.metric_type == DataPoint.metric_type,
            MetricRollup.resolution == resolution,
            MetricRollup.bucket_start == bucket,
            or_(
                MetricRollup.is_provider_total.is_(True),
                and_(
                    MetricRollup.first_timestamp.is_not(None),
                    MetricRollup.last_timestamp.is_not(None),
                    DataPoint.timestamp >= MetricRollup.first_timestamp,
                    DataPoint.timestamp <= MetricRollup.last_timestamp,
                ),
            ),
        )
    )


@dataclass
class _SeriesAccumulator:
    """Aggregation state for one source, metric, and time bucket."""

    aggregation: Aggregation
    sample_count: int = 0
    sum_value: float = 0.0
    max_value: float | None = None
    last_value: float | None = None
    last_timestamp: datetime | None = None

    def add(
        self,
        *,
        sample_count: int,
        sum_value: float | None,
        max_value: float | None,
        last_value: float | None,
        last_timestamp: datetime | None,
    ) -> None:
        """Merge a source-level aggregate into this source-scoped bucket."""
        if sample_count <= 0:
            return
        self.sample_count += sample_count
        self.sum_value += float(sum_value or 0.0)
        if max_value is not None:
            self.max_value = (
                float(max_value)
                if self.max_value is None
                else max(self.max_value, float(max_value))
            )
        if last_timestamp is not None:
            timestamp = (
                last_timestamp
                if last_timestamp.tzinfo
                else last_timestamp.replace(tzinfo=timezone.utc)
            ).astimezone(timezone.utc)
            if self.last_timestamp is None or timestamp >= self.last_timestamp:
                self.last_timestamp = timestamp
                self.last_value = (
                    float(last_value) if last_value is not None else self.last_value
                )

    def set_last_value(self, value: float, timestamp: datetime) -> None:
        """Attach the value selected by the raw-data latest-value query."""
        timestamp = (
            timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        ).astimezone(timezone.utc)
        if self.last_timestamp is None or timestamp >= self.last_timestamp:
            self.last_timestamp = timestamp
            self.last_value = float(value)

    @property
    def value(self) -> float | None:
        """Return the registry-aware value, or None for an empty bucket."""
        if self.sample_count == 0:
            return None
        if self.aggregation is Aggregation.SUM:
            return self.sum_value
        if self.aggregation is Aggregation.MAX:
            return self.max_value
        if self.aggregation is Aggregation.LAST:
            return self.last_value
        return self.sum_value / self.sample_count


class CoreDataServicer(pb_grpc.CoreDataServiceServicer):
    """Read-only projection of Core's data for other services."""

    async def QueryDataPoints(
        self, request: pb.QueryDataPointsRequest, context: grpc.aio.ServicerContext
    ) -> pb.QueryDataPointsResponse:
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)

            page_size = request.pagination.page_size or DEFAULT_PAGE_SIZE
            page_size = max(1, min(page_size, MAX_PAGE_SIZE))
            cursor, legacy_offset = _decode_page_token(request.pagination.page_token)
            requested_source_id = None
            if request.HasField("source_id"):
                requested_source_id = _require_source_id(request.source_id)

            stmt = select(DataPoint).where(DataPoint.tenant_id == tenant_id)
            if request.HasField("metric_type"):
                stmt = stmt.where(DataPoint.metric_type == request.metric_type)
            if requested_source_id is not None:
                stmt = stmt.where(DataPoint.source_id == requested_source_id)
            if (start := _from_timestamp(request.start_time)) is not None:
                stmt = stmt.where(DataPoint.timestamp >= start)
            if (end := _from_timestamp(request.end_time)) is not None:
                stmt = stmt.where(DataPoint.timestamp <= end)

            if cursor is not None:
                cursor_timestamp, cursor_id = cursor
                stmt = stmt.where(
                    or_(
                        DataPoint.timestamp > cursor_timestamp,
                        and_(
                            DataPoint.timestamp == cursor_timestamp,
                            DataPoint.id > cursor_id,
                        ),
                    )
                )

            # Ordered so paging is stable; id breaks ties between points sharing
            # a timestamp, which is common for a daily summary metric.
            stmt = stmt.order_by(DataPoint.timestamp, DataPoint.id)
            # One extra row tells us whether another page exists without a
            # second COUNT query over the whole window.
            if legacy_offset is not None:
                # Accept old offset tokens during a rolling deployment. New
                # responses use a keyset cursor so deep pages do not make
                # PostgreSQL scan and discard every earlier row.
                stmt = stmt.offset(legacy_offset)
            stmt = stmt.limit(page_size + 1)

            async with async_session_maker() as session:
                if requested_source_id is not None:
                    source_exists = await session.execute(
                        select(DataSource.id).where(
                            DataSource.tenant_id == tenant_id,
                            DataSource.id == requested_source_id,
                        )
                    )
                    if source_exists.scalar_one_or_none() is None:
                        await context.abort(
                            grpc.StatusCode.NOT_FOUND, "Data source not found"
                        )
                rows = (await session.execute(stmt)).scalars().all()

            has_more = len(rows) > page_size
            page = rows[:page_size]

            response = pb.QueryDataPointsResponse(
                data_points=[_to_proto(row) for row in page]
            )
            if has_more:
                last = page[-1]
                response.pagination.next_page_token = _encode_page_token(
                    last.timestamp, str(last.id)
                )
            return response

    async def QueryMetricSeries(
        self, request: pb.QueryMetricSeriesRequest, context: grpc.aio.ServicerContext
    ) -> pb.QueryMetricSeriesResponse:
        """Return registry-aware buckets without transferring raw points."""
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            start = _from_timestamp(request.start_time)
            end = _from_timestamp(request.end_time)
            if start is None or end is None:
                raise ValueError("start_time and end_time are required")
            if end <= start:
                raise ValueError("end_time must be after start_time")
            if end - start > MAX_SERIES_RANGE:
                raise ValueError("Metric series range cannot exceed 366 days")

            resolution = _series_resolution(request.resolution)
            metric_types = _canonical_metric_types(list(request.metric_types))
            buckets = _series_buckets(start, end, resolution)
            if metric_types and len(metric_types) * len(buckets) > MAX_SERIES_BUCKETS:
                raise ValueError("Requested metric series is too large")

            aggregations = {
                metric_type: _metric_aggregation(metric_type)
                for metric_type in metric_types
            }
            aggregates: dict[tuple[str, str, datetime], _SeriesAccumulator] = {}
            metric_sources: dict[str, set[str]] = {}

            requested_source_id = None
            if request.HasField("source_id"):
                requested_source_id = _require_source_id(request.source_id)

            def accumulator(
                metric_type: str, source_id: str, bucket: datetime
            ) -> _SeriesAccumulator:
                key = (metric_type, source_id, bucket)
                if key not in aggregates:
                    aggregation = aggregations.setdefault(
                        metric_type, _metric_aggregation(metric_type)
                    )
                    aggregates[key] = _SeriesAccumulator(aggregation)
                metric_sources.setdefault(metric_type, set()).add(source_id)
                return aggregates[key]

            source_filter = []
            if requested_source_id is not None:
                source_filter.append(MetricRollup.source_id == requested_source_id)

            async with async_session_maker() as session:
                if requested_source_id is not None:
                    source_exists = await session.execute(
                        select(DataSource.id).where(
                            DataSource.tenant_id == tenant_id,
                            DataSource.id == requested_source_id,
                        )
                    )
                    if source_exists.scalar_one_or_none() is None:
                        await context.abort(
                            grpc.StatusCode.NOT_FOUND, "Data source not found"
                        )

                rollup_stmt = select(
                    MetricRollup.metric_type,
                    MetricRollup.source_id,
                    MetricRollup.bucket_start,
                    MetricRollup.value,
                    MetricRollup.sample_count,
                    MetricRollup.sum_value,
                    MetricRollup.max_value,
                    MetricRollup.last_value,
                    MetricRollup.last_timestamp,
                ).where(
                    MetricRollup.tenant_id == tenant_id,
                    MetricRollup.resolution == resolution,
                    MetricRollup.bucket_start
                    >= _series_bucket_start(start, resolution),
                    MetricRollup.bucket_start < end,
                    *source_filter,
                )
                if metric_types:
                    rollup_stmt = rollup_stmt.where(
                        MetricRollup.metric_type.in_(metric_types)
                    )

                for row in (await session.execute(rollup_stmt)).all():
                    bucket = _series_bucket_start(row.bucket_start, resolution)
                    accumulator(row.metric_type, str(row.source_id), bucket).add(
                        sample_count=int(row.sample_count),
                        sum_value=row.sum_value,
                        max_value=row.max_value,
                        last_value=row.last_value,
                        last_timestamp=row.last_timestamp,
                    )

                # Skipped only for a day series over a workspace already proven to
                # hold no point outside a day rollup: the coverage test below is
                # applied to every point in the window, and there is nothing for it
                # to find. At minute and hour resolution the raw points *are* the
                # answer — an ordinary point is rolled up into a day and nothing
                # else — so the proof says nothing there. See `core.rollup_coverage`.
                covered = resolution == "day" and not may_hold_points_outside_day_rollups(
                    tenant_id
                )

                # Built unconditionally, even though only the two blocks below read
                # it. It used to be built inside `if not covered:` while the
                # `LAST`-metric refinement further down read it regardless, so a day
                # series over a workspace whose points are all covered by day rollups
                # raised `UnboundLocalError` — and that combination is the *normal*
                # one for an established workspace. In production it failed every
                # insights run: the gRPC call returned INTERNAL, the Analysis worker
                # treated it as "Core unavailable" and re-raised, the run stayed in
                # flight, and thirty minutes later the sweep failed it as a timeout.
                # The reader was told the report was too slow. It never ran at all.
                raw_filters = [
                    DataPoint.tenant_id == tenant_id,
                    DataPoint.timestamp >= start,
                    DataPoint.timestamp < end,
                    ~_rollup_covers_point(resolution),
                ]
                if requested_source_id is not None:
                    raw_filters.append(DataPoint.source_id == requested_source_id)
                if metric_types:
                    raw_filters.append(DataPoint.metric_type.in_(metric_types))

                if not covered:
                    bucket_expr = func.date_trunc(resolution, DataPoint.timestamp).label(
                        "bucket_start"
                    )
                    raw_stmt = (
                        select(
                            DataPoint.metric_type,
                            DataPoint.source_id,
                            bucket_expr,
                            func.count(DataPoint.value).label("sample_count"),
                            func.sum(DataPoint.value).label("sum_value"),
                            func.max(DataPoint.value).label("max_value"),
                            func.max(DataPoint.timestamp)
                            .filter(DataPoint.value.is_not(None))
                            .label("last_timestamp"),
                        )
                        .where(*raw_filters)
                        .group_by(DataPoint.metric_type, DataPoint.source_id, bucket_expr)
                    )
                    raw_series_rows = (await session.execute(raw_stmt)).all()
                else:
                    raw_series_rows = []

                for row in raw_series_rows:
                    bucket = _series_bucket_start(row.bucket_start, resolution)
                    accumulator(row.metric_type, str(row.source_id), bucket).add(
                        sample_count=int(row.sample_count),
                        sum_value=row.sum_value,
                        max_value=row.max_value,
                        last_value=None,
                        last_timestamp=row.last_timestamp,
                    )

                last_metrics = {
                    metric_type
                    for metric_type, aggregation in aggregations.items()
                    if aggregation is Aggregation.LAST
                }
                # `not covered` as well, because this block refines a `LAST` value
                # from the raw points a rollup does *not* cover. Where the workspace
                # is proven to have none, its filters exclude everything and the query
                # is a round trip that can only return nothing.
                if last_metrics and not covered:
                    latest_bucket = func.date_trunc(resolution, DataPoint.timestamp)
                    row_number = (
                        func.row_number()
                        .over(
                            partition_by=(
                                DataPoint.metric_type,
                                DataPoint.source_id,
                                latest_bucket,
                            ),
                            order_by=(DataPoint.timestamp.desc(), DataPoint.id.desc()),
                        )
                        .label("row_number")
                    )
                    ranked = (
                        select(
                            DataPoint.metric_type.label("metric_type"),
                            DataPoint.source_id.label("source_id"),
                            latest_bucket.label("bucket_start"),
                            DataPoint.value.label("value"),
                            DataPoint.timestamp.label("timestamp"),
                            row_number,
                        )
                        .where(
                            *raw_filters,
                            DataPoint.value.is_not(None),
                            DataPoint.metric_type.in_(last_metrics),
                        )
                        .subquery()
                    )
                    latest_stmt = select(
                        ranked.c.metric_type,
                        ranked.c.source_id,
                        ranked.c.bucket_start,
                        ranked.c.value,
                        ranked.c.timestamp,
                    ).where(ranked.c.row_number == 1)
                    for row in (await session.execute(latest_stmt)).all():
                        bucket = _series_bucket_start(row.bucket_start, resolution)
                        accumulator(
                            row.metric_type, str(row.source_id), bucket
                        ).set_last_value(
                            row.value, row.timestamp
                        )

            if requested_source_id is not None:
                # An explicitly selected source is allowed to return gaps for a
                # requested metric, even when that source has no point in the
                # window.
                for metric_type in metric_types:
                    metric_sources.setdefault(metric_type, set()).add(
                        requested_source_id
                    )

            # No metric-count ceiling here, deliberately.
            #
            # There used to be one, mirroring the request-side cap below the
            # imports, and it did two things wrong at once. It fired *after* the
            # query it claimed to bound had already run and been accumulated, so
            # it protected nothing — it discarded finished work. And it failed a
            # tenant for the crime of holding data: a caller that names no metric
            # types is asking for whatever exists, and a workspace with 112
            # metric types got INVALID_ARGUMENT on every insights run, forever.
            # A hard cap could never have been the answer anyway, because
            # `home_assistant_*` and `apple_health_*` are open namespaces (rule
            # 15) whose size is the reader's own installation.
            #
            # The real budget is the one below, and it is the honest one: it
            # bounds the *response*, in the units the response is actually
            # measured in. The request-side cap stays, because rejecting an
            # over-long list of names before any work is cheap and the caller
            # wrote that list.
            metric_order = metric_types or sorted(metric_sources)
            series_count = sum(
                len(metric_sources.get(metric_type, ())) for metric_type in metric_order
            )
            if series_count * len(buckets) > MAX_SERIES_BUCKETS:
                raise ValueError("Metric series is too large")

            # Only fetched when something is actually ambiguous. Most tenants have
            # one connector per metric and pay nothing for this.
            ambiguous = [
                metric_type
                for metric_type in metric_order
                if len(metric_sources.get(metric_type, ())) > 1
            ]
            preferences: dict[str, str] = {}
            coverage: dict[tuple[str, str], int] = {}
            if ambiguous:
                # Whole-history coverage, not the window's. A primary source is a
                # property of the workspace, so resolving it from whatever window
                # this call happens to ask for would make the analysed series
                # change identity between two views — and would disagree with the
                # picker card, which counts everything. See `metric_source_coverage`.
                async with async_session_maker() as pref_session:
                    preferences = await primary_source_preferences(
                        pref_session, tenant_id
                    )
                    coverage = await metric_source_coverage(pref_session, tenant_id)

            response = pb.QueryMetricSeriesResponse()
            for metric_type in metric_order:
                source_ids = sorted(metric_sources.get(metric_type, ()))
                if len(source_ids) > 1:
                    primary, reason = resolve_primary_source(
                        source_ids,
                        preference=preferences.get(metric_type),
                        coverage={
                            source_id: coverage.get((metric_type, source_id), 0)
                            for source_id in source_ids
                        },
                    )
                    issue = response.issues.add(
                        code="AMBIGUOUS_METRIC_SOURCE",
                        metric_type=metric_type,
                        primary_source_id=primary,
                        primary_reason=reason,
                    )
                    issue.source_ids.extend(source_ids)
                for source_id in source_ids:
                    for bucket in buckets:
                        point = response.buckets.add(
                            metric_type=metric_type,
                            source_id=source_id,
                            sample_count=0,
                        )
                        point.bucket_start.CopyFrom(_to_timestamp(bucket))
                        aggregate = aggregates.get((metric_type, source_id, bucket))
                        if aggregate is None:
                            continue
                        point.sample_count = aggregate.sample_count
                        if (value := aggregate.value) is not None:
                            point.value = value
            return response

    async def QueryStrengthSets(
        self, request: pb.QueryStrengthSetsRequest, context: grpc.aio.ServicerContext
    ) -> pb.QueryStrengthSetsResponse:
        """Resistance sets in a bounded window, reassembled into rows.

        A set is stored as up to four points sharing a `set_id` — its weight, its
        repetitions, the volume they make and the peak pulse during it. No consumer
        wants those apart, and the thing they need to group by, `exercise_title`,
        lives in JSONB where only Core can read it (rule 1).

        This exists rather than a `group_by_metadata_key` dimension on
        `QueryMetricSeries` because that would put an almost-always-empty field into
        the one interface every analysis depends on, for a single caller. A
        purpose-built message says what a set is instead.
        """
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            start = _from_timestamp(request.start_time)
            end = _from_timestamp(request.end_time)
            if start is None or end is None:
                raise ValueError("start_time and end_time are required")
            if end <= start:
                raise ValueError("end_time must be after start_time")
            if end - start > MAX_SERIES_RANGE:
                raise ValueError(
                    f"Range must not exceed {MAX_SERIES_RANGE.days} days"
                )

            page_size = request.pagination.page_size or DEFAULT_SET_PAGE
            page_size = max(1, min(page_size, MAX_SET_PAGE))
            cursor, _legacy = _decode_page_token(request.pagination.page_token)

            stmt = select(DataPoint).where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
                DataPoint.metric_type.in_(sorted(_SET_METRIC_FIELDS)),
            )
            if request.HasField("source_id"):
                stmt = stmt.where(
                    DataPoint.source_id == _require_source_id(request.source_id)
                )
            if request.exercise_titles:
                stmt = stmt.where(
                    DataPoint.metadata_.op("->>")("exercise_title").in_(
                        list(request.exercise_titles)
                    )
                )
            if request.muscle_groups:
                stmt = stmt.where(
                    DataPoint.metadata_.op("->>")("muscle_group").in_(
                        list(request.muscle_groups)
                    )
                )
            if cursor is not None:
                cursor_timestamp, cursor_id = cursor
                stmt = stmt.where(
                    or_(
                        DataPoint.timestamp > cursor_timestamp,
                        and_(
                            DataPoint.timestamp == cursor_timestamp,
                            DataPoint.id > cursor_id,
                        ),
                    )
                )
            stmt = stmt.order_by(DataPoint.timestamp, DataPoint.id)
            # Four metrics make one set, so the row budget is the page size times
            # that, plus one row to tell a full page from an exhausted window.
            row_budget = page_size * len(_SET_METRIC_FIELDS)
            stmt = stmt.limit(row_budget + 1)

            async with async_session_maker() as session:
                rows = (await session.execute(stmt)).scalars().all()

            truncated = len(rows) > row_budget
            rows = rows[:row_budget]
            sets, last_row = _assemble_sets(rows)

            # A partial trailing set is dropped rather than reported half-filled: a
            # bench press whose weight arrived and whose reps did not is not a set,
            # and the next page starts before it so nothing is lost.
            if truncated and sets:
                sets = sets[:-1]

            response = pb.QueryStrengthSetsResponse(sets=sets, truncated=truncated)
            if truncated and last_row is not None:
                response.pagination.next_page_token = _encode_page_token(
                    last_row.timestamp, str(last_row.id)
                )
            return response

    async def GetDataPoint(
        self, request: pb.GetDataPointRequest, context: grpc.aio.ServicerContext
    ) -> dp_pb.DataPoint:
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            async with async_session_maker() as session:
                row = (
                    (
                        await session.execute(
                            select(DataPoint).where(
                                DataPoint.tenant_id == tenant_id,
                                DataPoint.id == request.data_point_id,
                            )
                        )
                    )
                    .scalars()
                    .first()
                )

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
                    (
                        await session.execute(
                            select(DataSource).where(DataSource.tenant_id == tenant_id)
                        )
                    )
                    .scalars()
                    .all()
                )

            # Deliberately no `config` and no credentials of any kind, encrypted
            # or otherwise. This response crosses a service boundary; rule 12
            # says secrets do not.
            return pb.ListDataSourcesResponse(
                sources=[
                    pb.DataSourceSummary(
                        id=str(row.id),
                        source_type=row.source_type or "",
                        display_name=row.display_name or "",
                    )
                    for row in rows
                ]
            )

    async def ValidateUserSession(
        self, request: pb.ValidateUserSessionRequest, context: grpc.aio.ServicerContext
    ) -> pb.ValidateUserSessionResponse:
        """Check denylist and all-session cutoff for a locally verified user JWT."""
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            if not request.user_id or not request.jti:
                raise ValueError("user_id and jti are required")
            issued_at = _from_timestamp(request.issued_at)
            if issued_at is None:
                raise ValueError("issued_at is required")

            async with async_session_maker() as session:
                revoked = await session.execute(
                    select(RevokedAccessToken.jti).where(
                        RevokedAccessToken.tenant_id == tenant_id,
                        RevokedAccessToken.jti == request.jti,
                    )
                )
                if revoked.scalar_one_or_none() is not None:
                    return pb.ValidateUserSessionResponse(
                        valid=False, code="TOKEN_REVOKED"
                    )

                user_row = (
                    await session.execute(
                        select(User.sessions_valid_from).where(
                            User.tenant_id == tenant_id,
                            User.id == request.user_id,
                        )
                    )
                ).first()

            if user_row is None:
                return pb.ValidateUserSessionResponse(
                    valid=False, code="USER_NOT_FOUND"
                )
            cutoff = user_row[0]
            if cutoff is not None and issued_at < cutoff:
                return pb.ValidateUserSessionResponse(valid=False, code="SESSION_ENDED")
            return pb.ValidateUserSessionResponse(valid=True, code="VALID")

    async def ListDueAnalysisReports(
        self, request: pb.ListDueAnalysisReportsRequest, context: grpc.aio.ServicerContext
    ) -> pb.ListDueAnalysisReportsResponse:
        """Hand out queued insight runs, claiming them in the same transaction.

        Deliberately not tenant-scoped in the request: this is a worker asking for
        work across the deployment, in the same way the sync scheduler looks at
        every connector. Each run it receives names its own tenant, and everything
        the worker then reads is scoped to that tenant (rule 2).
        """
        async with _guard(context):
            limit = max(1, min(int(request.limit or 10), 50))
            async with async_session_maker() as session:
                runs = await claim_due_analysis_runs(session, limit=limit)
                reports = [
                    pb.DueAnalysisReport(
                        run_id=str(run.id),
                        tenant_id=str(run.tenant_id),
                        params_json=json.dumps(run.params or {}),
                        request_id=run.request_id or "",
                    )
                    for run in runs
                ]
                await session.commit()
            return pb.ListDueAnalysisReportsResponse(reports=reports)

    async def PutAnalysisReport(
        self, request: pb.PutAnalysisReportRequest, context: grpc.aio.ServicerContext
    ) -> pb.PutAnalysisReportResponse:
        """Store a finished insights bundle against the run it was claimed for.

        Scoped by tenant *and* run id, so a worker cannot write a result into
        another tenant's report by presenting the wrong identifier.
        """
        async with _guard(context):
            tenant_id = _require_tenant(request.tenant_id)
            if not request.run_id:
                raise ValueError("run_id is required")

            async with async_session_maker() as session:
                run = (
                    await session.execute(
                        select(ReportRun).where(
                            ReportRun.tenant_id == tenant_id,
                            ReportRun.id == request.run_id,
                            # The kind too, not only the identifier. Scoping by
                            # tenant and id alone let an insights bundle be
                            # stored into the same tenant's `gaps` run, and it
                            # was safe only because `ListDueAnalysisReports`
                            # happens to hand out insights runs exclusively —
                            # a guarantee held by the caller, which is the kind
                            # that stops holding when someone adds a second one.
                            ReportRun.kind == "insights",
                        )
                    )
                ).scalars().first()
                if run is None:
                    return pb.PutAnalysisReportResponse(
                        stored=False, code="RUN_NOT_FOUND"
                    )
                if run.status in ("success", "error"):
                    # A retry after Core already timed the run out. Refused rather
                    # than applied: the timeout may have queued a replacement, and
                    # a late result must not overwrite a newer one.
                    return pb.PutAnalysisReportResponse(
                        stored=False, code="RUN_ALREADY_FINISHED"
                    )

                if request.error_code:
                    # `message` is the operator's English fallback, so it has to
                    # say something the code does not already say on its own.
                    fail_report_run(
                        run,
                        request.error_code,
                        f"The Analysis Service could not compute this report ({request.error_code}).",
                    )
                else:
                    try:
                        payload = json.loads(request.payload_json or "{}")
                    except ValueError:
                        raise ValueError("payload_json is not valid JSON") from None
                    if not isinstance(payload, dict):
                        raise ValueError("payload_json must encode an object")
                    finish_report_run(run, payload)
                await session.commit()
            return pb.PutAnalysisReportResponse(stored=True, code="STORED")


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
        logger.exception("[req_id=%s] gRPC handler failed", get_current_request_id())
        await self._context.abort(grpc.StatusCode.INTERNAL, "Internal error")
        return True


#: The four metrics that together describe one set, and the proto field each fills.
_SET_METRIC_FIELDS: dict[str, str] = {
    "strength_set_weight": "weight_kg",
    "strength_set_reps": "reps",
    "strength_set_volume": "volume_kg",
    "strength_set_heart_rate_max": "heart_rate_max",
}


def _set_identity(point: DataPoint) -> tuple[str, str]:
    """What makes two points the same set.

    `set_id` where the provider states one; the instant otherwise, which is what
    separates one set from the next when it does not. Paired with the exercise so
    two exercises logged in the same second cannot merge.
    """
    metadata = point.metadata_ or {}
    exercise = str(metadata.get("exercise_title") or "")
    stated = metadata.get("set_id")
    identity = str(stated) if stated else point.timestamp.isoformat()
    return (exercise, identity)


def _assemble_sets(rows: list[DataPoint]) -> tuple[list[pb.StrengthSet], DataPoint | None]:
    """Turn per-metric points back into one row per set, in time order."""
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    last_row: DataPoint | None = None
    for point in rows:
        last_row = point
        key = _set_identity(point)
        entry = grouped.get(key)
        if entry is None:
            metadata = point.metadata_ or {}
            entry = grouped[key] = {
                "at": point.timestamp,
                "session_id": str(metadata.get("session_id") or ""),
                "source_id": str(point.source_id),
                "exercise_title": str(metadata.get("exercise_title") or ""),
                "muscle_group": str(metadata.get("muscle_group") or ""),
                "set_number": int(metadata.get("set_number") or 0),
            }
            order.append(key)
        entry["at"] = min(entry["at"], point.timestamp)
        field = _SET_METRIC_FIELDS.get(point.metric_type)
        if field is not None and point.value is not None:
            entry[field] = float(point.value)

    sets: list[pb.StrengthSet] = []
    for key in order:
        entry = grouped[key]
        weight = entry.get("weight_kg")
        message = pb.StrengthSet(
            session_id=entry["session_id"],
            source_id=entry["source_id"],
            exercise_title=entry["exercise_title"],
            muscle_group=entry["muscle_group"],
            reps=entry.get("reps", 0.0),
            volume_kg=entry.get("volume_kg", 0.0),
            set_number=entry["set_number"],
            # Distinct from a weight of zero, which a provider may legitimately
            # state and which `weight_kg == 0` alone cannot tell apart from a
            # bodyweight set.
            has_weight=weight is not None,
            weight_kg=weight or 0.0,
        )
        message.at.FromDatetime(entry["at"])
        sets.append(message)
    return sets, last_row


def _encode_page_token(timestamp: datetime, point_id: str) -> str:
    """Encode a stable keyset cursor without exposing a mutable offset."""
    payload = json.dumps(
        {"timestamp": timestamp.astimezone(timezone.utc).isoformat(), "id": point_id},
        separators=(",", ":"),
    ).encode()
    return "k1." + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_page_token(
    token: str,
) -> tuple[tuple[datetime, str] | None, int | None]:
    """Decode a keyset cursor and tolerate legacy offset tokens during rollout."""
    if not token:
        return None, None
    if token.startswith("k1."):
        try:
            encoded = token[3:] + "=" * (-len(token[3:]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(encoded).decode())
            timestamp = datetime.fromisoformat(payload["timestamp"])
            point_id = payload["id"]
            if timestamp.tzinfo is None or not isinstance(point_id, str) or not point_id:
                raise ValueError
            return (timestamp.astimezone(timezone.utc), point_id), None
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("Invalid page token") from exc
    try:
        offset = int(token)
    except ValueError as exc:
        raise ValueError("Invalid page token") from exc
    if offset < 0:
        raise ValueError("Invalid page token")
    return None, offset


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
