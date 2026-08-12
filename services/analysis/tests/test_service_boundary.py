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
from analysis.config import settings
from analysis.core_client import MetricPoint
from analysis.main import app, build_daily_series, resolve_tenant
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


def test_build_daily_series_keeps_the_latest_value_per_day():
    """A re-imported day must not double-count.

    The metrics involved are daily summaries, so two points on one day mean the
    day was imported twice, not that the data is finer-grained.
    """
    day = datetime(2026, 3, 1, tzinfo=timezone.utc)
    points = [
        MetricPoint("sleep_score", day.replace(hour=2), 70.0),
        MetricPoint("sleep_score", day.replace(hour=9), 85.0),
        MetricPoint("steps", day.replace(hour=9), 1000.0),
    ]
    series = build_daily_series(points)
    assert series["sleep_score"]["2026-03-01"] == 85.0
    assert series["steps"]["2026-03-01"] == 1000.0


def test_health_endpoint_needs_no_credential():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_insights_without_a_token_is_401():
    """Verifies Fizzbee Invariant: UnauthenticatedRequestsBlocked"""
    with TestClient(app) as client:
        assert client.get("/api/v1/analysis/insights").status_code == 401
