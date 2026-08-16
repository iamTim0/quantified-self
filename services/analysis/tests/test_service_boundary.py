"""The Analysis Service must stay a reader.

AGENTS.md rule 1 gives Core sole ownership of the database and rule 3 makes gRPC
the only transport between Analysis and Core. Those are architectural rules, so a
violation does not announce itself as a failing test somewhere else -- it just
quietly works, and the boundary is gone. These tests are the tripwire.

The service also has to resolve the tenant the same way everything else does:
from the validated token, never from a header a client can set.

Maps to Fizzbee Invariants:
- TenantIsolation
- TenantIdAlwaysPresent
- UnauthenticatedRequestsBlocked
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from analysis import main as analysis_main
from analysis.config import settings
from analysis.core_client import (
    CoreClient,
    MetricSeriesBucket,
    MetricSeriesIssue,
    MetricSeriesResponse,
)
from analysis.main import app, build_daily_series, get_insights, resolve_tenant
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

SRC = Path(__file__).resolve().parents[1] / "src" / "analysis"

# Anything that would mean this service talks to a database directly.
FORBIDDEN_IMPORTS = {
    "sqlalchemy",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "alembic",
    "databases",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_no_module_imports_a_database_driver():
    """Rule 1: only services/core may hold a database connection.

    Checked by reading the AST rather than by grepping strings, so a driver
    imported under an alias is still caught.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        hits = _imported_modules(path) & FORBIDDEN_IMPORTS
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"Analysis must not import a database driver: {offenders}"


def test_no_module_reads_a_database_url():
    """A DATABASE_URL here would mean somebody intends to connect.

    Read from the AST, not the raw text: config.py *documents* that it has no
    DATABASE_URL, and a substring search flagged that comment as a violation.
    Parsing ignores comments, so the check tests the code rather than the prose.
    """
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                name = node.value
            if name and "DATABASE_URL" in name:
                raise AssertionError(f"{path.name} references DATABASE_URL")

    assert not hasattr(settings, "DATABASE_URL")


def _token(**overrides) -> str:
    claims = {
        "user_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "email": "user@example.test",
        "role": "owner",
        "iss": "qs-core",
        "aud": "qs-api",
        "token_type": "access",
        "jti": "44444444-4444-4444-4444-444444444444",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    claims.update(overrides)
    return jwt.encode(claims, settings.JWT_SECRET, algorithm="HS256")


def _request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/analysis/insights",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope, receive=lambda: None)


def test_tenant_comes_from_the_token():
    """Verifies Fizzbee Invariant: TenantIdAlwaysPresent"""
    tenant = resolve_tenant(_request({"Authorization": f"Bearer {_token()}"}))
    assert tenant == "22222222-2222-2222-2222-222222222222"


def test_missing_credential_is_401():
    """Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked"""
    with pytest.raises(HTTPException) as excinfo:
        resolve_tenant(_request({}))
    assert excinfo.value.status_code == 401


def test_a_header_may_agree_with_the_token_but_never_override_it():
    """A supplied tenant that contradicts the token is 403, not a silent switch.

    Verifies Fizzbee Invariant: TenantIsolation
    """
    headers = {
        "Authorization": f"Bearer {_token()}",
        "X-Tenant-ID": "99999999-9999-9999-9999-999999999999",
    }
    with pytest.raises(HTTPException) as excinfo:
        resolve_tenant(_request(headers))
    assert excinfo.value.status_code == 403

    agreeing = {
        "Authorization": f"Bearer {_token()}",
        "X-Tenant-ID": "22222222-2222-2222-2222-222222222222",
    }
    assert resolve_tenant(_request(agreeing)) == "22222222-2222-2222-2222-222222222222"


def test_a_service_token_cannot_stand_in_for_a_user_session():
    """The internal credential has a different audience and must not authenticate here."""
    service = jwt.encode(
        {
            "sub": "qs-internal-service",
            "iss": "qs-core",
            "aud": "qs-internal",
            "token_type": "service",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.internal_secret,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as excinfo:
        resolve_tenant(_request({"Authorization": f"Bearer {service}"}))
    assert excinfo.value.status_code == 401


def test_expired_token_is_rejected():
    expired = _token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
    with pytest.raises(HTTPException) as excinfo:
        resolve_tenant(_request({"Authorization": f"Bearer {expired}"}))
    assert excinfo.value.status_code == 401


def test_build_daily_series_preserves_server_aggregates_and_gaps():
    """Analysis consumes Core's registry-aware buckets without inventing zeros."""
    day = datetime(2026, 3, 1, tzinfo=timezone.utc)
    buckets = [
        MetricSeriesBucket("sleep_score", day, 85.0, 1),
        MetricSeriesBucket("steps", day, 2500.0, 2),
        MetricSeriesBucket("steps", day + timedelta(days=1), None, 0),
    ]
    series = build_daily_series(buckets)
    assert series["sleep_score"]["2026-03-01"] == 85.0
    assert series["steps"]["2026-03-01"] == 2500.0
    assert "2026-03-02" not in series["steps"]


@pytest.mark.asyncio
async def test_core_client_reads_metric_series_and_preserves_null_values(monkeypatch):
    """The Analysis client sends the new request and decodes protobuf presence."""
    from analysis import core_client as core_client_module
    from google.protobuf.timestamp_pb2 import Timestamp
    from quantified_self.v1 import core_service_pb2 as pb

    captured: dict[str, object] = {}

    class _Channel:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class _Stub:
        async def QueryMetricSeries(self, query, metadata):
            captured["query"] = query
            captured["metadata"] = metadata
            value = pb.MetricSeriesBucket(
                metric_type="steps",
                source_id="11111111-1111-1111-1111-111111111111",
                sample_count=2,
                value=350.0,
            )
            gap = pb.MetricSeriesBucket(
                metric_type="steps",
                source_id="11111111-1111-1111-1111-111111111111",
                sample_count=0,
            )
            for bucket in (value, gap):
                timestamp = Timestamp()
                timestamp.FromDatetime(datetime(2026, 3, 1, tzinfo=timezone.utc))
                bucket.bucket_start.CopyFrom(timestamp)
            return pb.QueryMetricSeriesResponse(buckets=[value, gap])

    monkeypatch.setattr(
        core_client_module.grpc.aio,
        "insecure_channel",
        lambda _target: _Channel(),
    )
    monkeypatch.setattr(
        core_client_module.pb_grpc,
        "CoreDataServiceStub",
        lambda _channel: _Stub(),
    )

    client = CoreClient(target="core:50051")
    result = await client.fetch_metric_series(
        "22222222-2222-2222-2222-222222222222",
        start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        end=datetime(2026, 3, 2, tzinfo=timezone.utc),
        request_id="req_series_test",
        metric_types=["steps"],
    )

    query = captured["query"]
    assert isinstance(query, pb.QueryMetricSeriesRequest)
    assert query.tenant_id == "22222222-2222-2222-2222-222222222222"
    assert list(query.metric_types) == ["steps"]
    assert query.resolution == pb.METRIC_SERIES_RESOLUTION_DAY
    assert result.buckets[0].value == 350.0
    assert result.buckets[0].sample_count == 2
    assert result.buckets[0].source_id == "11111111-1111-1111-1111-111111111111"
    assert result.buckets[1].value is None
    assert result.buckets[1].sample_count == 0
    assert result.issues == []


@pytest.mark.asyncio
async def test_insights_use_metric_series_instead_of_raw_points(monkeypatch):
    """Daily insight calculation does not request the unbounded raw-point API."""

    class _FakeCoreClient:
        raw_called = False
        series_called = False

        async def fetch_points(self, **_kwargs):
            self.raw_called = True
            raise AssertionError("daily insights must not fetch raw points")

        async def fetch_metric_series(self, *_args, **_kwargs):
            self.series_called = True
            now = datetime.now(timezone.utc)
            return MetricSeriesResponse(
                buckets=[
                    MetricSeriesBucket(
                        "steps",
                        now - timedelta(days=13 - index),
                        float(index),
                        1,
                        "source-1",
                    )
                    for index in range(14)
                ]
            )

        async def fetch_source_map(self, *_args, **_kwargs):
            return {"source-1": "oura"}

    fake = _FakeCoreClient()
    monkeypatch.setattr(analysis_main, "core_client", fake)
    result = await get_insights(
        request=_request({"X-Request-ID": "req_insights_test"}),
        days=14,
        metric_type="steps",
        min_strength=0.0,
        compare_to_previous=False,
        tenant_id="22222222-2222-2222-2222-222222222222",
    )

    assert fake.series_called is True
    assert fake.raw_called is False
    assert result["metrics_analysed"] == ["steps"]


def _ambiguous_steps_client(primary: str, reason: str = "coverage"):
    """A Core answering with `steps` from two connectors, one of them primary."""

    class _FakeCoreClient:
        async def fetch_metric_series(self, *_args, **_kwargs):
            now = datetime.now(timezone.utc)
            return MetricSeriesResponse(
                buckets=[
                    MetricSeriesBucket("steps", now - timedelta(days=offset), 350.0, 1, "source-a")
                    for offset in range(14)
                ]
                + [
                    MetricSeriesBucket("steps", now - timedelta(days=offset), 1000.0, 1, "source-b")
                    for offset in range(14)
                ],
                issues=[
                    MetricSeriesIssue(
                        code="AMBIGUOUS_METRIC_SOURCE",
                        metric_type="steps",
                        source_ids=["source-a", "source-b"],
                        primary_source_id=primary,
                        primary_reason=reason if primary else "",
                    )
                ],
            )

        async def fetch_source_map(self, *_args, **_kwargs):
            return {"source-a": "oura", "source-b": "apple_health"}

    return _FakeCoreClient()


@pytest.mark.asyncio
async def test_insights_never_merge_two_sources_of_one_metric(monkeypatch):
    """Only the primary connector's series is analysed — the two are never summed.

    Summing them would double count (AGENTS.md rule 19); averaging them would
    reweight the samples invisibly. Exactly one source answers.
    """
    monkeypatch.setattr(analysis_main, "core_client", _ambiguous_steps_client("source-a"))
    result = await get_insights(
        request=_request({"X-Request-ID": "req_ambiguous_primary"}),
        days=14,
        metric_type="steps",
        tenant_id="22222222-2222-2222-2222-222222222222",
    )

    # Analysed rather than dropped, and attributed to the one source that answered.
    assert result["metrics_analysed"] == ["steps"]
    assert result["metrics_excluded_for_quality"] == []
    assert result["metric_source_ids"]["steps"] == ["source-a"]
    # `source-b` reported 1000 on every day. If its buckets had leaked into the
    # series the trend would be built on values this connector never sent.
    assert result["source_issues"][0]["primary_source_id"] == "source-a"
    assert result["source_issues"][0]["primary_reason"] == "coverage"


@pytest.mark.asyncio
async def test_insights_exclude_an_ambiguous_metric_when_core_names_no_primary(monkeypatch):
    """A Core too old to resolve the ambiguity still gets the safe answer.

    Choosing here would be a guess about which of two step counters is real, and
    a guess is worse than an omission the reader can see.
    """
    monkeypatch.setattr(analysis_main, "core_client", _ambiguous_steps_client(""))
    result = await get_insights(
        request=_request({"X-Request-ID": "req_ambiguous_unresolved"}),
        days=14,
        metric_type="steps",
        tenant_id="22222222-2222-2222-2222-222222222222",
    )

    assert result["metrics_analysed"] == []
    assert result["metrics_excluded_for_quality"] == ["steps"]


def test_health_endpoint_needs_no_credential():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["version"]
        assert response.json()["commit"]
        assert response.headers["cache-control"] == "no-store"


def test_insights_without_a_token_is_401():
    """Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked"""
    with TestClient(app) as client:
        assert client.get("/api/v1/analysis/insights").status_code == 401
