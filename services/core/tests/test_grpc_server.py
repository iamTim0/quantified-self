"""Integration tests for Core's gRPC read API.

This is the transport AGENTS.md rule 3 mandates between the Analysis Service and
Core. It was an eleven-line `pass` stub, which is why the analyses ended up
living inside Core instead of in their own service.

The tests that matter here are the two that would let a stub-shaped bug through
unnoticed: that a caller cannot read another tenant's rows, and that an
unauthenticated caller cannot read at all. The port sits on the internal network,
but "internal" was already assumed to be a boundary once before -- that
assumption is what let a bare X-Tenant-ID header read any tenant over HTTP.

Maps to Fizzbee Invariants:
- TenantIsolation
- NoUnauthorizedAccess
- UnauthenticatedRequestsBlocked
"""

import uuid
from datetime import datetime, timedelta, timezone

import grpc
import pytest
import pytest_asyncio
from core.db.models import (
    DataPoint,
    DataSource,
    MetricRollup,
    RevokedAccessToken,
    User,
)
from core.db.session import async_session_maker
from core.grpc.server import serve_grpc
from core.security.tokens import (
    create_access_token,
    create_service_token,
    decode_access_token,
)
from google.protobuf.timestamp_pb2 import Timestamp
from quantified_self.v1 import common_pb2 as common_pb
from quantified_self.v1 import core_service_pb2 as pb
from quantified_self.v1 import core_service_pb2_grpc as pb_grpc

from tests.db_helpers import cleanup_test_tenant, create_test_tenant, owner_user_id

# Not the configured GRPC_PORT: a developer running Core locally would already
# have that bound, and the failure would look like a test bug.
TEST_PORT = 51051


def _auth() -> list[tuple[str, str]]:
    return [("authorization", f"Bearer {create_service_token()}")]


async def _seed(tenant_id: str, *, metric: str, count: int) -> str:
    """Create a data source and `count` points. Returns the source id."""
    source_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type="oura",
                display_name="Oura",
            )
        )
        await session.flush()
        for index in range(count):
            session.add(
                DataPoint(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source_id,
                    metric_type=metric,
                    timestamp=now - timedelta(days=index),
                    value=float(index),
                    idempotency_key=f"grpc-test-{uuid.uuid4().hex}",
                    metadata_={"seeded_by": "test_grpc_server"},
                )
            )
        await session.commit()
    return source_id


@pytest_asyncio.fixture
async def grpc_channel():
    server = await serve_grpc(port=TEST_PORT)
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{TEST_PORT}")
    try:
        yield channel
    finally:
        await channel.close()
        await server.stop(grace=None)


@pytest.mark.asyncio
async def test_query_returns_only_the_requested_tenants_points(grpc_channel):
    """A tenant sees its own rows and nothing else.

    Verifies Fizzbee Invariant: TenantIsolation
    """
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    try:
        await _seed(tenant_a, metric="oura_sleep_score", count=3)
        await _seed(tenant_b, metric="oura_sleep_score", count=5)

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.QueryDataPoints(
            pb.QueryDataPointsRequest(tenant_id=tenant_a), metadata=_auth()
        )

        assert len(response.data_points) == 3
        assert {p.tenant_id for p in response.data_points} == {tenant_a}
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


@pytest.mark.asyncio
async def test_unauthenticated_call_is_rejected(grpc_channel):
    """No service credential, no data.

    Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked
    """
    tenant_id = await create_test_tenant()
    try:
        await _seed(tenant_id, metric="oura_sleep_score", count=1)
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)

        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.QueryDataPoints(pb.QueryDataPointsRequest(tenant_id=tenant_id))
        assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED

        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.QueryDataPoints(
                pb.QueryDataPointsRequest(tenant_id=tenant_id),
                metadata=[("authorization", "Bearer not-a-real-credential")],
            )
        assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_validate_user_session_rejects_a_denied_jti(grpc_channel):
    """Verifies Fizzbee Invariant: RevokedMcpSessionRejectedImmediately"""
    tenant_id = await create_test_tenant()
    try:
        token, jti, expires_at = create_access_token(
            user_id=owner_user_id(tenant_id),
            tenant_id=tenant_id,
            email=f"owner-{tenant_id}@example.test",
            role="owner",
        )
        claims = decode_access_token(token)
        async with async_session_maker() as session:
            session.add(
                RevokedAccessToken(
                    jti=jti,
                    tenant_id=tenant_id,
                    user_id=owner_user_id(tenant_id),
                    expires_at=expires_at,
                    reason="logout",
                )
            )
            await session.commit()

        issued_at = Timestamp()
        issued_at.FromDatetime(datetime.fromtimestamp(claims["iat"], tz=timezone.utc))
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.ValidateUserSession(
            pb.ValidateUserSessionRequest(
                tenant_id=tenant_id,
                user_id=owner_user_id(tenant_id),
                jti=jti,
                issued_at=issued_at,
            ),
            metadata=_auth(),
        )
        assert response.valid is False
        assert response.code == "TOKEN_REVOKED"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_validate_user_session_honors_the_all_session_cutoff(grpc_channel):
    """Verifies Fizzbee Invariant: RevokedMcpSessionRejectedImmediately"""
    tenant_id = await create_test_tenant()
    try:
        token, jti, _expires_at = create_access_token(
            user_id=owner_user_id(tenant_id),
            tenant_id=tenant_id,
            email=f"owner-{tenant_id}@example.test",
            role="owner",
        )
        claims = decode_access_token(token)
        issued_at_value = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
        async with async_session_maker() as session:
            user = await session.get(User, owner_user_id(tenant_id))
            assert user is not None
            user.sessions_valid_from = issued_at_value + timedelta(seconds=1)
            await session.commit()

        issued_at = Timestamp()
        issued_at.FromDatetime(issued_at_value)
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.ValidateUserSession(
            pb.ValidateUserSessionRequest(
                tenant_id=tenant_id,
                user_id=owner_user_id(tenant_id),
                jti=jti,
                issued_at=issued_at,
            ),
            metadata=_auth(),
        )
        assert response.valid is False
        assert response.code == "SESSION_ENDED"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_user_access_token_is_not_a_service_credential(grpc_channel):
    """The two credential families are disjoint, here as well as over HTTP.

    Verifies Fizzbee Invariant: ServiceTokenScopedToInternalPaths
    """
    from core.security.tokens import create_access_token

    tenant_id = await create_test_tenant()
    try:
        token, _jti, _exp = create_access_token(
            user_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            email="user@example.test",
            role="owner",
        )
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.QueryDataPoints(
                pb.QueryDataPointsRequest(tenant_id=tenant_id),
                metadata=[("authorization", f"Bearer {token}")],
            )
        assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_missing_or_malformed_tenant_is_rejected(grpc_channel):
    """A blank or non-UUID tenant must never reach a query unfiltered."""
    stub = pb_grpc.CoreDataServiceStub(grpc_channel)

    for bad in ("", "'; DROP TABLE data_points; --", "not-a-uuid"):
        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.QueryDataPoints(
                pb.QueryDataPointsRequest(tenant_id=bad), metadata=_auth()
            )
        assert excinfo.value.code() == grpc.StatusCode.INVALID_ARGUMENT, bad


@pytest.mark.asyncio
async def test_pagination_walks_the_whole_window_exactly_once(grpc_channel):
    """Every point is returned once across pages, in timestamp order.

    A page token that failed to advance would loop forever; one that overshot
    would silently drop data. Both look like "analysis is a bit off" downstream,
    so the walk is asserted rather than assumed.
    """
    tenant_id = await create_test_tenant()
    try:
        await _seed(tenant_id, metric="steps", count=7)
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)

        seen: list[str] = []
        token = ""
        for _ in range(10):  # bounded so a non-advancing token fails, not hangs
            response = await stub.QueryDataPoints(
                pb.QueryDataPointsRequest(
                    tenant_id=tenant_id,
                    pagination=common_pb.PaginationRequest(
                        page_size=3, page_token=token
                    ),
                ),
                metadata=_auth(),
            )
            seen.extend(p.id for p in response.data_points)
            token = response.pagination.next_page_token
            if not token:
                break

        assert not token, "pagination did not terminate"
        assert len(seen) == 7
        assert len(set(seen)) == 7, "a point was returned on more than one page"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_metric_series_uses_registry_aggregation_and_emits_gaps(grpc_channel):
    """The series RPC is tenant-scoped, metric-aware, and explicit about gaps."""
    tenant_id = await create_test_tenant()
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    source_id = str(uuid.uuid4())
    rollup_source_id = str(uuid.uuid4())
    try:
        async with async_session_maker() as session:
            session.add_all(
                [
                    DataSource(
                        id=source_id,
                        tenant_id=tenant_id,
                        source_type="oura",
                        display_name="Oura",
                    ),
                    DataSource(
                        id=rollup_source_id,
                        tenant_id=tenant_id,
                        source_type="apple_health",
                        display_name="Apple Health",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="steps",
                        timestamp=start + timedelta(hours=1),
                        value=100.0,
                        idempotency_key=f"series-steps-1-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="steps",
                        timestamp=start + timedelta(hours=2),
                        value=250.0,
                        idempotency_key=f"series-steps-2-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="heart_rate",
                        timestamp=start + timedelta(hours=3),
                        value=60.0,
                        idempotency_key=f"series-heart-1-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="heart_rate",
                        timestamp=start + timedelta(hours=4),
                        value=80.0,
                        idempotency_key=f"series-heart-2-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="body_weight",
                        timestamp=start + timedelta(hours=5),
                        value=70.0,
                        idempotency_key=f"series-weight-1-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="body_weight",
                        timestamp=start + timedelta(hours=6),
                        value=72.0,
                        idempotency_key=f"series-weight-2-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="heart_rate_max",
                        timestamp=start + timedelta(hours=5),
                        value=90.0,
                        idempotency_key=f"series-max-1-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="heart_rate_max",
                        timestamp=start + timedelta(hours=6),
                        value=100.0,
                        idempotency_key=f"series-max-2-{uuid.uuid4().hex}",
                    ),
                    DataPoint(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        source_id=source_id,
                        metric_type="steps",
                        timestamp=start + timedelta(days=2, hours=1),
                        value=40.0,
                        idempotency_key=f"series-steps-3-{uuid.uuid4().hex}",
                    ),
                    MetricRollup(
                        tenant_id=tenant_id,
                        source_id=rollup_source_id,
                        metric_type="steps",
                        resolution="day",
                        bucket_start=start,
                        value=1000.0,
                        sample_count=2,
                        sum_value=1000.0,
                        min_value=400.0,
                        max_value=600.0,
                        first_value=400.0,
                        last_value=600.0,
                        first_timestamp=start + timedelta(hours=7),
                        last_timestamp=start + timedelta(hours=8),
                        metadata_={"derived_by": "sum"},
                        is_provider_total=False,
                    ),
                ]
            )
            await session.commit()

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        start_stamp = Timestamp()
        start_stamp.FromDatetime(start)
        end_stamp = Timestamp()
        end_stamp.FromDatetime(start + timedelta(days=3))
        response = await stub.QueryMetricSeries(
            pb.QueryMetricSeriesRequest(
                tenant_id=tenant_id,
                metric_types=[
                    "steps",
                    "heart_rate",
                    "body_weight",
                    "heart_rate_max",
                ],
                start_time=start_stamp,
                end_time=end_stamp,
                resolution=pb.METRIC_SERIES_RESOLUTION_DAY,
            ),
            metadata=_auth(),
        )

        buckets = {
            (
                bucket.metric_type,
                bucket.source_id,
                bucket.bucket_start.ToDatetime().date(),
            ): bucket
            for bucket in response.buckets
        }
        assert len(response.buckets) == 15
        assert {
            source_id
            for (metric_type, source_id, _), bucket in buckets.items()
            if metric_type == "steps" and bucket.sample_count
        } == {source_id, rollup_source_id}
        assert response.issues[0].code == "AMBIGUOUS_METRIC_SOURCE"
        assert response.issues[0].metric_type == "steps"
        assert set(response.issues[0].source_ids) == {source_id, rollup_source_id}
        assert buckets[("steps", source_id, start.date())].value == pytest.approx(350.0)
        assert buckets[("steps", source_id, start.date())].sample_count == 2
        assert buckets[("steps", rollup_source_id, start.date())].value == pytest.approx(
            1000.0
        )
        assert buckets[("steps", rollup_source_id, start.date())].sample_count == 2
        assert buckets[("heart_rate", source_id, start.date())].value == pytest.approx(
            70.0
        )
        assert buckets[("heart_rate", source_id, start.date())].sample_count == 2
        assert buckets[("body_weight", source_id, start.date())].value == pytest.approx(
            72.0
        )
        assert buckets[("body_weight", source_id, start.date())].sample_count == 2
        assert buckets[("heart_rate_max", source_id, start.date())].value == pytest.approx(
            100.0
        )
        assert buckets[("heart_rate_max", source_id, start.date())].sample_count == 2
        assert buckets[("steps", source_id, (start + timedelta(days=1)).date())].sample_count == 0
        assert not buckets[
            ("steps", source_id, (start + timedelta(days=1)).date())
        ].HasField("value")
        assert buckets[
            ("steps", source_id, (start + timedelta(days=2)).date())
        ].value == pytest.approx(40.0)
        assert buckets[
            ("steps", source_id, (start + timedelta(days=2)).date())
        ].sample_count == 1

        selected = await stub.QueryMetricSeries(
            pb.QueryMetricSeriesRequest(
                tenant_id=tenant_id,
                metric_types=["steps"],
                source_id=source_id,
                start_time=start_stamp,
                end_time=end_stamp,
                resolution=pb.METRIC_SERIES_RESOLUTION_DAY,
            ),
            metadata=_auth(),
        )
        assert not selected.issues
        assert {bucket.source_id for bucket in selected.buckets} == {source_id}
        assert selected.buckets[0].value == pytest.approx(350.0)
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_metric_series_rejects_a_cross_tenant_source_id(grpc_channel):
    """A source selector cannot be used as a cross-tenant existence oracle.

    Verifies Fizzbee Invariant: TenantIsolation
    """
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    source_b = await _seed(tenant_b, metric="steps", count=1)
    try:
        start = datetime.now(timezone.utc) - timedelta(days=1)
        end = datetime.now(timezone.utc) + timedelta(days=1)
        start_stamp = Timestamp()
        start_stamp.FromDatetime(start)
        end_stamp = Timestamp()
        end_stamp.FromDatetime(end)
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.QueryMetricSeries(
                pb.QueryMetricSeriesRequest(
                    tenant_id=tenant_a,
                    metric_types=["steps"],
                    source_id=source_b,
                    start_time=start_stamp,
                    end_time=end_stamp,
                    resolution=pb.METRIC_SERIES_RESOLUTION_DAY,
                ),
                metadata=_auth(),
            )
        assert excinfo.value.code() == grpc.StatusCode.NOT_FOUND
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


@pytest.mark.asyncio
async def test_list_data_sources_carries_no_credentials(grpc_channel):
    """Provenance needs the source type; it must not carry the connector secret.

    Verifies Fizzbee Invariant: SecretsAlwaysEncryptedAtRest
    """
    tenant_id = await create_test_tenant()
    try:
        await _seed(tenant_id, metric="oura_sleep_score", count=1)
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.ListDataSources(
            pb.ListDataSourcesRequest(tenant_id=tenant_id), metadata=_auth()
        )

        assert [s.source_type for s in response.sources] == ["oura"]
        # The message has no field that could carry one, which is the point. The
        # set is pinned exactly rather than checked for absences, so *adding* a
        # field is a decision somebody has to make here on purpose --
        # `display_name` arrived with multi-instance connectors and is a label the
        # user typed, never a credential.
        assert {f.name for f in pb.DataSourceSummary.DESCRIPTOR.fields} == {
            "id",
            "source_type",
            "display_name",
        }
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_get_data_point_hides_other_tenants_behind_not_found(grpc_channel):
    """Cross-tenant reads are NOT_FOUND, not PERMISSION_DENIED.

    Distinguishing the two would confirm that an id exists.

    Verifies Fizzbee Invariant: NoUnauthorizedAccess
    """
    tenant_a = await create_test_tenant()
    tenant_b = await create_test_tenant()
    try:
        await _seed(tenant_a, metric="oura_sleep_score", count=1)
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)

        owned = await stub.QueryDataPoints(
            pb.QueryDataPointsRequest(tenant_id=tenant_a), metadata=_auth()
        )
        point_id = owned.data_points[0].id

        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.GetDataPoint(
                pb.GetDataPointRequest(tenant_id=tenant_b, data_point_id=point_id),
                metadata=_auth(),
            )
        assert excinfo.value.code() == grpc.StatusCode.NOT_FOUND
    finally:
        await cleanup_test_tenant(tenant_a)
        await cleanup_test_tenant(tenant_b)


# ── QueryStrengthSets ────────────────────────────────────────────────────────


async def _seed_sets(tenant_id: str, plan: list[tuple[str, str, float | None, int]]) -> str:
    """One source and one set per entry: (exercise, muscle group, weight, reps).

    A weight of `None` is a bodyweight set — reps and no load, which is a real
    thing a gym log records and which `has_weight` exists to distinguish from a
    stated zero.
    """
    source_id = str(uuid.uuid4())
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id, tenant_id=tenant_id,
                source_type="streak", display_name="Streak",
            )
        )
        await session.flush()
        for index, (exercise, group, weight, reps) in enumerate(plan):
            at = base + timedelta(minutes=index * 3)
            common = {
                "exercise_title": exercise,
                "muscle_group": group,
                "set_id": f"set-{index}",
                "set_number": index + 1,
                "session_id": "streak:abc123",
            }
            values = [("strength_set_reps", float(reps))]
            if weight is not None:
                values += [
                    ("strength_set_weight", weight),
                    ("strength_set_volume", weight * reps),
                ]
            for metric, value in values:
                session.add(
                    DataPoint(
                        id=str(uuid.uuid4()), tenant_id=tenant_id, source_id=source_id,
                        metric_type=metric, timestamp=at, value=value,
                        idempotency_key=f"set-{uuid.uuid4().hex}", metadata_=common,
                    )
                )
        await session.commit()
    return source_id


def _set_window() -> tuple[Timestamp, Timestamp]:
    start, end = Timestamp(), Timestamp()
    start.FromDatetime(datetime.now(timezone.utc) - timedelta(days=3))
    end.FromDatetime(datetime.now(timezone.utc) + timedelta(days=1))
    return start, end


@pytest.mark.asyncio
async def test_strength_sets_are_reassembled_into_rows(grpc_channel):
    """Four metrics sharing a `set_id` are one set, not four points.

    Analysis holds no database connection (rule 3), so this is the only way it can
    see an exercise name at all — the grouping key lives in JSONB.
    """
    tenant_id = await create_test_tenant()
    try:
        await _seed_sets(tenant_id, [
            ("Back Squat", "quads", 100.0, 5),
            ("Back Squat", "quads", 110.0, 3),
            ("Pull-up", "back", None, 12),
        ])
        start, end = _set_window()

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(tenant_id=tenant_id, start_time=start, end_time=end),
            metadata=_auth(),
        )

        assert len(response.sets) == 3
        first = response.sets[0]
        assert first.exercise_title == "Back Squat"
        assert first.muscle_group == "quads"
        assert first.weight_kg == 100.0
        assert first.reps == 5
        assert first.volume_kg == 500.0
        assert first.has_weight is True
        assert first.session_id == "streak:abc123"
        assert first.set_number == 1

        bodyweight = response.sets[2]
        assert bodyweight.exercise_title == "Pull-up"
        assert bodyweight.reps == 12
        # Not the same as a stated zero, which is why the flag exists.
        assert bodyweight.has_weight is False
        assert bodyweight.weight_kg == 0.0
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_strength_sets_are_scoped_to_the_calling_tenant(grpc_channel):
    """Verifies Fizzbee Invariant: TenantIsolation."""
    owner = await create_test_tenant()
    other = await create_test_tenant()
    try:
        await _seed_sets(owner, [("Deadlift", "hamstrings", 140.0, 5)])
        start, end = _set_window()

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(tenant_id=other, start_time=start, end_time=end),
            metadata=_auth(),
        )
        assert list(response.sets) == []
    finally:
        await cleanup_test_tenant(owner)
        await cleanup_test_tenant(other)


@pytest.mark.asyncio
async def test_strength_sets_can_be_filtered_by_exercise_and_muscle(grpc_channel):
    tenant_id = await create_test_tenant()
    try:
        await _seed_sets(tenant_id, [
            ("Back Squat", "quads", 100.0, 5),
            ("Bench Press", "chest", 80.0, 8),
        ])
        start, end = _set_window()
        stub = pb_grpc.CoreDataServiceStub(grpc_channel)

        by_exercise = await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(
                tenant_id=tenant_id, start_time=start, end_time=end,
                exercise_titles=["Bench Press"],
            ),
            metadata=_auth(),
        )
        assert [s.exercise_title for s in by_exercise.sets] == ["Bench Press"]

        by_muscle = await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(
                tenant_id=tenant_id, start_time=start, end_time=end,
                muscle_groups=["quads"],
            ),
            metadata=_auth(),
        )
        assert [s.exercise_title for s in by_muscle.sets] == ["Back Squat"]
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_page_of_sets_reports_that_it_was_cut(grpc_channel):
    """A shortened answer says so, rather than reading as a short training block."""
    tenant_id = await create_test_tenant()
    try:
        await _seed_sets(
            tenant_id,
            [("Back Squat", "quads", 100.0 + index, 5) for index in range(6)],
        )
        start, end = _set_window()

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(
                tenant_id=tenant_id, start_time=start, end_time=end,
                pagination=common_pb.PaginationRequest(page_size=2),
            ),
            metadata=_auth(),
        )

        assert response.truncated is True
        assert response.pagination.next_page_token
        assert len(response.sets) <= 2
        # And the cursor actually advances rather than repeating the first page.
        nxt = await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(
                tenant_id=tenant_id, start_time=start, end_time=end,
                pagination=common_pb.PaginationRequest(
                    page_size=2, page_token=response.pagination.next_page_token
                ),
            ),
            metadata=_auth(),
        )
        assert {s.weight_kg for s in nxt.sets}.isdisjoint({s.weight_kg for s in response.sets})
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_unbounded_strength_range_is_refused(grpc_channel):
    """Bounded exactly like the series call: no window, no answer."""
    tenant_id = await create_test_tenant()
    try:
        start, end = Timestamp(), Timestamp()
        start.FromDatetime(datetime.now(timezone.utc) - timedelta(days=400))
        end.FromDatetime(datetime.now(timezone.utc))

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        with pytest.raises(grpc.aio.AioRpcError) as excinfo:
            await stub.QueryStrengthSets(
                pb.QueryStrengthSetsRequest(
                    tenant_id=tenant_id, start_time=start, end_time=end
                ),
                metadata=_auth(),
            )
        assert excinfo.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_strength_sets_require_a_service_credential(grpc_channel):
    """Verifies Fizzbee Invariant: CredentialBoundToIdentity."""
    stub = pb_grpc.CoreDataServiceStub(grpc_channel)
    start, end = _set_window()
    with pytest.raises(grpc.aio.AioRpcError) as excinfo:
        await stub.QueryStrengthSets(
            pb.QueryStrengthSetsRequest(
                tenant_id=str(uuid.uuid4()), start_time=start, end_time=end
            )
        )
    assert excinfo.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_a_last_metric_on_a_fully_rolled_up_workspace_does_not_crash(grpc_channel):
    """The production failure behind every "report did not complete" message.

    `raw_filters` was built inside `if not covered:` while the `LAST`-metric
    refinement below read it unconditionally. So a *day* series over a workspace
    proven to hold no point outside its day rollups raised `UnboundLocalError` --
    and that combination is the normal one for an established workspace.

    The consequence was invisible from the dashboard: the gRPC call returned
    INTERNAL, the Analysis worker read that as "Core unavailable" and re-raised, the
    run stayed in flight, and thirty minutes later the sweep failed it as a timeout.
    The reader was told the analysis was too slow. It never ran at all.
    """
    from core.rollup_coverage import (
        forget_day_rollup_coverage,
        remember_day_rollup_coverage,
    )

    tenant_id = await create_test_tenant()
    start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=2)

    try:
        source_id = str(uuid.uuid4())
        async with async_session_maker() as session:
            session.add(
                DataSource(
                    id=source_id,
                    tenant_id=tenant_id,
                    source_type="apple_health",
                    display_name="Phone",
                )
            )
            session.add(
                MetricRollup(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    # `body_weight` is a LAST metric, which is what reaches the block.
                    metric_type="body_weight",
                    resolution="day",
                    bucket_start=start,
                    sample_count=1,
                    sum_value=81.0,
                    min_value=81.0,
                    max_value=81.0,
                    first_value=81.0,
                    last_value=81.0,
                    first_timestamp=start,
                    last_timestamp=start,
                    metadata_={},
                    is_provider_total=False,
                )
            )
            await session.commit()

        # The state the bug needs: this workspace is known to hold no point outside
        # a day rollup, so the raw scan is skipped.
        remember_day_rollup_coverage(tenant_id)

        start_stamp = Timestamp()
        start_stamp.FromDatetime(start)
        end_stamp = Timestamp()
        end_stamp.FromDatetime(start + timedelta(days=3))

        stub = pb_grpc.CoreDataServiceStub(grpc_channel)
        response = await stub.QueryMetricSeries(
            pb.QueryMetricSeriesRequest(
                tenant_id=tenant_id,
                metric_types=["body_weight"],
                start_time=start_stamp,
                end_time=end_stamp,
                resolution=pb.METRIC_SERIES_RESOLUTION_DAY,
            ),
            metadata=_auth(),
        )

        weights = [b for b in response.buckets if b.metric_type == "body_weight"]
        assert weights, "the rollup's own value must still be returned"
        # The value the rollup already carried, not one the skipped raw scan found.
        assert any(bucket.value == 81.0 for bucket in weights)
    finally:
        forget_day_rollup_coverage(tenant_id)
        await cleanup_test_tenant(tenant_id)
