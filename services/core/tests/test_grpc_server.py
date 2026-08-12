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
from core.db.models import DataPoint, DataSource, RevokedAccessToken, User
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
