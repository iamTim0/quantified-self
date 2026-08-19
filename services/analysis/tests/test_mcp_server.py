"""Protocol and tenant-boundary tests for the stateless Analysis MCP server."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import analysis.mcp_server as mcp_module
import jwt
import pytest
from analysis.config import settings
from analysis.core_client import MetricPoint, MetricSummary, PointBatch
from analysis.main import app
from fastapi.testclient import TestClient
from shared_schemas.metrics import describe

TENANT_A = "22222222-2222-2222-2222-222222222222"
TENANT_B = "33333333-3333-3333-3333-333333333333"
USER_ID = "11111111-1111-1111-1111-111111111111"


class FakeCoreClient:
    """Tenant-aware gRPC stand-in with no shared query result state."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.point_reads = 0
        self.summary_calls = 0
        self.last_query: dict[str, Any] = {}

    async def fetch_metric_types(self, tenant_id: str, *, request_id: str) -> list[str]:
        self.calls.append((tenant_id, request_id))
        return ["sleep_score", "steps"]

    async def fetch_metric_summaries(
        self,
        tenant_id: str,
        *,
        request_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[MetricSummary]:
        del start, end
        self.calls.append((tenant_id, request_id))
        self.summary_calls += 1
        return [
            MetricSummary(
                metric_type="sleep_duration",
                point_count=30,
                first_observed_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
            MetricSummary(
                metric_type="steps",
                point_count=12_000,
                first_observed_at=datetime(2026, 7, 1, tzinfo=UTC),
                last_observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            ),
        ]

    async def fetch_source_types(self, tenant_id: str, *, request_id: str) -> list[str]:
        self.calls.append((tenant_id, request_id))
        return ["manual"]

    async def fetch_source_map(
        self, tenant_id: str, *, request_id: str
    ) -> dict[str, str]:
        self.calls.append((tenant_id, request_id))
        return {"source-1": "manual"}

    async def validate_user_session(
        self, tenant_id: str, *, request_id: str, **kwargs: Any
    ) -> tuple[bool, str]:
        del kwargs
        self.calls.append((tenant_id, request_id))
        return True, "VALID"

    async def fetch_points_bounded(
        self,
        tenant_id: str,
        *,
        start: datetime,
        end: datetime,
        request_id: str,
        metric_type: str | None,
        max_points: int | None,
        min_value: float | None = None,
        max_value: float | None = None,
        activity_type: str | None = None,
        order: str = "time",
    ) -> PointBatch:
        del start, end
        self.calls.append((tenant_id, request_id))
        self.point_reads += 1
        self.last_query = {
            "max_points": max_points,
            "min_value": min_value,
            "max_value": max_value,
            "activity_type": activity_type,
            "order": order,
        }
        value = 100.0 if tenant_id == TENANT_A else 200.0
        name = metric_type or "steps"
        return PointBatch(
            points=[
                MetricPoint(
                    name,
                    datetime(2026, 8, 1, tzinfo=UTC),
                    value,
                    source_id="source-1",
                    metadata={"provider_value": value, "units": "count"},
                )
            ],
            truncated=False,
        )


class FailingCoreClient(FakeCoreClient):
    async def fetch_points_bounded(self, *args: Any, **kwargs: Any) -> PointBatch:
        del args, kwargs
        raise RuntimeError("sensitive implementation detail")


class RevokedCoreClient(FakeCoreClient):
    async def validate_user_session(
        self, tenant_id: str, *, request_id: str, **kwargs: Any
    ) -> tuple[bool, str]:
        del tenant_id, request_id, kwargs
        return False, "TOKEN_REVOKED"


@pytest.fixture(autouse=True)
def _available_core(monkeypatch):
    """Every protocol test starts with an independent, valid Core session check."""
    monkeypatch.setattr(mcp_module, "core_client", FakeCoreClient())


def _token(tenant_id: str = TENANT_A, **overrides: Any) -> str:
    claims: dict[str, Any] = {
        "user_id": USER_ID,
        "tenant_id": tenant_id,
        "role": "owner",
        "iss": "qs-core",
        "aud": "qs-api",
        "token_type": "access",
        "jti": "44444444-4444-4444-4444-444444444444",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=30),
    }
    claims.update(overrides)
    return jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _meta() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "analysis-test", "version": "1"},
    }


def _headers(
    method: str,
    *,
    token: str | None = None,
    name: str | None = None,
    version: str = "2026-07-28",
    request_id: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token or _token()}",
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if name is not None:
        headers["Mcp-Name"] = name
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    return headers


def _request(
    method: str, request_id: int, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    payload = dict(params or {})
    payload["_meta"] = _meta()
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": payload}


def _call_series(client: TestClient, token: str, request_id: str) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        headers=_headers(
            "tools/call",
            name="query_metric_series",
            token=token,
            request_id=request_id,
        ),
        json=_request(
            "tools/call",
            3,
            {
                "name": "query_metric_series",
                "arguments": {
                    "metric_type": "steps",
                    "start": "2026-08-01T00:00:00Z",
                    "end": "2026-08-03T00:00:00Z",
                },
            },
        ),
    )
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


def test_discovery_uses_the_sessionless_protocol() -> None:
    """Verifies Fizzbee Invariant: NoProtocolSessionState"""
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request("server/discover", 1),
        )

    assert response.status_code == 200
    assert response.json()["result"]["supportedVersions"] == ["2026-07-28"]
    assert response.json()["result"]["capabilities"] == {
        "tools": {"listChanged": False}
    }
    assert "mcp-session-id" not in response.headers


def test_tools_are_read_only_and_have_no_identity_arguments() -> None:
    """Verifies Fizzbee Invariant: AllToolsAreReadOnly"""
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=_headers("tools/list"),
            json=_request("tools/list", 2),
        )

    tools = response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "list_metrics",
        "query_metric_series",
        "analyze_metrics",
        "get_data_quality",
    }
    for tool in tools:
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["destructiveHint"] is False
        properties = tool["inputSchema"].get("properties", {})
        assert "tenant_id" not in properties
        assert "user_id" not in properties


def test_legacy_initialization_and_session_headers_are_rejected() -> None:
    """Verifies Fizzbee Invariant: NoProtocolSessionState"""
    with TestClient(app, base_url="http://localhost") as client:
        legacy = client.post(
            "/mcp",
            headers=_headers("initialize", version="2025-11-25"),
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        session_headers = _headers("tools/list")
        session_headers["Mcp-Session-Id"] = "legacy-session"
        session = client.post(
            "/mcp",
            headers=session_headers,
            json=_request("tools/list", 2),
        )

    assert legacy.status_code == 400
    assert legacy.json()["error"]["data"]["code"] == "UNSUPPORTED_PROTOCOL_VERSION"
    assert session.status_code == 400
    assert session.json()["error"]["data"]["code"] == "SESSION_PROTOCOL_REJECTED"


def test_each_request_authenticates_without_reusing_the_previous_identity() -> None:
    """Verifies Fizzbee Invariant: EveryRequestAuthenticatesIndependently"""
    with TestClient(app, base_url="http://localhost") as client:
        accepted = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request("server/discover", 1),
        )
        unauthenticated_headers = _headers("server/discover")
        unauthenticated_headers["Authorization"] = ""
        rejected = client.post(
            "/mcp",
            headers=unauthenticated_headers,
            json=_request("server/discover", 2),
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 401
    assert rejected.json()["error"]["data"]["code"] == "AUTHENTICATION_FAILED"


def test_tenant_header_cannot_override_the_authenticated_principal() -> None:
    """Verifies Fizzbee Invariant: PrincipalIsNeverModelSupplied"""
    headers = _headers("server/discover")
    headers["X-Tenant-ID"] = TENANT_B
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json=_request("server/discover", 1),
        )

    assert response.status_code == 403
    assert response.json()["error"]["data"]["code"] == "TENANT_HEADER_MISMATCH"


def test_core_revocation_rejects_the_request_immediately(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: RevokedMcpSessionRejectedImmediately"""
    monkeypatch.setattr(mcp_module, "core_client", RevokedCoreClient())
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=_headers("server/discover"),
            json=_request("server/discover", 1),
        )

    assert response.status_code == 401
    assert response.json()["error"]["data"]["code"] == "TOKEN_REVOKED"


def test_tool_results_and_core_calls_stay_in_the_token_tenant(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: NoCrossTenantResults"""
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        tenant_a = _call_series(client, _token(TENANT_A), "req_a")
        tenant_b = _call_series(client, _token(TENANT_B), "req_b")

    assert tenant_a["points"][0]["value"] == 100.0
    assert tenant_b["points"][0]["value"] == 200.0
    assert {tenant for tenant, _ in fake.calls} == {TENANT_A, TENANT_B}


def test_model_cannot_supply_a_tenant_and_request_id_reaches_core(monkeypatch) -> None:
    """Verifies Fizzbee Invariants: PrincipalIsNeverModelSupplied, RequestIdReachesCore"""
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=_headers(
                "tools/call",
                name="query_metric_series",
                request_id="req_traceable",
            ),
            json=_request(
                "tools/call",
                4,
                {
                    "name": "query_metric_series",
                    "arguments": {
                        "metric_type": "steps",
                        "tenant_id": TENANT_B,
                    },
                },
            ),
        )

    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False
    assert all(tenant == TENANT_A for tenant, _ in fake.calls)
    # An unknown identity argument is ignored; the authenticated principal is
    # still the only tenant forwarded to Core.
    assert fake.calls


def test_request_id_is_propagated_to_every_core_call(monkeypatch) -> None:
    """Verifies Fizzbee Invariant: RequestIdReachesCore"""
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)
    with TestClient(app, base_url="http://localhost") as client:
        result = _call_series(client, _token(), "req_traceable")

    assert result["provenance"]["request_id"] == "req_traceable"
    assert fake.calls
    assert all(request_id == "req_traceable" for _, request_id in fake.calls)


def test_daily_sum_metric_collapses_reimports_before_weekly_sum() -> None:
    """A daily total must not be counted twice when the day was reimported."""
    points = [
        MetricPoint("steps", datetime(2026, 8, 3, 6, tzinfo=UTC), 100.0),
        MetricPoint("steps", datetime(2026, 8, 3, 9, tzinfo=UTC), 200.0),
        MetricPoint("steps", datetime(2026, 8, 4, 9, tzinfo=UTC), 300.0),
    ]
    daily, _ = mcp_module._series_points(
        points,
        bucket="day",
        definition=describe("steps"),
        max_points=100,
    )
    weekly, _ = mcp_module._series_points(
        points,
        bucket="week",
        definition=describe("steps"),
        max_points=100,
    )

    assert [point.value for point in daily] == [200.0, 300.0]
    assert [point.value for point in weekly] == [500.0]


def test_catalogued_values_are_labelled_with_registry_unit() -> None:
    """Provider provenance units must not relabel already converted values."""
    definition = describe("distance")
    points = [
        MetricPoint(
            "distance",
            datetime(2026, 8, 3, tzinfo=UTC),
            1.609344,
            metadata={"provider_value": 1.0, "units": "mi"},
        )
    ]
    assert mcp_module._result_unit(points, definition) == "km"


def test_mcp_rejects_an_implicit_cross_source_series() -> None:
    """MCP never turns two connector instances into one silent aggregate."""
    batch = PointBatch(
        points=[
            MetricPoint("steps", datetime(2026, 8, 1, tzinfo=UTC), 350.0, "source-a"),
            MetricPoint("steps", datetime(2026, 8, 1, tzinfo=UTC), 1000.0, "source-b"),
        ],
        truncated=False,
    )
    with pytest.raises(mcp_module.MCPError) as excinfo:
        mcp_module._require_single_source(
            batch, metric_type="steps", source_id=None
        )
    assert excinfo.value.data["code"] == "AMBIGUOUS_METRIC_SOURCE"
    assert excinfo.value.data["source_ids"] == ["source-a", "source-b"]


def test_unexpected_tool_errors_are_sanitized(monkeypatch) -> None:
    """Internal exception messages must never become model-visible tool output."""
    monkeypatch.setattr(mcp_module, "core_client", FailingCoreClient())
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=_headers("tools/call", name="query_metric_series"),
            json=_request(
                "tools/call",
                6,
                {
                    "name": "query_metric_series",
                    "arguments": {"metric_type": "steps"},
                },
            ),
        )

    result = response.json()["result"]
    assert result["isError"] is True
    assert "INTERNAL_TOOL_ERROR" in result["content"][0]["text"]
    assert "sensitive implementation detail" not in response.text


def test_data_quality_reports_gaps_outliers_and_source_distribution(
    monkeypatch,
) -> None:
    """Data-quality evidence stays structured and source-auditable."""
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            headers=_headers("tools/call", name="get_data_quality"),
            json=_request(
                "tools/call",
                5,
                {
                    "name": "get_data_quality",
                    "arguments": {
                        "metric_types": ["steps"],
                        "start": "2026-08-01T00:00:00Z",
                        "end": "2026-08-03T00:00:00Z",
                    },
                },
            ),
        )

    assert response.status_code == 200
    quality = response.json()["result"]["structuredContent"]["metrics"][0]
    assert quality["missing_expected_days"] == 1
    assert quality["plausible_outlier_count"] == 0
    assert quality["source_point_counts"] == {"manual": 1}


def _call_list_metrics(
    client: TestClient, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        headers=_headers("tools/call", name="list_metrics", request_id="req_catalog"),
        json=_request(
            "tools/call",
            9,
            {"name": "list_metrics", "arguments": arguments or {}},
        ),
    )
    return response.json()


def test_the_catalogue_is_counted_by_core_not_read_here(monkeypatch) -> None:
    """A question about names must not cost what the tenant has recorded.

    This tool used to fetch every point of every metric in its window purely to
    group them by name. Three location metrics at ~26k points per 90 days pushed
    that past the 100k transfer bound, `_points` treats a truncated read as fatal,
    and the first tool any model calls began failing for good.
    """
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        result = _call_list_metrics(client)["result"]

    catalogue = result["structuredContent"]
    assert [item["metric_type"] for item in catalogue["metrics"]] == [
        "sleep_duration",
        "steps",
    ]
    assert [item["observed_count"] for item in catalogue["metrics"]] == [30, 12_000]
    assert catalogue["provenance"]["point_count"] == 12_030
    assert catalogue["provenance"]["truncated"] is False
    assert fake.summary_calls == 1
    assert fake.point_reads == 0, "the catalogue must not transfer data points"


def test_an_undescribable_metric_does_not_take_the_catalogue_down(monkeypatch) -> None:
    """One stored name the registry cannot describe must not blank the catalogue.

    It is named in the result rather than dropped (rule 19): a model that is told
    what it could not read about can say so, where one that is told nothing
    answers as though the metric were absent.
    """
    fake = FakeCoreClient()

    async def _with_a_stranger(tenant_id, *, request_id, start=None, end=None):
        del start, end
        fake.calls.append((tenant_id, request_id))
        return [
            MetricSummary(metric_type="steps", point_count=3),
            MetricSummary(metric_type="not_a_registered_metric", point_count=7),
        ]

    fake.fetch_metric_summaries = _with_a_stranger
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        catalogue = _call_list_metrics(client)["result"]["structuredContent"]

    assert [item["metric_type"] for item in catalogue["metrics"]] == ["steps"]
    assert catalogue["undescribed_metric_types"] == ["not_a_registered_metric"]


def test_a_refused_tool_call_says_why(monkeypatch) -> None:
    """The caller gets this server's own code, not one opaque failure for all.

    Every refusal here is written for a caller to act on — shorten the window, fix
    the metric name. Collapsing them into `INTERNAL_TOOL_ERROR` left a model with
    nothing to correct, so it stopped asking; and since nothing logged the reason
    either, the failure was invisible from both ends at once.
    """
    monkeypatch.setattr(mcp_module, "core_client", FakeCoreClient())

    with TestClient(app, base_url="http://localhost") as client:
        result = _call_list_metrics(
            client,
            {"start": "2020-01-01T00:00:00Z", "end": "2026-08-01T00:00:00Z"},
        )

    assert result["error"]["data"]["code"] == "TIME_RANGE_TOO_LARGE"


def _ranking_points() -> list[MetricPoint]:
    """Two days of workouts, so a ranking of points differs from one of days."""
    return [
        MetricPoint("workout_distance", datetime(2026, 8, 1, 9, tzinfo=UTC), 5.0),
        MetricPoint("workout_distance", datetime(2026, 8, 1, 17, tzinfo=UTC), 6.0),
        MetricPoint("workout_distance", datetime(2026, 8, 2, 9, tzinfo=UTC), 8.0),
    ]


def _call_series_tool(client: TestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        headers=_headers("tools/call", name="query_metric_series", request_id="req_rank"),
        json=_request(
            "tools/call",
            11,
            {"name": "query_metric_series", "arguments": arguments},
        ),
    )
    return response.json()


def test_a_raw_ranking_is_ordered_and_bounded_by_core(monkeypatch) -> None:
    """"My largest three" must cost three rows, not the window they were found in."""
    fake = FakeCoreClient()

    async def _ranked(tenant_id, *, order="time", max_points=None, **kwargs):
        del kwargs
        fake.last_query = {"order": order, "max_points": max_points}
        points = sorted(_ranking_points(), key=lambda point: point.value, reverse=True)
        return PointBatch(points=points[: max_points or len(points)], truncated=False)

    fake.fetch_points_bounded = _ranked
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        result = _call_series_tool(
            client,
            {
                "metric_type": "workout_distance",
                "bucket": "raw",
                "order": "value_desc",
                "max_points": 2,
            },
        )["result"]["structuredContent"]

    assert fake.last_query == {"order": "value_desc", "max_points": 2}, (
        "the order and the bound belong in Core's query, not in a local sort"
    )
    assert [point["value"] for point in result["points"]] == [8.0, 6.0]
    assert result["order"] == "value_desc"


def test_a_bucketed_ranking_ranks_the_aggregate_not_the_points(monkeypatch) -> None:
    """Ranking daily totals is a different question from ranking single points.

    The largest single workout is on the second day; the largest *day* is the first,
    because two rides sum past it. Aggregation has to happen before the ranking, so
    this one cannot be pushed into the query the way a raw ranking can.
    """
    fake = FakeCoreClient()

    async def _window(tenant_id, *, order="time", max_points=None, **kwargs):
        del kwargs
        fake.last_query = {"order": order, "max_points": max_points}
        return PointBatch(points=_ranking_points(), truncated=False)

    fake.fetch_points_bounded = _window
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        result = _call_series_tool(
            client,
            {
                "metric_type": "workout_distance",
                "bucket": "day",
                "order": "value_desc",
                "max_points": 2,
            },
        )["result"]["structuredContent"]

    assert fake.last_query["order"] == "time", (
        "a bucketed ranking needs the whole window; the values it ranks do not "
        "exist until they are aggregated"
    )
    assert [point["value"] for point in result["points"]] == [11.0, 8.0]
    assert result["points"][0]["timestamp"].startswith("2026-08-01")


def test_an_inverted_value_range_is_refused(monkeypatch) -> None:
    """A range that cannot match anything is a caller error, not an empty result."""
    monkeypatch.setattr(mcp_module, "core_client", FakeCoreClient())

    with TestClient(app, base_url="http://localhost") as client:
        body = _call_series_tool(
            client,
            {
                "metric_type": "steps",
                "min_value": 100,
                "max_value": 10,
            },
        )

    assert body["error"]["data"]["code"] == "INVALID_VALUE_RANGE"


def test_a_value_bound_reaches_the_query(monkeypatch) -> None:
    """The filter is applied where the rows are, so a narrow band is a narrow read."""
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        _call_series_tool(
            client,
            {"metric_type": "steps", "min_value": 50.0, "max_value": 150.0},
        )

    assert fake.last_query["min_value"] == 50.0
    assert fake.last_query["max_value"] == 150.0


def test_an_activity_filter_reaches_the_query(monkeypatch) -> None:
    """"The runs" is a canonical key on the query, not prose matched here."""
    fake = FakeCoreClient()
    monkeypatch.setattr(mcp_module, "core_client", fake)

    with TestClient(app, base_url="http://localhost") as client:
        _call_series_tool(
            client,
            {
                "metric_type": "workout_distance",
                "bucket": "raw",
                "order": "value_desc",
                "activity_type": "running",
                "max_points": 3,
            },
        )

    assert fake.last_query["activity_type"] == "running"
    assert fake.last_query["order"] == "value_desc"


def test_an_unknown_activity_type_is_refused_with_the_known_ones(monkeypatch) -> None:
    """A typo must not silently answer "no such workouts".

    An empty series and an unrecognised filter look identical to a caller, and the
    difference matters: one means "you did not do that", the other "I did not
    understand you". The known keys travel with the refusal so the next attempt can
    be right.
    """
    monkeypatch.setattr(mcp_module, "core_client", FakeCoreClient())

    with TestClient(app, base_url="http://localhost") as client:
        body = _call_series_tool(
            client, {"metric_type": "workout_distance", "activity_type": "jogging"}
        )

    assert body["error"]["data"]["code"] == "UNKNOWN_ACTIVITY_TYPE"
    assert "running" in body["error"]["data"]["known_activity_types"]
