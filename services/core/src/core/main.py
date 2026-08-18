# ruff: noqa: B008
"""Core Data Service FastAPI Entry Point.

Serves REST endpoints for time-series metric data queries, metric type listing, summary statistics,
and secure encrypted connector configuration management.

Enforces multi-tenant isolation via TenantMiddleware & contextvars.
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Final, Literal
from urllib.parse import parse_qs

import httpx
import nats
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from shared_schemas import FieldReport, health_payload, idempotency_key
from shared_schemas.metrics import (
    CANONICAL_KEYS,
    DYNAMIC_NAMESPACES,
    METRIC_ALIASES,
    METRIC_CATALOG,
    Cadence,
    IngestResolution,
    MetricDefinition,
    UnknownMetricTypeError,
    canonical_metric_type,
    describe,
    metrics_for_source,
)
from sqlalchemy import and_, case, delete, distinct, exists, func, or_, select, text
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.analytics import pearson_pairs
from core.config import settings
from core.connectors import (
    IMPORT_MODE_FILE,
    PUSH_SOURCE_TYPES,
    credential_is_optional,
    is_scheduled,
    supports_file_import,
)
from core.daily_story import build_day_story, day_window
from core.db.models import (
    ApiKey,
    DataPoint,
    DataSource,
    ExplorerView,
    IngestFieldReport,
    LegalDocument,
    MetricIngestPolicy,
    MetricMappingRule,
    MetricRollup,
    MetricSourcePreference,
    OidcAuthRequest,
    OidcProvider,
    QuarantinedDataPoint,
    QuarantineRefusal,
    RefreshToken,
    ReportRun,
    RevokedAccessToken,
    SyncRun,
    Tenant,
    TenantShare,
    User,
    UserIdentity,
)
from core.db.session import async_session_maker, get_session
from core.db.tenant import _current_tenant_id, get_current_tenant_id
from core.deployment_warnings import account_warnings, deployment_warnings
from core.events.consumer import (
    MAX_QUARANTINED_NAMES,
    MAX_QUARANTINED_ROWS,
    IngestionConsumerController,
    IngestionResetError,
    ingestion_retention_warning,
    run_consumer_forever,
)
from core.field_backfill import (
    PendingBackfill,
    run_field_backfill_scheduler,
)
from core.field_backfill import window_reason as backfill_window_reason
from core.grpc.server import serve_grpc
from core.ingest_planning import (
    BucketCount,
    TimeRange,
    analyse_coverage,
    analyse_metric_coverage,
    compute_sync_window,
    plan_import,
)
from core.jobs import MAX_JOBS, list_jobs
from core.metric_mapping import (
    MappingAction,
    ValidatedMapping,
    custom_definitions_from_rules,
    replay_value,
    validate_mapping,
)
from core.oauth_refresh import (
    RefreshError,
    apply_refresh,
    can_refresh,
    needs_refresh,
    refresh_credential,
)
from core.reports import (
    CORE_COMPUTED_KINDS,
    REASON_COVERAGE,
    REASON_PREFERENCE,
    REPORT_KINDS,
    acquire_report_lock,
    compute_conflicts_report,
    compute_core_report,
    compute_gaps_report,
    enqueue_report_run,
    fail_report_run,
    finish_report_run,
    has_in_flight_report,
    latest_failed_report,
    latest_successful_report,
    metric_source_coverage,
    open_report_run,
    primary_source_preferences,
    report_is_stale,
    report_payload,
    resolve_primary_source,
    resolved_report_params,
    run_report_scheduler,
    tenant_data_high_water,
)
from core.rollup_coverage import (
    may_hold_points_outside_day_rollups,
    remember_day_rollup_coverage,
)
from core.rollups import update_rollups_for_point
from core.scheduler import (
    DueConnector,
    acquire_connector_lock,
    has_in_flight_run,
    overdue_connector_warning,
    run_scheduler,
    run_stale_run_sweep,
)
from core.security import login_throttle
from core.security.auth import (
    AuthenticationMiddleware,
    Principal,
    get_current_principal,
    require_platform_admin,
    require_role,
)
from core.security.cookies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    REFRESH_COOKIE,
    clear_session_cookies,
    csrf_token_matches,
    set_session_cookies,
)
from core.security.crypto import (
    DecryptionError,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)
from core.security.oidc import (
    AUTH_REQUEST_TTL_SECONDS,
    OidcError,
    apply_claims_mapping,
    build_authorization_request,
    end_session_url,
    exchange_code,
    fetch_discovery,
    is_redirect_uri_allowed,
    verify_id_token,
    verify_logout_token,
)
from core.security.secret_audit import audit_secrets
from core.security.tokens import (
    TokenError,
    create_access_token,
    create_api_key,
    create_refresh_token,
    decode_access_token,
    hash_token,
)
from core.sessions import decode_session_key
from core.tracing import (
    RequestTracingMiddleware,
    get_current_request_id,
    setup_tracing_logger,
)
from core.workouts import (
    DEFAULT_DAY_TRACK_POINTS,
    DEFAULT_PAD_SECONDS,
    DEFAULT_ROUTE_POINTS,
    DEFAULT_STREAM_POINTS,
    MAX_DAY_TRACK_POINTS,
    MAX_LIST_DAYS,
    MAX_LIST_SESSIONS,
    MAX_PAD_SECONDS,
    MAX_ROUTE_POINTS,
    MAX_STREAM_POINTS,
    SessionNotFound,
    build_workout_detail,
    build_workout_list,
    track_for_window,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MAX_QUARANTINE_LIST_ROWS = 5000
QUARANTINE_REPLAY_BATCH_SIZE = 500


def _quarantine_capacity_warning(
    *,
    active_rows: int,
    active_names: int,
    refused_occurrences: int,
) -> tuple[str, str]:
    """Return a stable warning code and the capacity dimension closest to full."""
    row_ratio = active_rows / MAX_QUARANTINED_ROWS
    name_ratio = active_names / MAX_QUARANTINED_NAMES
    limiting_dimension = "rows" if row_ratio >= name_ratio else "names"
    usage_ratio = max(row_ratio, name_ratio)

    # A refusal is more urgent than the current queue size: values have already
    # failed to enter quarantine and cannot be recovered by a later mapping rule.
    if refused_occurrences > 0:
        return "quarantine_values_refused", limiting_dimension
    if usage_ratio >= 1:
        return "quarantine_full", limiting_dimension
    if usage_ratio >= 0.75:
        return "quarantine_near_full", limiting_dimension
    if usage_ratio >= 0.5:
        return "quarantine_half_full", limiting_dimension
    return "quarantine_has_pending", limiting_dimension

# SECURITY H3: Constrain source_type to known connectors
ValidSourceType = Literal[
    "oura", "whoop", "apple_health", "fitbit", "garmin", "strava", "yazio",
    "dawarich", "streak", "home_assistant", "weather", "calendar", "github",
]
ValidStatus = Literal["active", "inactive"]

# The connector taxonomy lives in `core.connectors`, so the scheduler can share it
# without importing this module (see the import block above).


class ManualDataPointRequest(BaseModel):
    """Validated manual or visually mapped import row."""

    source_id: str
    metric_type: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime
    value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metric_type")
    @classmethod
    def canonicalise_metric_type(cls, v: str) -> str:
        """Map the row onto a registered metric, or reject it.

        Unlike the NATS path this one *does* rewrite aliases, because the idempotency
        key for a manual row is derived downstream from the validated value rather than
        by the caller. A CSV whose column header is `carbs` therefore lands in
        `nutrition_carbohydrates` instead of founding a metric of its own — which is the
        whole point of mapping a spreadsheet into the platform. A name that matches
        nothing is a 422 naming the `custom_` namespace, rather than silent acceptance.
        """
        try:
            return canonical_metric_type(v)
        except UnknownMetricTypeError as exc:
            raise ValueError(str(exc)) from None


class BatchImportRequest(BaseModel):
    """A bounded batch produced by the dashboard CSV/DB visual mapper."""

    rows: list[ManualDataPointRequest] = Field(..., min_length=1, max_length=5000)



class UserSignupRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="User password")
    name: str = Field(..., description="Tenant / user display name")


class UserLoginRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="User password")


_PROFILE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UpdateProfileRequest(BaseModel):
    """Self-service account fields and the workspace label."""

    name: str | None = Field(None, min_length=1, max_length=128)
    email: str | None = Field(None, min_length=3, max_length=320)
    workspace_name: str | None = Field(None, min_length=1, max_length=128)

    @field_validator("name", "workspace_name", mode="before")
    @classmethod
    def trim_display_names(cls, value: Any) -> Any:
        """Reject whitespace-only labels while preserving omitted fields."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("must be a string")
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("must not be blank")
        return trimmed

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: Any) -> Any:
        """Store sign-in addresses canonically and catch obvious typos."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise TypeError("must be a string")
        normalized = value.strip().casefold()
        if not _PROFILE_EMAIL.fullmatch(normalized):
            raise ValueError("must be a valid email address")
        return normalized

    @model_validator(mode="after")
    def require_one_change(self) -> "UpdateProfileRequest":
        """Do not accept an empty profile update."""
        if self.name is None and self.email is None and self.workspace_name is None:
            raise ValueError("at least one profile field is required")
        return self


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "testing", False):
        yield
        return

    # Before anything else, and deliberately not caught: a Core signing real
    # sessions with a secret published in this repository should fail to start,
    # not start and log about it.
    audit_secrets(
        environment=settings.ENVIRONMENT,
        jwt_secret=settings.JWT_SECRET,
        encryption_key=settings.ENCRYPTION_KEY,
        internal_secret=settings.INTERNAL_SERVICE_SECRET,
        service="core",
    )

    role = settings.CORE_ROLE.lower()
    if role not in {"all", "api", "ingest", "scheduler"}:
        raise RuntimeError(f"Unsupported CORE_ROLE: {settings.CORE_ROLE}")

    # The gRPC server is how the Analysis Service reads data (AGENTS.md rule 3).
    # It starts before the NATS consumer and outside that try block on purpose:
    # the consumer's failure path deliberately still yields so Core serves HTTP
    # without a broker, and folding gRPC into it would have let the read API for
    # another service disappear silently.
    grpc_server = None
    if role in {"all", "api"}:
        try:
            grpc_server = await serve_grpc()
            app.state.grpc_server = grpc_server
        except Exception:
            logger.exception("gRPC server failed to start; Analysis Service reads will fail")

    scheduler_task = None
    report_task = None
    backfill_task = None
    stale_sweep_task = None
    if settings.SCHEDULER_ENABLED and role in {"all", "scheduler"}:
        scheduler_task = asyncio.create_task(run_scheduler(_enqueue_scheduled_sync))
        # Same role as the sync scheduler and for the same reason: it is the one
        # process that acts across tenants on a timer. Separate task, because a
        # report that fails must not delay the next import.
        report_task = asyncio.create_task(run_report_scheduler())
        # And a third, on a much slower tick: recovering the history of a field that
        # has only just become supported is not urgent, and it must not sit in front
        # of the scheduled imports on the same timer.
        backfill_task = asyncio.create_task(
            run_field_backfill_scheduler(_enqueue_field_backfill)
        )
        # A fourth, and the one that must not share a fate with the others: retiring
        # a dead run is how a wedged connector recovers, so it runs on its own timer
        # under its own lock. It used to happen only inside the sync tick, and when
        # that tick hung on its advisory lock the repair hung with it.
        stale_sweep_task = asyncio.create_task(run_stale_run_sweep())

    # The NATS subscription is established in the background, never awaited here.
    #
    # It used to be awaited, and `nats.connect` retries sixty times two seconds
    # apart before giving up -- so an unreachable broker held Core's startup for
    # two minutes and nothing answered /health in the meantime. The surrounding
    # `except Exception: yield` was written to prevent exactly that and could not,
    # because the call blocks rather than raising.
    #
    # A broker outage should degrade ingestion. It should not take down queries,
    # authentication or the dashboard.
    app.state.nats_client = None
    app.state.nats_status = "disconnected"
    ingestion_controller = IngestionConsumerController()
    app.state.ingestion_controller = ingestion_controller

    def _remember(nc):
        app.state.nats_client = nc
        app.state.nats_status = "connected"

    def _consumer_ready(nc, connection_lost):
        ingestion_controller.connected(nc, connection_lost)

    def _consumer_lost(nc):
        ingestion_controller.disconnected(nc)
        if getattr(app.state, "nats_client", None) is nc:
            app.state.nats_client = None
            app.state.nats_status = "disconnected"

    consumer_task = None
    publisher_task = None
    if role in {"all", "ingest"}:
        consumer_task = asyncio.create_task(
            run_consumer_forever(
                _remember,
                on_connection_ready=_consumer_ready,
                on_connection_lost=_consumer_lost,
            )
        )
    if role in {"api", "scheduler"}:
        # API-triggered imports and scheduled imports both publish task messages,
        # but neither role should consume the ingest stream. Keeping this small
        # publisher connection in the API role preserves manual syncs when the
        # production deployment separates the consumer into core-ingest.
        publisher_task = asyncio.create_task(_run_nats_publisher_forever(app))

    try:
        yield
    finally:
        if consumer_task is not None:
            consumer_task.cancel()
            with suppress(asyncio.CancelledError):
                await consumer_task
        if publisher_task is not None:
            publisher_task.cancel()
            with suppress(asyncio.CancelledError):
                await publisher_task
        if (nc := getattr(app.state, "nats_client", None)) is not None:
            with suppress(Exception):
                await nc.close()
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
        if report_task is not None:
            report_task.cancel()
            with suppress(asyncio.CancelledError):
                await report_task
        if backfill_task is not None:
            backfill_task.cancel()
            with suppress(asyncio.CancelledError):
                await backfill_task
        if stale_sweep_task is not None:
            stale_sweep_task.cancel()
            with suppress(asyncio.CancelledError):
                await stale_sweep_task
        if grpc_server is not None:
            await grpc_server.stop(grace=2.0)


async def _run_nats_publisher_forever(app: FastAPI) -> None:
    """Keep a NATS connection for task publishing without consuming ingest events."""
    delay = 1.0
    while True:
        try:
            nc = await nats.connect(
                settings.NATS_URL,
                connect_timeout=5,
                max_reconnect_attempts=0,
                allow_reconnect=False,
            )
            app.state.nats_client = nc
            app.state.nats_status = "connected"
            delay = 1.0
            # nats-py exposes the terminal state as the public `is_closed`
            # property; there is no public `closed` event. Polling keeps this
            # publisher alive without depending on a private client member.
            while not nc.is_closed:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - retry after a broker outage
            logger.warning(
                "NATS publisher unavailable (%s); task publishing is paused for %.0fs",
                type(exc).__name__,
                delay,
            )
        finally:
            app.state.nats_status = "disconnected"
            if (current := getattr(app.state, "nats_client", None)) is not None:
                with suppress(Exception):
                    await current.close()
                app.state.nats_client = None
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)


async def _enqueue_scheduled_sync(connector: DueConnector) -> None:
    """Enqueue one due connector, on its own session and tenant scope.

    A separate session per connector so one failure cannot roll back another's
    SyncRun row, and the tenant context is bound explicitly because there is no
    request to derive it from -- the scheduler acts for every tenant in turn.
    """
    token = _current_tenant_id.set(connector.tenant_id)
    try:
        async with async_session_maker() as session:
            source = (
                await session.execute(
                    select(DataSource).where(
                        DataSource.id == connector.source_id,
                        DataSource.tenant_id == connector.tenant_id,
                        DataSource.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if source is None:
                return
            await plan_and_enqueue_sync(
                session,
                connector.tenant_id,
                source,
                mode="smart",
                trigger="scheduled",
            )
    finally:
        _current_tenant_id.reset(token)


async def _enqueue_field_backfill(pending: PendingBackfill) -> bool:
    """Re-import the span a connector's newly supported fields arrived unstored in.

    `mode="force"`, because the whole point is to fetch a period the coverage
    planner considers complete — it is complete, for every metric except the ones
    that were not being stored yet, and coverage cannot tell the difference.

    Returns whether the run was actually queued. A connector with an import in
    flight comes back `skipped`, and reporting that honestly is what leaves the
    fields pending for the next sweep instead of marking history recovered that
    nothing fetched.
    """
    reason = backfill_window_reason(pending)
    token = _current_tenant_id.set(pending.tenant_id)
    try:
        async with async_session_maker() as session:
            source = (
                await session.execute(
                    select(DataSource).where(
                        DataSource.id == pending.source_id,
                        DataSource.tenant_id == pending.tenant_id,
                        DataSource.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if source is None:
                return False
            result = await plan_and_enqueue_sync(
                session,
                pending.tenant_id,
                source,
                start=pending.window_start,
                end=pending.window_end,
                mode="force",
                trigger="field_backfill",
                window_reason=reason,
            )
            return result.get("status") == "sync_queued"
    finally:
        _current_tenant_id.reset(token)



setup_tracing_logger("qs-core")
logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_HOURS = 7 * 24


def _configured_lookback_hours(config: dict[str, Any] | None) -> float:
    """Read the sub-day lookback while preserving legacy day-only configs."""
    config = config or {}
    raw_hours = config.get("lookback_hours")
    if raw_hours is not None:
        try:
            return max(1.0, min(365 * 24, float(raw_hours)))
        except (TypeError, ValueError):
            pass
    try:
        raw_days = float(config.get("lookback_days", DEFAULT_LOOKBACK_HOURS / 24))
    except (TypeError, ValueError):
        raw_days = DEFAULT_LOOKBACK_HOURS / 24
    return max(24.0, min(365 * 24, raw_days * 24))

app = FastAPI(
    title=settings.SERVICE_NAME,
    lifespan=lifespan,
)

app.add_middleware(RequestTracingMiddleware)
# SECURITY C4: Core should only be accessed by Gateway, not browsers directly.
# Restrict CORS to reject browser-originated cross-origin requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # No browser origins allowed — Gateway proxies server-side
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "X-Tenant-ID", "X-Request-ID", "Content-Type"],
)
app.add_middleware(AuthenticationMiddleware)


@app.get("/health")
async def health_check(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return health_payload(settings.SERVICE_NAME, role=settings.CORE_ROLE.lower())


@app.get("/readyz")
async def readiness_check(response: Response):
    """Report whether Core dependencies can serve traffic safely.

    ``/health`` is deliberately a cheap process liveness probe. This endpoint is
    the dependency-aware probe for operators and deployment controllers: a live
    Core with a disconnected broker must not be mistaken for an ingest-ready Core.
    It never checks tenant state or provider credentials.
    """
    role = settings.CORE_ROLE.lower()
    components: dict[str, str] = {"database": "ok"}
    if role in {"all", "api", "ingest", "scheduler"}:
        components["nats"] = "unknown"
    if role in {"all", "ingest"}:
        components["ingestion_consumer"] = "unknown"
    if role in {"all", "api"}:
        components["grpc"] = "unknown"
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Core readiness database check failed")
        components["database"] = "error"

    if "nats" in components:
        nc = getattr(app.state, "nats_client", None)
        if nc is not None and getattr(nc, "is_connected", False):
            components["nats"] = "ok"
        else:
            components["nats"] = "disconnected"

    if "ingestion_consumer" in components:
        controller = getattr(app.state, "ingestion_controller", None)
        components["ingestion_consumer"] = (
            "ok" if controller is not None and controller.status == "connected" else "disconnected"
        )

    if "grpc" in components:
        grpc_server = getattr(app.state, "grpc_server", None)
        components["grpc"] = "ok" if grpc_server is not None else "unavailable"
    ready = all(value == "ok" for value in components.values())
    payload = health_payload(
        settings.SERVICE_NAME,
        status="ok" if ready else "degraded",
        components=components,
    )
    if not ready:
        return JSONResponse(
            status_code=503,
            content=payload,
            headers={"Cache-Control": "no-store"},
        )
    response.headers["Cache-Control"] = "no-store"
    return payload


# ─── Auth Endpoints ──────────────────────────────────────────


async def _issue_session(
    session: AsyncSession,
    response: Response,
    *,
    user_id: str,
    tenant_id: str,
    email: str,
    role: str,
) -> dict[str, Any]:
    """Mint an access/refresh pair, persist the refresh hash, set the cookies.

    Only the refresh token's hash is stored, so a database disclosure cannot be
    replayed against the API.

    The tokens themselves are deliberately absent from the returned body. They
    used to be in it, and the dashboard put them in ``localStorage`` where any
    script on the page could read them. Handing them back at all would keep that
    door open no matter what the client then chose to do, so the credential now
    leaves this function only as an httpOnly cookie. The body carries the session
    *metadata* a UI legitimately needs to render itself.
    """
    access_token, _jti, access_expires = create_access_token(
        user_id=user_id, tenant_id=tenant_id, email=email, role=role
    )
    raw_refresh, refresh_hash, refresh_expires = create_refresh_token()

    session.add(
        RefreshToken(
            tenant_id=tenant_id,
            user_id=user_id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
        )
    )
    await session.commit()

    set_session_cookies(
        response,
        access_token=access_token,
        access_expires=access_expires,
        refresh_token=raw_refresh,
        refresh_expires=refresh_expires,
    )

    return {
        "token_type": "cookie",
        "expires_at": access_expires.isoformat(),
        "expires_in": int((access_expires - datetime.now(timezone.utc)).total_seconds()),
    }


async def _revoke_all_sessions(
    session: AsyncSession, *, tenant_id: str, user_id: str, reason: str
) -> None:
    """Invalidate every session for a user (password change, compromise, federated logout).

    Both halves are needed and the second was missing. Revoking the refresh
    tokens stops new access tokens being minted, but says nothing about the ones
    already in circulation: they carry their own signature and expiry and were
    accepted for the rest of their twelve hours. "Revoke all sessions" therefore
    did not end any session already in use — only the ability to renew it.

    The denylist cannot close that gap, because it keys on ``jti`` and a ``jti``
    is only ever learned by being presented. ``users.sessions_valid_from`` covers
    every outstanding token at once, and :func:`core.security.auth._revocation_reason`
    compares it against each token's ``iat``.
    """
    now = datetime.now(timezone.utc)
    await session.execute(
        sa_update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.tenant_id == tenant_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.execute(
        sa_update(User)
        .where(User.id == user_id, User.tenant_id == tenant_id)
        .values(sessions_valid_from=now)
    )
    logger.info(
        "Revoked all sessions for user=%s tenant=%s reason=%s",
        user_id,
        tenant_id,
        reason,
    )


@app.post("/api/v1/auth/signup")
async def signup(
    req: UserSignupRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    if not settings.ALLOW_REGISTRATION:
        raise HTTPException(
            status_code=403,
            detail="Registration is currently disabled by system administrator."
        )
    stmt = select(User).where(User.email == req.email)
    res = await session.execute(stmt)
    if res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    hashed_pwd = pwd_context.hash(req.password)

    tenant = Tenant(id=tenant_id, name=f"{req.name}'s Workspace")
    user = User(
        id=user_id,
        tenant_id=tenant_id,
        email=req.email,
        password_hash=hashed_pwd,
        name=req.name,
        role="owner",
    )
    session.add(tenant)
    session.add(user)
    await session.commit()

    tokens = await _issue_session(
        session,
        response,
        user_id=user_id,
        tenant_id=tenant_id,
        email=req.email,
        role="owner",
    )

    return {
        "status": "success",
        **tokens,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": req.email,
        "name": req.name,
        "role": "owner",
        "workspace_name": tenant.name,
    }


#: Verified against when no account matches, so that both branches of a failed
#: sign-in cost the same bcrypt work.
#:
#: The endpoint used to answer in microseconds for an address it had never seen
#: and in a few hundred milliseconds for one it had, because `not user or not
#: verify(...)` short-circuits and never reached bcrypt in the first case. That
#: difference is measurable over the network, which made the endpoint an
#: account-enumeration oracle: an attacker learned which addresses were real
#: before spending a single guess on them.
#:
#: Hashed once at import, from a value no account can hold — `bcrypt` truncates
#: at 72 bytes and never sees this string as a candidate password anyway.
_DUMMY_PASSWORD_HASH = pwd_context.hash("password-that-belongs-to-no-account")


@app.post("/api/v1/auth/login")
async def login(
    req: UserLoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    # Before the password is checked, so a throttled caller cannot spend our
    # bcrypt either. Keyed on the address as *submitted*, so a refusal says
    # nothing about whether that account exists.
    decision = await login_throttle.check(session, email=req.email)
    if not decision.allowed:
        await session.commit()
        logger.warning(
            "[req_id=%s] Refused a sign-in attempt: too many recent failures.",
            get_current_request_id(),
        )
        raise HTTPException(
            status_code=429,
            detail={
                "code": login_throttle.THROTTLED_CODE,
                "message": "Too many sign-in attempts. Try again shortly.",
            },
            headers={"Retry-After": str(decision.retry_after_seconds)},
        )

    stmt = select(User).where(User.email == req.email)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    # Always verify something. Against the real hash when the account exists,
    # against a fixed one when it does not — the point is that both paths pay
    # bcrypt, so the response time no longer answers "does this address exist".
    password_ok = pwd_context.verify(
        req.password, user.password_hash if user else _DUMMY_PASSWORD_HASH
    )

    if not user or not password_ok:
        await login_throttle.record_failure(session, email=req.email)
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await login_throttle.clear_account(session, email=req.email)

    tenant_name = (
        await session.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))
    ).scalar_one()

    tokens = await _issue_session(
        session,
        response,
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role,
    )

    return {
        "status": "success",
        **tokens,
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "workspace_name": tenant_name,
    }


class RefreshRequest(BaseModel):
    # Optional: browsers present the refresh token in the qs_refresh cookie and
    # send no body at all. This field is the non-browser path.
    refresh_token: str | None = Field(None, min_length=16, max_length=512)


@app.post("/api/v1/auth/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    req: RefreshRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Exchange a refresh token for a fresh access/refresh pair.

    Rotation is single-use. Presenting a token that has already been rotated is
    treated as replay: the entire chain for that user is revoked rather than
    silently issuing another session.

    This endpoint is exempt from the authentication middleware -- the access
    token is expected to be expired by the time anyone calls it -- so it performs
    its own CSRF check for the cookie path rather than inheriting one.
    """
    cookie_refresh = request.cookies.get(REFRESH_COOKIE)
    presented = cookie_refresh or (req.refresh_token if req else None)

    if not presented:
        raise HTTPException(status_code=401, detail="No refresh token presented")

    if cookie_refresh and not csrf_token_matches(
        request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)
    ):
        raise HTTPException(status_code=403, detail="Missing or invalid CSRF token")

    presented_hash = hash_token(presented)
    res = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == presented_hash)
    )
    stored = res.scalars().first()

    if not stored:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    now = datetime.now(timezone.utc)

    if stored.rotated_to_id is not None or stored.revoked_at is not None:
        # Replay of a superseded or revoked token — assume compromise.
        await _revoke_all_sessions(
            session,
            tenant_id=stored.tenant_id,
            user_id=stored.user_id,
            reason="refresh_token_replay",
        )
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=401, detail="Refresh token has expired")

    user_res = await session.execute(
        select(User).where(User.id == stored.user_id, User.tenant_id == stored.tenant_id)
    )
    user = user_res.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    tenant_name = (
        await session.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))
    ).scalar_one()

    raw_refresh, refresh_hash, refresh_expires = create_refresh_token()
    replacement = RefreshToken(
        tenant_id=user.tenant_id,
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_expires,
    )
    session.add(replacement)
    await session.flush()

    stored.rotated_to_id = replacement.id
    stored.revoked_at = now

    access_token, _jti, access_expires = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role,
    )
    await session.commit()

    # Rotating the cookies also rotates the CSRF token, so a token captured from
    # an earlier session cannot be paired with the new credential.
    set_session_cookies(
        response,
        access_token=access_token,
        access_expires=access_expires,
        refresh_token=raw_refresh,
        refresh_expires=refresh_expires,
    )

    return {
        "status": "success",
        "token_type": "cookie",
        "expires_at": access_expires.isoformat(),
        "expires_in": int((access_expires - now).total_seconds()),
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "workspace_name": tenant_name,
    }


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(
        None, description="Refresh token to revoke alongside the access token"
    )
    all_sessions: bool = Field(
        False, description="Revoke every refresh token for this user, not just this one"
    )


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(
    request: Request,
    req: LogoutRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Invalidate the presented session server-side.

    Deliberately idempotent and always ``204``: a client that has already lost or
    expired its token must still be able to complete a logout, and the response
    must not reveal whether the presented credential was real.
    """
    auth_header = request.headers.get("Authorization") or ""
    now = datetime.now(timezone.utc)

    tenant_id: str | None = None
    user_id: str | None = None

    presented_access = (
        auth_header[7:].strip()
        if auth_header.startswith("Bearer ")
        else request.cookies.get(ACCESS_COOKIE)
    )

    if presented_access:
        try:
            claims = decode_access_token(presented_access)
        except TokenError:
            claims = None
        if claims:
            tenant_id = claims["tenant_id"]
            user_id = claims["user_id"]
            expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
            await session.execute(
                pg_insert(RevokedAccessToken)
                .values(
                    jti=claims["jti"],
                    tenant_id=tenant_id,
                    user_id=user_id,
                    expires_at=expires_at,
                    reason="logout",
                    revoked_at=now,
                )
                .on_conflict_do_nothing(index_elements=["jti"])
            )

    body = req or LogoutRequest()

    # The cookie is the browser's refresh token; the body field is the
    # non-browser path. Revoke whichever was presented.
    presented_refresh = request.cookies.get(REFRESH_COOKIE) or body.refresh_token

    if presented_refresh:
        await session.execute(
            sa_update(RefreshToken)
            .where(
                RefreshToken.token_hash == hash_token(presented_refresh),
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    if body.all_sessions and tenant_id and user_id:
        await _revoke_all_sessions(
            session, tenant_id=tenant_id, user_id=user_id, reason="logout_all"
        )

    # Opportunistic housekeeping: a denylist entry is pointless once the token it
    # names would fail signature validation anyway.
    await session.execute(
        delete(RevokedAccessToken).where(RevokedAccessToken.expires_at < now)
    )
    await session.commit()

    # If the user signed in through an identity provider, offer the provider's
    # RP-initiated logout URL so the caller can finish the job there. Ending only
    # the local session leaves the provider's alive, so the next "sign in with…"
    # completes instantly with no prompt and logging out looks like it did
    # nothing.
    #
    # Returned rather than acted on: this is a 204 API call, and only the browser
    # can perform a top-level navigation to another origin.
    end_session: str | None = None
    if user_id and tenant_id:
        end_session = await _provider_end_session_url(session, user_id, tenant_id)

    # Clear the cookies unconditionally. Logout must leave the browser signed out
    # even when the presented credential was already expired or unparseable --
    # otherwise a stale cookie survives and the next page load looks signed in,
    # which is precisely the bug this endpoint exists to prevent.
    if end_session:
        out = JSONResponse(status_code=200, content={"end_session_url": end_session})
    else:
        out = Response(status_code=204)
    clear_session_cookies(out)
    return out


async def _provider_end_session_url(
    session: AsyncSession, user_id: str, tenant_id: str
) -> str | None:
    """The provider logout URL for this user's linked identity, if there is one.

    Best-effort throughout: a provider that is unreachable, has been deleted, or
    offers no `end_session_endpoint` must not stop the local logout from
    completing. Failing here would mean a provider outage prevents users from
    signing out.
    """
    try:
        identity = (
            await session.execute(
                select(UserIdentity)
                .where(
                    UserIdentity.user_id == user_id,
                    UserIdentity.tenant_id == tenant_id,
                )
                .order_by(UserIdentity.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        if identity is None:
            return None

        provider = (
            await session.execute(
                select(OidcProvider).where(
                    OidcProvider.slug == identity.provider_slug,
                    OidcProvider.enabled.is_(True),
                )
            )
        ).scalars().first()
        if provider is None:
            return None

        discovery = await fetch_discovery(provider.issuer)
        return end_session_url(
            discovery,
            post_logout_redirect_uri=settings.POST_LOGOUT_REDIRECT_URI,
            client_id=provider.client_id,
        )
    except Exception:
        logger.warning(
            "[req_id=%s] Could not resolve an RP-initiated logout URL",
            get_current_request_id(),
            exc_info=True,
        )
        return None


@app.get("/api/v1/auth/me")
async def get_current_user(session: AsyncSession = Depends(get_session)):
    """Return the authenticated identity. Used by the dashboard to validate a session."""
    principal = get_current_principal()
    res = await session.execute(
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            User.id == principal.user_id,
            User.tenant_id == principal.tenant_id,
            Tenant.id == principal.tenant_id,
        )
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    user, tenant = row

    return {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "workspace_name": tenant.name,
    }


@app.put("/api/v1/auth/me")
async def update_current_user_profile(
    req: UpdateProfileRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Update the caller's identity and, for admins, the workspace label.

    Email changes revoke every existing session and immediately issue one fresh
    session for the caller. This keeps the current browser usable while closing
    any session that may still know the old sign-in address.
    """
    principal = get_current_principal()
    res = await session.execute(
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(
            User.id == principal.user_id,
            User.tenant_id == principal.tenant_id,
            Tenant.id == principal.tenant_id,
        )
    )
    row = res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Account no longer exists")
    user, tenant = row

    if req.workspace_name is not None and user.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail="Only owners and administrators can rename the workspace.",
        )

    email_changed = req.email is not None and req.email != user.email
    if email_changed:
        existing = await session.execute(
            select(User.id).where(
                User.tenant_id == principal.tenant_id,
                User.id != user.id,
                func.lower(User.email) == req.email,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="An account with this email address already exists.",
            )
        user.email = req.email
    if req.name is not None:
        user.name = req.name
    if req.workspace_name is not None:
        tenant.name = req.workspace_name

    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with this email address already exists.",
        ) from exc

    if email_changed:
        await _revoke_all_sessions(
            session,
            tenant_id=principal.tenant_id,
            user_id=user.id,
            reason="email_change",
        )
    await session.commit()

    session_tokens: dict[str, Any] = {}
    if email_changed:
        session_tokens = await _issue_session(
            session,
            response,
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
        )

    return {
        **session_tokens,
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "workspace_name": tenant.name,
        "session_refreshed": email_changed,
    }


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, description="Current user password")
    new_password: str = Field(..., min_length=6, max_length=128, description="New password")


@app.post("/api/v1/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Safely update account password for the authenticated user.

    Resolves the account by ``user_id`` from the verified token. The previous
    implementation selected the first user in the tenant, which changed the wrong
    person's password in any workspace with more than one member.
    """
    principal = get_current_principal()

    stmt = select(User).where(
        User.id == principal.user_id, User.tenant_id == principal.tenant_id
    )
    res = await session.execute(stmt)
    user = res.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User account not found.")

    if not pwd_context.verify(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="The current password is incorrect.")

    user.password_hash = pwd_context.hash(req.new_password)

    # A password change must not leave older sessions alive.
    await _revoke_all_sessions(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        reason="password_change",
    )
    if principal.jti:
        await session.execute(
            pg_insert(RevokedAccessToken)
            .values(
                jti=principal.jti,
                tenant_id=user.tenant_id,
                user_id=user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(
                    minutes=settings.ACCESS_TOKEN_TTL_MINUTES
                ),
                reason="password_change",
            )
            .on_conflict_do_nothing(index_elements=["jti"])
        )
    await session.commit()

    # The caller's own session was just revoked along with the rest, so leave the
    # browser genuinely signed out. Without this the cookies survive a change that
    # invalidated them, and the UI keeps rendering as signed-in until some later
    # request happens to 401.
    clear_session_cookies(response)

    return {
        "status": "success",
        "message": "Password changed. Please sign in again.",
        "sessions_revoked": True,
    }


# ─── OIDC / External Identity Providers ─────────────────────


def _serialize_provider(provider: OidcProvider, *, admin: bool = False) -> dict[str, Any]:
    """Public shape. The client secret is never included, masked or otherwise."""
    public = {
        "slug": provider.slug,
        "display_name": provider.display_name,
        "enabled": provider.enabled,
    }
    if not admin:
        return public
    return {
        **public,
        "id": provider.id,
        "issuer": provider.issuer,
        "client_id": provider.client_id,
        "has_client_secret": bool(provider.encrypted_client_secret),
        "scopes": provider.scopes,
        "redirect_uri": provider.redirect_uri,
        "claims_mapping": provider.claims_mapping,
        "allow_signup": provider.allow_signup,
        "require_verified_email": provider.require_verified_email,
        "created_at": provider.created_at.isoformat() if provider.created_at else None,
    }


async def _load_enabled_provider(session: AsyncSession, slug: str) -> OidcProvider:
    res = await session.execute(
        select(OidcProvider).where(OidcProvider.slug == slug, OidcProvider.enabled.is_(True))
    )
    provider = res.scalars().first()
    if not provider:
        # Same answer for "unknown" and "disabled": no enumeration.
        raise HTTPException(status_code=404, detail="Unknown or disabled login provider")
    return provider


@app.get("/api/v1/auth/oidc/providers")
async def list_oidc_providers(session: AsyncSession = Depends(get_session)):
    """Enabled providers, for rendering login buttons. Unauthenticated by design."""
    res = await session.execute(
        select(OidcProvider).where(OidcProvider.enabled.is_(True)).order_by(OidcProvider.display_name)
    )
    return {"providers": [_serialize_provider(p) for p in res.scalars().all()]}


# ─── OIDC provider administration ───────────────────────────
#
# Providers were configurable only by inserting a database row by hand, which
# meant nobody without psql access could add one and there was no audit of who
# changed what. These endpoints are owner-only and live under /api/v1/data/ so
# the Gateway proxies them like any other authenticated route.


class OidcProviderRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")
    display_name: str = Field(..., min_length=1, max_length=128)
    issuer: str = Field(..., min_length=8, max_length=512)
    client_id: str = Field(..., min_length=1, max_length=512)
    client_secret: str | None = Field(
        None, max_length=2048, description="Stored encrypted; omit when editing to keep"
    )
    scopes: str = Field("openid email profile", max_length=512)
    redirect_uri: str = Field(..., min_length=8, max_length=512)
    claims_mapping: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False
    allow_signup: bool = False
    require_verified_email: bool = True


def _admin_provider_view(provider: OidcProvider) -> dict[str, Any]:
    """Full configuration minus the secret, which is never returned."""
    return {
        "id": provider.id,
        "slug": provider.slug,
        "display_name": provider.display_name,
        "issuer": provider.issuer,
        "client_id": provider.client_id,
        "has_client_secret": bool(provider.encrypted_client_secret),
        "scopes": provider.scopes,
        "redirect_uri": provider.redirect_uri,
        "claims_mapping": provider.claims_mapping or {},
        "enabled": provider.enabled,
        "allow_signup": provider.allow_signup,
        "require_verified_email": provider.require_verified_email,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


@app.get("/api/v1/data/oidc/providers")
async def admin_list_oidc_providers(
    session: AsyncSession = Depends(get_session),
    _principal: Principal = Depends(require_platform_admin("owner", "admin")),
):
    """Every provider, enabled or not, with the secret redacted."""
    res = await session.execute(select(OidcProvider).order_by(OidcProvider.display_name))
    return {"providers": [_admin_provider_view(p) for p in res.scalars().all()]}


async def _validate_provider_issuer(issuer: str) -> None:
    """Refuse to save a provider whose discovery document does not check out.

    Saving first and discovering later means the failure surfaces to a user
    halfway through a login, with nothing but a 502 to go on.
    """
    try:
        await fetch_discovery(issuer)
    except OidcError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"The issuer could not be verified: {exc.detail}",
        ) from exc


@app.post("/api/v1/data/oidc/providers", status_code=201)
async def admin_create_oidc_provider(
    req: OidcProviderRequest,
    session: AsyncSession = Depends(get_session),
    _principal: Principal = Depends(require_platform_admin("owner", "admin")),
):
    existing = await session.execute(
        select(OidcProvider).where(OidcProvider.slug == req.slug)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="A provider with this slug already exists.")

    await _validate_provider_issuer(req.issuer)

    provider = OidcProvider(
        slug=req.slug,
        display_name=req.display_name,
        issuer=req.issuer.rstrip("/"),
        client_id=req.client_id,
        encrypted_client_secret=encrypt_secret(req.client_secret)
        if req.client_secret
        else None,
        scopes=req.scopes,
        redirect_uri=req.redirect_uri,
        claims_mapping=req.claims_mapping,
        enabled=req.enabled,
        allow_signup=req.allow_signup,
        require_verified_email=req.require_verified_email,
    )
    session.add(provider)
    await session.commit()
    logger.info(
        "[req_id=%s] OIDC provider %s created (enabled=%s)",
        get_current_request_id(),
        provider.slug,
        provider.enabled,
    )
    return _admin_provider_view(provider)


@app.put("/api/v1/data/oidc/providers/{slug}")
async def admin_update_oidc_provider(
    slug: str,
    req: OidcProviderRequest,
    session: AsyncSession = Depends(get_session),
    _principal: Principal = Depends(require_platform_admin("owner", "admin")),
):
    res = await session.execute(select(OidcProvider).where(OidcProvider.slug == slug))
    provider = res.scalars().first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    if req.issuer.rstrip("/") != provider.issuer:
        await _validate_provider_issuer(req.issuer)

    provider.display_name = req.display_name
    provider.issuer = req.issuer.rstrip("/")
    provider.client_id = req.client_id
    provider.scopes = req.scopes
    provider.redirect_uri = req.redirect_uri
    provider.claims_mapping = req.claims_mapping
    provider.enabled = req.enabled
    provider.allow_signup = req.allow_signup
    provider.require_verified_email = req.require_verified_email
    provider.updated_at = datetime.now(timezone.utc)

    # An omitted secret keeps the stored one. Clearing it on every edit would mean
    # re-entering the secret to toggle a checkbox.
    if req.client_secret:
        provider.encrypted_client_secret = encrypt_secret(req.client_secret)

    await session.commit()
    logger.info(
        "[req_id=%s] OIDC provider %s updated (enabled=%s)",
        get_current_request_id(),
        provider.slug,
        provider.enabled,
    )
    return _admin_provider_view(provider)


@app.delete("/api/v1/data/oidc/providers/{slug}", status_code=204)
async def admin_delete_oidc_provider(
    slug: str,
    session: AsyncSession = Depends(get_session),
    _principal: Principal = Depends(require_platform_admin("owner", "admin")),
):
    """Remove a provider.

    Linked identities are left in place deliberately. Deleting them would silently
    orphan accounts that have no password -- an OIDC-only user would simply lose
    access with no way back. Disabling the provider is the reversible action;
    deletion is for one that was never used.
    """
    res = await session.execute(select(OidcProvider).where(OidcProvider.slug == slug))
    provider = res.scalars().first()
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found.")

    linked = await session.execute(
        select(func.count())
        .select_from(UserIdentity)
        .where(UserIdentity.provider_slug == slug)
    )
    if (linked.scalar() or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Accounts still use this provider. Disable it instead of "
                "deleting it."
            ),
        )

    await session.delete(provider)
    await session.commit()
    logger.info(
        "[req_id=%s] OIDC provider %s deleted", get_current_request_id(), slug
    )
    return Response(status_code=204)


# ─── Legal documents ────────────────────────────────────────
#
# The imprint and the privacy policy, as text rather than as code. Both used to
# be TSX components carrying `[placeholder]` markers, so naming the operator meant
# editing source and rebuilding an image — and a deployment whose owner does not
# do that served a public legal notice identifying nobody.
#
# Markdown, never HTML. These are the only pages the platform serves to readers who
# are not signed in, and the dashboard's CSP still permits `'unsafe-inline'` in
# `script-src`; storing HTML here would be storing script on the widest-reach,
# least-authenticated page in the product. `react-markdown` does not pass raw HTML
# through, so nothing downstream has to be trusted to sanitise it.

#: The documents that exist. Closed on purpose: each is a statutory obligation with
#: a route of its own, not a page an operator invents, and a slug that reaches the
#: database without being in this set would be a page nothing renders.
LEGAL_DOCUMENT_SLUGS: Final[tuple[str, ...]] = ("imprint", "privacy")

#: Generous against any real policy — the longest German privacy policy in the wild
#: is a few tens of thousands of characters. Present so an accidental paste of a
#: whole website is refused with an explanation rather than truncated in silence.
MAX_LEGAL_BODY_CHARS: Final[int] = 200_000


class LegalDocumentRequest(BaseModel):
    """One document, both halves.

    Both bodies are optional and both may be cleared: emptying the German half is
    how an operator goes back to the shipped default, and refusing to accept an
    empty string would make that a database chore instead of an edit.
    """

    body_de: str | None = Field(None, max_length=MAX_LEGAL_BODY_CHARS)
    body_en: str | None = Field(None, max_length=MAX_LEGAL_BODY_CHARS)


def _legal_document_view(slug: str, document: LegalDocument | None) -> dict[str, Any]:
    """What both the public route and the editor read.

    `source` is the field that matters and the reason this is not just the row:
    a client cannot tell a deployment that wrote its own imprint from one still
    showing the template by looking at the text, and the difference is exactly
    what an operator needs to see. `custom` means at least one language was
    written; `default` means the shipped document is what a visitor gets.
    """
    body_de = (document.body_de or "").strip() if document else ""
    body_en = (document.body_en or "").strip() if document else ""
    return {
        "slug": slug,
        "body_de": body_de or None,
        "body_en": body_en or None,
        "source": "custom" if (body_de or body_en) else "default",
        "updated_at": document.updated_at.isoformat() if document and document.updated_at else None,
    }


async def _legal_documents(session: AsyncSession) -> dict[str, LegalDocument]:
    res = await session.execute(select(LegalDocument))
    return {row.slug: row for row in res.scalars().all()}


@app.get("/api/v1/legal/documents/{slug}")
async def get_legal_document(
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    """The stored text of one document. Unauthenticated by design.

    An imprint that only a signed-in reader can see does not discharge the
    obligation to publish one, so this endpoint is exempt from the auth middleware
    alongside the sign-in routes. It exposes nothing else: two markdown bodies the
    operator wrote in order to publish them.
    """
    if slug not in LEGAL_DOCUMENT_SLUGS:
        raise HTTPException(status_code=404, detail="Unknown legal document")

    res = await session.execute(select(LegalDocument).where(LegalDocument.slug == slug))
    return _legal_document_view(slug, res.scalars().first())


@app.get("/api/v1/data/legal/documents")
async def admin_list_legal_documents(
    session: AsyncSession = Depends(get_session),
    _principal: Principal = Depends(require_platform_admin("owner", "admin")),
):
    """Both documents, for the editor. Every slug appears, stored or not.

    A document nobody has written yet comes back with null bodies rather than
    being absent, so the editor renders the same two panels on a fresh deployment
    as on an established one and "not written yet" is a state instead of a gap.
    """
    stored = await _legal_documents(session)
    return {
        "documents": [
            _legal_document_view(slug, stored.get(slug)) for slug in LEGAL_DOCUMENT_SLUGS
        ]
    }


@app.put("/api/v1/data/legal/documents/{slug}")
async def admin_save_legal_document(
    slug: str,
    req: LegalDocumentRequest,
    session: AsyncSession = Depends(get_session),
    principal: Principal = Depends(require_platform_admin("owner", "admin")),
):
    """Write one document.

    Both halves are saved in one call, which is the closest a database row gets to
    the guarantee rule 16 used to obtain from the type system: while the documents
    were code, `Record<SectionId, ReactNode>` made a section present in German and
    missing in English a compile error. Nothing can typecheck a row, so the next
    best thing is that the two halves cannot be saved at different moments, and the
    one `updated_at` covers both.

    Neither half is required, and the German one governs (rule 16). What is refused
    is the combination that has no honest reading: English text with no German text
    at all, on a document whose binding version is the German one.
    """
    if slug not in LEGAL_DOCUMENT_SLUGS:
        raise HTTPException(status_code=404, detail="Unknown legal document")

    body_de = (req.body_de or "").strip()
    body_en = (req.body_en or "").strip()

    if body_en and not body_de:
        raise HTTPException(
            status_code=422,
            detail=(
                "The German version is the binding one and cannot be empty while "
                "the English version is set. Write the German text first; readers "
                "of either language are shown it until an English version exists."
            ),
        )

    res = await session.execute(select(LegalDocument).where(LegalDocument.slug == slug))
    document = res.scalars().first()
    now = datetime.now(timezone.utc)

    if document is None:
        document = LegalDocument(slug=slug, created_at=now)
        session.add(document)

    document.body_de = body_de or None
    document.body_en = body_en or None
    document.updated_by = principal.user_id
    document.updated_at = now

    await session.commit()
    await session.refresh(document)

    # The text itself is never logged. It is not a secret, but it is a document
    # measured in tens of kilobytes and a log is not where it belongs.
    logger.info(
        "[req_id=%s] Legal document %s saved (de=%s, en=%s)",
        get_current_request_id(),
        slug,
        "set" if document.body_de else "empty",
        "set" if document.body_en else "empty",
    )
    return _legal_document_view(slug, document)


class OidcStartRequest(BaseModel):
    redirect_uri: str | None = Field(None, description="Must match the configured URI exactly")


@app.post("/api/v1/auth/oidc/{slug}/start")
async def start_oidc_login(
    slug: str,
    req: OidcStartRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Begin an Authorization Code + PKCE login.

    ``state``, ``nonce`` and the PKCE verifier are stored server-side, so the
    browser never holds anything that would let it forge or replay the callback.
    """
    provider = await _load_enabled_provider(session, slug)
    body = req or OidcStartRequest()

    redirect_uri = body.redirect_uri or provider.redirect_uri
    if not is_redirect_uri_allowed(redirect_uri, provider.redirect_uri):
        raise HTTPException(status_code=400, detail="redirect_uri is not allowed for this provider")

    try:
        discovery = await fetch_discovery(provider.issuer)
        auth_request = build_authorization_request(
            discovery=discovery,
            client_id=provider.client_id,
            redirect_uri=redirect_uri,
            scopes=provider.scopes,
        )
    except OidcError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    now = datetime.now(timezone.utc)
    session.add(
        OidcAuthRequest(
            state=auth_request.state,
            provider_slug=provider.slug,
            nonce=auth_request.nonce,
            code_verifier=auth_request.code_verifier,
            redirect_uri=redirect_uri,
            expires_at=now + timedelta(seconds=AUTH_REQUEST_TTL_SECONDS),
        )
    )
    # Opportunistic cleanup of abandoned attempts.
    await session.execute(delete(OidcAuthRequest).where(OidcAuthRequest.expires_at < now))
    await session.commit()

    return {
        "authorization_url": auth_request.authorization_url,
        "state": auth_request.state,
        "expires_in": AUTH_REQUEST_TTL_SECONDS,
    }


class OidcCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=4096)
    state: str = Field(..., min_length=8, max_length=128)


@app.post("/api/v1/auth/oidc/{slug}/callback")
async def complete_oidc_login(
    slug: str,
    req: OidcCallbackRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Finish the flow: validate the token, resolve the account, issue a session."""
    provider = await _load_enabled_provider(session, slug)

    res = await session.execute(
        select(OidcAuthRequest).where(OidcAuthRequest.state == req.state)
    )
    auth_request = res.scalars().first()

    now = datetime.now(timezone.utc)
    if not auth_request or auth_request.provider_slug != slug:
        raise HTTPException(status_code=400, detail="Unknown or expired login attempt")
    if auth_request.consumed_at is not None:
        # Single use. A replayed state means the callback leaked.
        await session.execute(
            delete(OidcAuthRequest).where(OidcAuthRequest.state == req.state)
        )
        await session.commit()
        raise HTTPException(status_code=400, detail="This login attempt was already used")

    expires_at = auth_request.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise HTTPException(status_code=400, detail="This login attempt has expired")

    auth_request.consumed_at = now
    await session.commit()

    client_secret = None
    if provider.encrypted_client_secret:
        try:
            client_secret = decrypt_secret(provider.encrypted_client_secret)
        except DecryptionError:
            raise HTTPException(status_code=500, detail="Provider secret could not be decrypted")

    try:
        discovery = await fetch_discovery(provider.issuer)
        tokens = await exchange_code(
            discovery=discovery,
            client_id=provider.client_id,
            client_secret=client_secret,
            code=req.code,
            redirect_uri=auth_request.redirect_uri,
            code_verifier=auth_request.code_verifier,
        )
        identity = verify_id_token(
            id_token=tokens["id_token"],
            discovery=discovery,
            client_id=provider.client_id,
            issuer=provider.issuer,
            expected_nonce=auth_request.nonce,
        )
        identity = apply_claims_mapping(identity, provider.claims_mapping or {})
    except OidcError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    finally:
        await session.execute(
            delete(OidcAuthRequest).where(OidcAuthRequest.state == req.state)
        )
        await session.commit()

    # Identity is keyed on (provider, subject). Never on email.
    link_res = await session.execute(
        select(UserIdentity).where(
            UserIdentity.provider_slug == provider.slug,
            UserIdentity.subject == identity.subject,
        )
    )
    link = link_res.scalars().first()

    if link:
        user_res = await session.execute(select(User).where(User.id == link.user_id))
        user = user_res.scalars().first()
        if not user:
            raise HTTPException(status_code=401, detail="Linked account no longer exists")
        link.last_login_at = now
        link.email = identity.email
        await session.commit()
        return await _oidc_session_response(
            session, response, user, provider.slug, linked=False
        )

    # No link yet. Everything below is first contact, which is where account
    # takeover happens if the rules are loose.
    if provider.require_verified_email and not identity.email_verified:
        raise HTTPException(
            status_code=403,
            detail=(
                "The provider did not confirm this email address as verified. "
                "Sign in with your email address and password, then link the "
                "provider in the settings."
            ),
        )
    if not identity.email:
        raise HTTPException(
            status_code=403, detail="The provider did not supply an email address."
        )

    existing_res = await session.execute(select(User).where(User.email == identity.email))
    existing_user = existing_res.scalars().first()

    if existing_user:
        # An account with this address already exists but was never linked.
        # Auto-linking on a matching email is exactly the takeover vector: anyone
        # who can get a provider to assert an address would inherit the account.
        raise HTTPException(
            status_code=409,
            detail=(
                "An account already exists for this email address. Sign in with "
                "your email address and password, then link the provider in the "
                "settings."
            ),
        )

    if not provider.allow_signup or not settings.ALLOW_REGISTRATION:
        raise HTTPException(
            status_code=403, detail="Sign-up through this provider is disabled."
        )

    tenant_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    display_name = identity.name or identity.email.split("@")[0]

    session.add(Tenant(id=tenant_id, name=f"{display_name}'s Workspace"))
    session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            email=identity.email,
            # No local password. Sign-in works only through the provider until the
            # user sets one; an empty string would be a hash nobody can match.
            password_hash="!oidc-only",
            name=display_name,
            role="owner",
        )
    )
    # Flush before the identity row: it carries a foreign key to users, and the
    # unit of work does not otherwise guarantee the user is inserted first.
    await session.flush()

    session.add(
        UserIdentity(
            user_id=user_id,
            tenant_id=tenant_id,
            provider_slug=provider.slug,
            subject=identity.subject,
            email=identity.email,
            last_login_at=now,
        )
    )
    await session.commit()

    created_res = await session.execute(select(User).where(User.id == user_id))
    return await _oidc_session_response(
        session, response, created_res.scalars().first(), provider.slug, linked=True
    )


async def _oidc_session_response(
    session: AsyncSession,
    response: Response,
    user: User,
    provider_slug: str,
    *,
    linked: bool,
) -> dict[str, Any]:
    """Issue the same session an email/password login would."""
    tenant_name = (
        await session.execute(select(Tenant.name).where(Tenant.id == user.tenant_id))
    ).scalar_one()
    tokens = await _issue_session(
        session,
        response,
        user_id=user.id,
        tenant_id=user.tenant_id,
        email=user.email,
        role=user.role,
    )
    logger.info(
        "OIDC login succeeded via %s for user=%s tenant=%s (new_account=%s)",
        provider_slug,
        user.id,
        user.tenant_id,
        linked,
    )
    return {
        "status": "success",
        **tokens,
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "workspace_name": tenant_name,
        "provider": provider_slug,
        "account_created": linked,
    }


@app.post("/api/v1/auth/oidc/{slug}/backchannel-logout")
async def oidc_backchannel_logout(
    slug: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """End every local session for an identity the provider has signed out.

    The other direction to RP-initiated logout. Here the session ends *at the
    provider* — the user signs out of Google, an administrator disables the
    account, a device is deprovisioned — and the provider POSTs a signed logout
    token to us out of band. Nothing consumed it before, so the local session
    survived until its own expiry: up to thirty days after the identity behind it
    was withdrawn.

    The caller is a server, not a browser, and holds no session with us, so the
    endpoint is necessarily unauthenticated (it is covered by the
    ``/api/v1/auth/oidc/`` exemption in the auth middleware). Everything rests on
    :func:`verify_logout_token`; see ``specs/oidc_backchannel_logout.fizz`` for
    the check list stated as an invariant.

    Maps to Fizzbee Invariants:
    - AcceptedTokenWasGenuine
    - AcceptedLogoutLeavesNothingItCoveredAlive
    - ProviderLogoutEventuallyEndsEverySession
    """
    provider = await _load_enabled_provider(session, slug)

    # Parsed by hand rather than with `Form(...)`, which would pull in
    # python-multipart for one field. The specification mandates exactly this
    # content type, so accepting anything else would be a favour to nobody.
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip()
    if content_type != "application/x-www-form-urlencoded":
        raise HTTPException(
            status_code=400,
            detail="A logout token must be posted as application/x-www-form-urlencoded",
        )

    fields = parse_qs((await request.body()).decode("utf-8", errors="replace"))
    tokens = fields.get("logout_token") or []
    if len(tokens) != 1 or not tokens[0]:
        raise HTTPException(status_code=400, detail="Exactly one logout_token is required")

    try:
        discovery = await fetch_discovery(provider.issuer)
        named = verify_logout_token(
            logout_token=tokens[0],
            discovery=discovery,
            client_id=provider.client_id,
            issuer=provider.issuer,
        )
    except OidcError as exc:
        # 400 means "do not retry, this token is wrong"; 503 means "we could not
        # check, come back". Collapsing the two would either make a key-server
        # blip permanent or make a forged token a source of retries forever.
        logger.warning(
            "[req_id=%s] Rejected a back-channel logout for %s: %s",
            get_current_request_id(),
            slug,
            exc.detail,
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    if not named.subject:
        # Only `sid` was supplied. Our access tokens are not bound to a provider
        # session id, so there is nothing to match it against, and guessing would
        # mean ending sessions the provider did not name. Operators must leave
        # `backchannel_logout_session_required` off at the provider, which obliges
        # it to send `sub`.
        raise HTTPException(
            status_code=400,
            detail="This deployment requires a sub claim; sid-only logout is not supported",
        )

    identity = (
        await session.execute(
            select(UserIdentity).where(
                UserIdentity.provider_slug == slug,
                UserIdentity.subject == named.subject,
            )
        )
    ).scalars().first()

    if identity is None:
        # Nothing linked to that subject. 200 rather than 404: the provider is
        # telling us something true, we simply have nothing to do about it, and a
        # 404 would have it retry an event that will never apply. It is also not
        # this endpoint's job to disclose which subjects have accounts here.
        logger.info(
            "[req_id=%s] Back-channel logout for %s named an unknown subject",
            get_current_request_id(),
            slug,
        )
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    await _revoke_all_sessions(
        session,
        tenant_id=identity.tenant_id,
        user_id=identity.user_id,
        reason="oidc_backchannel_logout",
    )
    await session.commit()

    logger.info(
        "[req_id=%s] Back-channel logout from %s ended every session for user=%s tenant=%s",
        get_current_request_id(),
        slug,
        identity.user_id,
        identity.tenant_id,
    )
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


@app.get("/api/v1/data/system/warnings")
async def list_system_warnings(session: AsyncSession = Depends(get_session)):
    """Configuration and credential problems, for the dashboard to show.

    These existed already — in the startup log, in a commit message, in
    docs/operations.md. None of which anybody reads. A platform running on a
    signing key that is printed in its own source should say so where its
    operator is looking, which is the dashboard.

    Scoped by role rather than uniformly: deployment warnings name *which* secret
    is weak, so they go to owners and administrators. The account warning is
    about the caller's own password and goes to the caller whatever their role —
    withholding "your password is public" from a member would be absurd.
    """
    principal = get_current_principal()

    user = (
        await session.execute(
            select(User).where(
                User.id == principal.user_id, User.tenant_id == principal.tenant_id
            )
        )
    ).scalars().first()

    warnings = account_warnings(password_hash=user.password_hash if user else None)

    if principal.role in {"owner", "admin"}:
        warnings.extend(
            deployment_warnings(
                environment=settings.ENVIRONMENT,
                jwt_secret=settings.JWT_SECRET,
                encryption_key=settings.ENCRYPTION_KEY,
                internal_secret=settings.INTERNAL_SERVICE_SECRET,
                allow_registration=settings.ALLOW_REGISTRATION,
                cookie_secure=settings.COOKIE_SECURE,
            )
        )
        if stream_warning := await ingestion_retention_warning(
            getattr(app.state, "nats_client", None)
        ):
            warnings.append(stream_warning)
        # A connector that stopped importing is an operational fact the operator has
        # to be able to see. Scheduled imports once stopped for a day with nothing
        # saying so — every card still showed its last successful run, which is what
        # a healthy connector looks like too.
        if overdue_warning := await overdue_connector_warning(
            session, principal.tenant_id
        ):
            warnings.append(overdue_warning)

    return {"warnings": [w.as_dict() for w in warnings]}


@app.post("/api/v1/data/system/ingestion/reset")
async def reset_ingestion_stream(
    _principal: Principal = Depends(require_platform_admin("owner")),
):
    """Reset the shared ingestion stream only from its consumer-owning role."""
    if settings.CORE_ROLE.lower() not in {"all", "ingest"}:
        return JSONResponse(
            status_code=404,
            content={
                "code": "ingestion_reset_unavailable",
                "detail": "The ingestion reset is served only by Core's ingest role.",
            },
        )

    controller = getattr(app.state, "ingestion_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={
                "code": "ingestion_consumer_unavailable",
                "detail": "The ingestion consumer is not available; no stream was deleted.",
            },
        )

    try:
        result = await controller.reset()
    except IngestionResetError as exc:
        logger.warning(
            "[req_id=%s] Ingestion stream reset refused code=%s num_pending=%s num_ack_pending=%s",
            get_current_request_id(),
            exc.code,
            exc.num_pending,
            exc.num_ack_pending,
        )
        return JSONResponse(status_code=exc.status_code, content=exc.as_dict())

    logger.info(
        "[req_id=%s] Ingestion stream reset completed code=%s",
        get_current_request_id(),
        result["code"],
    )
    return result


@app.get("/api/v1/data/oidc/identities")
async def list_my_identities(session: AsyncSession = Depends(get_session)):
    """Providers linked to the calling user."""
    principal = get_current_principal()
    res = await session.execute(
        select(UserIdentity).where(UserIdentity.user_id == principal.user_id)
    )
    return {
        "identities": [
            {
                "provider_slug": i.provider_slug,
                "email": i.email,
                "linked_at": i.created_at.isoformat() if i.created_at else None,
                "last_login_at": i.last_login_at.isoformat() if i.last_login_at else None,
            }
            for i in res.scalars().all()
        ]
    }


@app.delete("/api/v1/data/oidc/identities/{provider_slug}")
async def unlink_identity(
    provider_slug: str,
    session: AsyncSession = Depends(get_session),
):
    """Unlink a provider, refusing to leave the account unreachable."""
    principal = get_current_principal()

    user_res = await session.execute(select(User).where(User.id == principal.user_id))
    user = user_res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Account not found")

    res = await session.execute(
        select(UserIdentity).where(
            UserIdentity.user_id == principal.user_id,
            UserIdentity.provider_slug == provider_slug,
        )
    )
    identity = res.scalars().first()
    if not identity:
        raise HTTPException(status_code=404, detail="Provider is not linked to this account")

    remaining = await session.execute(
        select(func.count())
        .select_from(UserIdentity)
        .where(UserIdentity.user_id == principal.user_id)
    )
    has_password = user.password_hash and user.password_hash != "!oidc-only"
    if (remaining.scalar() or 0) <= 1 and not has_password:
        raise HTTPException(
            status_code=409,
            detail=(
                "This is the only way to sign in to this account. Set a password "
                "first, or link another provider."
            ),
        )

    await session.delete(identity)
    await session.commit()
    return {"status": "unlinked", "provider_slug": provider_slug}


# ─── Core Metric Endpoints ───────────────────────────────────

def _definition_payload(
    metric_type: str,
    custom_definitions: dict[str, MetricDefinition] | None = None,
) -> dict[str, Any] | None:
    """Registry definition for a stored metric name, or ``None`` if it has none.

    A tenant can hold rows written before a catalog entry was renamed or removed, and
    those rows must still list and still chart. Returning ``None`` says "this is data
    without a current definition", which a caller can render; omitting the metric would
    make it look like the data were gone.
    """
    if custom_definitions and metric_type in custom_definitions:
        return custom_definitions[metric_type].model_dump(mode="json")
    try:
        return describe(metric_type).model_dump(mode="json")
    except UnknownMetricTypeError:
        return None


def _ingest_policy_payload(
    metric_type: str,
    definition: MetricDefinition | None = None,
    override: MetricIngestPolicy | None = None,
) -> dict[str, Any]:
    """Serialize the effective importer policy without exposing tenant internals."""
    definition = definition or _definition_payload(metric_type)
    if isinstance(definition, MetricDefinition):
        default_resolution = definition.default_ingest_resolution.value
        aggregation = definition.aggregation.value
        retention = definition.raw_retention_days
    elif isinstance(definition, dict):
        default_resolution = definition.get("ingest_resolution")
        if default_resolution is None:
            default_resolution = (
                IngestResolution.MINUTE.value
                if definition.get("cadence") == Cadence.CONTINUOUS.value
                else IngestResolution.RAW.value
            )
        aggregation = definition.get("aggregation", "average")
        stated = definition.get("raw_retention_days", 90)
        # `None` is a value here, not a missing key: it means never purge. Coercing
        # it with `int()` raised, and defaulting it to 90 would have quietly put an
        # expiry on the metrics whose fine-grained form is the data.
        retention = None if stated is None else int(stated)
    else:
        default_resolution = IngestResolution.RAW.value
        aggregation = "average"
        retention = 90
    resolution = override.resolution if override is not None else default_resolution
    return {
        "metric_type": metric_type,
        "resolution": resolution,
        "default_resolution": default_resolution,
        "aggregation": aggregation,
        "raw_retention_days": override.raw_retention_days if override else retention,
        "effective_from": override.updated_at.isoformat() if override else None,
    }


def _round(value: float | None, digits: int) -> float | None:
    """Round an aggregate to the precision the metric declares."""
    return round(float(value), digits) if value is not None else None


def _rollup_covers_point(resolution: str):
    """Return a predicate for raw points already represented by a rollup.

    A deployment can contain both legacy raw points and newer incremental rollups.
    The rollup's timestamp bounds let the compatibility query retain raw points
    before or after a partially covered bucket, while provider totals remain
    authoritative for their whole bucket. This keeps mixed history visible without
    blindly adding the same point to a rollup twice.
    """
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



@app.get("/api/v1/data/metrics")
async def query_metrics(
    metric_type: str | None = Query(None, description="Filter by metric type (e.g. sleep_score, steps)"),
    start_time: str | None = Query(None, description="ISO start timestamp"),
    end_time: str | None = Query(None, description="ISO end timestamp"),
    source_id: str | None = Query(None, description="Filter by connector instance"),
    source_type: str | None = Query(None, description="Filter by connector type"),
    resolution: Literal["auto", "raw", "second", "minute", "hour", "day"] = Query(
        "raw", description="Stored points or a server-side rollup resolution"
    ),
    limit: int = Query(100, ge=1, le=10000, description="Max points or buckets to return"),
    sort: Literal["asc", "desc"] = Query("asc", description="Sort by timestamp"),
    session: AsyncSession = Depends(get_session),
):
    """Query raw points or bounded, tenant-scoped rollups."""
    tenant_id = get_current_tenant_id()
    start_dt: datetime | None = None
    end_dt: datetime | None = None
    try:
        if start_time:
            start_dt = datetime.fromisoformat(start_time)
        if end_time:
            end_dt = datetime.fromisoformat(end_time)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO timestamp") from None
    if start_dt and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt and end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt and end_dt and end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    effective_resolution = resolution
    # `second` is not a rollup tier and never will be: a second bucket has the same
    # cardinality as `data_points`, so storing one would double the storage to answer
    # nothing faster. The stored points already *are* the second-resolution answer,
    # so the request reads them directly.
    if effective_resolution == "second":
        effective_resolution = "raw"

    if resolution == "auto":
        if not start_dt or not end_dt:
            effective_resolution = "raw"
        else:
            duration = end_dt - start_dt
            effective_resolution = (
                # A workout-length window gets whatever was stored, which for heart
                # rate is now per second. Bucketing an interval session by the minute
                # is what turned it into a flat line.
                "raw" if duration <= timedelta(hours=2)
                else "minute" if duration <= timedelta(hours=24)
                else "hour" if duration <= timedelta(days=90)
                else "day"
            )

    source_filter = []
    if source_id:
        source_filter.append(DataSource.id == source_id)
    if source_type:
        source_filter.append(DataSource.source_type == source_type)

    if effective_resolution != "raw":
        stmt = (
            select(MetricRollup, DataSource.source_type)
            .join(
                DataSource,
                and_(
                    DataSource.id == MetricRollup.source_id,
                    DataSource.tenant_id == tenant_id,
                ),
            )
            .where(
                MetricRollup.tenant_id == tenant_id,
                MetricRollup.resolution == effective_resolution,
                *source_filter,
            )
        )
        if metric_type:
            stmt = stmt.where(MetricRollup.metric_type == metric_type)
        if start_dt:
            stmt = stmt.where(MetricRollup.bucket_start >= start_dt)
        if end_dt:
            stmt = stmt.where(MetricRollup.bucket_start <= end_dt)
        stmt = stmt.order_by(
            MetricRollup.bucket_start.desc()
            if sort == "desc"
            else MetricRollup.bucket_start.asc()
        ).limit(limit)
        rollup_rows = (await session.execute(stmt)).all()

        # Do not use rollups as an all-or-nothing switch. Historical data may have
        # been written before incremental rollups existed, or a first bucket may
        # only be partly covered by a deployment that has just started producing
        # them. Return those legacy points alongside the rollups, bounded by the
        # same limit and marked so clients can explain the mixed resolution.
        #
        # Two bounds keep that compatibility query from costing more than the answer
        # it contributes. `~_rollup_covers_point` has to be applied to every point
        # the query considers, and it is at its most expensive exactly when it finds
        # nothing — the normal case for a deployment whose data all arrived after
        # rollups existed. Without them, a chart request with no time window walked
        # the tenant's entire history to return zero rows. `core.rollup_coverage`
        # then removes the query outright once that has been proven once.
        # The proof in `core.rollup_coverage` is about day buckets alone. A minute
        # or hour request must still read raw points: an ordinary raw point is only
        # ever rolled up into a day, so at those resolutions it is uncovered by
        # design and the fallback is where the answer comes from, not a compensation.
        covered = effective_resolution == "day" and not may_hold_points_outside_day_rollups(
            tenant_id
        )
        raw_rows: list[Any] = []
        if rollup_rows and not covered:
            # A full page of rollups means `limit` items already rank ahead of the
            # oldest one returned (newest one, ascending), so a legacy point beyond
            # that boundary cannot survive the `points[:limit]` slice below. Bounding
            # the scan there is not an approximation: the discarded rows are exactly
            # the rows the slice discarded before.
            boundary: datetime | None = None
            if len(rollup_rows) == limit:
                buckets = [rollup.bucket_start for rollup, _ in rollup_rows]
                boundary = min(buckets) if sort == "desc" else max(buckets)

            raw_stmt = (
                select(DataPoint, DataSource.source_type)
                .join(
                    DataSource,
                    and_(DataSource.id == DataPoint.source_id, DataSource.tenant_id == tenant_id),
                )
                .where(
                    DataPoint.tenant_id == tenant_id,
                    ~_rollup_covers_point(effective_resolution),
                    *source_filter,
                )
            )
            if metric_type:
                raw_stmt = raw_stmt.where(DataPoint.metric_type == metric_type)
            if start_dt:
                raw_stmt = raw_stmt.where(DataPoint.timestamp >= start_dt)
            if end_dt:
                raw_stmt = raw_stmt.where(DataPoint.timestamp <= end_dt)
            if boundary is not None:
                raw_stmt = raw_stmt.where(
                    DataPoint.timestamp >= boundary
                    if sort == "desc"
                    else DataPoint.timestamp <= boundary
                )
            raw_stmt = raw_stmt.order_by(
                DataPoint.timestamp.desc() if sort == "desc" else DataPoint.timestamp.asc()
            ).limit(limit)
            raw_rows = (await session.execute(raw_stmt)).all()

        points = [
            {
                "id": rollup.id,
                "source_id": rollup.source_id,
                "source_type": source,
                "metric_type": rollup.metric_type,
                "timestamp": rollup.bucket_start.isoformat(),
                "value": rollup.value,
                "metadata": {
                    **(rollup.metadata_ or {}),
                    "sample_count": rollup.sample_count,
                    "resolution": rollup.resolution,
                    "derived": not rollup.is_provider_total,
                },
                "sample_count": rollup.sample_count,
                # The bucket's spread, so a chart can draw the range a mean hides.
                # A minute of heart rate averaging 162 says nothing about whether it
                # was flat or ran from 140 to 186, and the second is a different
                # workout.
                "min": rollup.min_value,
                "max": rollup.max_value,
                "is_derived": not rollup.is_provider_total,
                "_sort_timestamp": rollup.bucket_start,
            }
            for rollup, source in rollup_rows
        ]
        points.extend(
            {
                "id": point.id,
                "source_id": point.source_id,
                "source_type": source,
                "metric_type": point.metric_type,
                "timestamp": point.timestamp.isoformat(),
                "value": point.value,
                "metadata": {
                    **(point.metadata_ or {}),
                    "resolution": "raw",
                    "compatibility_fallback": True,
                    "sample_count": 1,
                },
                "sample_count": 1,
                "is_derived": False,
                "_sort_timestamp": point.timestamp,
            }
            for point, source in raw_rows
        )
        points.sort(key=lambda item: item["_sort_timestamp"], reverse=sort == "desc")
        points = points[:limit]
        if points and rollup_rows:
            return {
                "tenant_id": tenant_id,
                "count": len(points),
                "resolution": effective_resolution,
                "rollup_available": bool(rollup_rows),
                "contains_legacy_raw": bool(raw_rows),
                "data_points": [
                    {key: value for key, value in point.items() if key != "_sort_timestamp"}
                    for point in points
                ],
            }

    stmt = (
        select(DataPoint, DataSource.source_type)
        .join(
            DataSource,
            and_(DataSource.id == DataPoint.source_id, DataSource.tenant_id == tenant_id),
        )
        .where(DataPoint.tenant_id == tenant_id, *source_filter)
    )
    if metric_type:
        stmt = stmt.where(DataPoint.metric_type == metric_type)
    if start_dt:
        stmt = stmt.where(DataPoint.timestamp >= start_dt)
    if end_dt:
        stmt = stmt.where(DataPoint.timestamp <= end_dt)
    stmt = stmt.order_by(
        DataPoint.timestamp.desc() if sort == "desc" else DataPoint.timestamp.asc()
    ).limit(limit)
    rows = (await session.execute(stmt)).all()
    return {
        "tenant_id": tenant_id,
        "count": len(rows),
        "resolution": "raw",
        "rollup_available": False,
        "data_points": [
            {
                "id": point.id,
                "source_id": point.source_id,
                "source_type": source,
                "metric_type": point.metric_type,
                "timestamp": point.timestamp.isoformat(),
                "value": point.value,
                "metadata": point.metadata_,
                "idempotency_key": point.idempotency_key,
                "is_derived": False,
            }
            for point, source in rows
        ],
    }


@app.get("/api/v1/data/metrics/catalog")
async def get_metric_catalog():
    """The metric registry: every metric the platform defines, with unit and meaning.

    Tenant-independent on purpose — this is the platform's vocabulary, not a tenant's
    data, so it needs no tenant filter and reveals nothing about anyone. Tenant-scoped
    questions ("which of these do I actually have?") are `/metrics/types`.

    The dashboard ships a generated copy of this catalog for rendering, so it does not
    have to wait on a request to know a unit. The endpoint exists for everything else:
    API clients, the CSV mapper's target list, and confirming what a deployed Core
    actually accepts.
    """
    return {
        "metrics": [METRIC_CATALOG[key].model_dump(mode="json") for key in CANONICAL_KEYS],
        "aliases": dict(sorted(METRIC_ALIASES.items())),
        "namespaces": [ns.model_dump(mode="json") for ns in DYNAMIC_NAMESPACES],
    }


class MetricIngestPolicyRequest(BaseModel):
    """Tenant-owned resolution override used by future imports."""

    resolution: IngestResolution
    #: Explicit `null` means never purge. **Omitting the field keeps whatever the
    #: registry says**, which is not the same thing and is why this defaults to
    #: `None` rather than to 90.
    #:
    #: A default of 90 meant that changing a metric's *resolution* silently wrote a
    #: ninety-day expiry onto it. For a `workout_*`, `strength_*` or `location_*`
    #: metric — the ones `NEVER_PURGED_CATEGORIES` exists to protect — the next
    #: retention run then deleted the GPS fixes and the sets, and reported nothing
    #: unusual, because a policy row of 90 is indistinguishable from a workspace
    #: asking for 90.
    raw_retention_days: int | None = Field(None, ge=0, le=3650)

    def retention_for(self, definition: MetricDefinition | None) -> int | None:
        """The retention to store: the caller's if they stated one, else the registry's."""
        if "raw_retention_days" in self.model_fields_set:
            return self.raw_retention_days
        if isinstance(definition, MetricDefinition):
            return definition.raw_retention_days
        return 90


async def _effective_ingest_policies(
    session: AsyncSession, tenant_id: str
) -> dict[str, dict[str, Any]]:
    """Build the full registry policy map and apply tenant overrides."""
    result = await session.execute(
        select(MetricIngestPolicy).where(MetricIngestPolicy.tenant_id == tenant_id)
    )
    overrides = {row.metric_type: row for row in result.scalars().all()}
    return {
        key: _ingest_policy_payload(key, override=overrides.get(key))
        for key in CANONICAL_KEYS
    }


@app.get("/api/v1/data/metrics/ingest-policy")
async def get_ingest_policy(session: AsyncSession = Depends(get_session)):
    """Return effective metric resolution rules for the authenticated workspace."""
    tenant_id = get_current_tenant_id()
    return {
        "tenant_id": tenant_id,
        "policies": await _effective_ingest_policies(session, tenant_id),
        "applies_to": "future_imports",
    }


@app.put("/api/v1/data/metrics/ingest-policy/{metric_type}")
async def set_ingest_policy(
    metric_type: str,
    req: MetricIngestPolicyRequest,
    session: AsyncSession = Depends(get_session),
):
    """Set one workspace metric resolution for future importer runs."""
    tenant_id = get_current_tenant_id()
    try:
        canonical = canonical_metric_type(metric_type)
    except UnknownMetricTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if canonical != metric_type:
        raise HTTPException(status_code=422, detail="metric_type must be canonical")

    definition = describe(canonical)
    retention = req.retention_for(definition)
    statement = pg_insert(MetricIngestPolicy).values(
        tenant_id=tenant_id,
        metric_type=canonical,
        resolution=req.resolution.value,
        raw_retention_days=retention,
        updated_at=datetime.now(timezone.utc),
    )
    statement = statement.on_conflict_do_update(
        index_elements=["tenant_id", "metric_type"],
        set_={
            "resolution": statement.excluded.resolution,
            "raw_retention_days": statement.excluded.raw_retention_days,
            "updated_at": statement.excluded.updated_at,
        },
    )
    await session.execute(statement)
    await session.commit()
    stored = (
        await session.execute(
            select(MetricIngestPolicy).where(
                MetricIngestPolicy.tenant_id == tenant_id,
                MetricIngestPolicy.metric_type == canonical,
            )
        )
    ).scalar_one_or_none()
    return {
        "tenant_id": tenant_id,
        # With the override, so the echoed policy is the one that was stored.
        # Without it this reported the registry default while the sibling field and
        # the database said something else — the response contradicted itself on the
        # one field that decides whether data is deleted.
        "policy": _ingest_policy_payload(canonical, definition=definition, override=stored),
        "resolution": req.resolution.value,
        "raw_retention_days": retention,
        "applies_to": "future_imports",
    }


class MetricSourcePreferenceRequest(BaseModel):
    primary_source_id: str = Field(..., min_length=1, max_length=64)


@app.get("/api/v1/data/metrics/source-preferences")
async def list_metric_source_preferences(
    session: AsyncSession = Depends(get_session),
):
    """Metrics that more than one connector reports, and which one answers.

    Only ambiguous metrics are listed: a metric with a single source needs no
    decision, and offering one would invite a reader to state a preference that
    can never matter. `coverage` is what the automatic choice is made on, so the
    reader can see why the default is what it is.
    """
    tenant_id = get_current_tenant_id()

    # The same figures the analysis uses to resolve its own primary source, so
    # the card cannot name one connector while the bundle counted another.
    coverage: dict[str, dict[str, int]] = {}
    for (metric_type, source_id), samples in (
        await metric_source_coverage(session, tenant_id)
    ).items():
        coverage.setdefault(metric_type, {})[source_id] = samples

    source_types = {
        str(source_id): source_type
        for source_id, source_type in (
            await session.execute(
                select(DataSource.id, DataSource.source_type).where(
                    DataSource.tenant_id == tenant_id
                )
            )
        ).all()
    }
    preferences = await primary_source_preferences(session, tenant_id)

    ambiguous = []
    for metric_type, by_source in sorted(coverage.items()):
        if len(by_source) < 2:
            continue
        primary, reason = resolve_primary_source(
            sorted(by_source),
            preference=preferences.get(metric_type),
            coverage=by_source,
        )
        ambiguous.append(
            {
                "metric_type": metric_type,
                "definition": _definition_payload(metric_type),
                "primary_source_id": primary,
                # preference or coverage — a stable identifier, not prose (rule 17).
                "primary_reason": reason,
                "sources": [
                    {
                        "source_id": source_id,
                        "source_type": source_types.get(source_id),
                        "sample_count": samples,
                    }
                    for source_id, samples in sorted(
                        by_source.items(), key=lambda item: (-item[1], item[0])
                    )
                ],
            }
        )

    return {"tenant_id": tenant_id, "metrics": ambiguous}


@app.put("/api/v1/data/metrics/source-preferences/{metric_type}")
async def set_metric_source_preference(
    metric_type: str,
    req: MetricSourcePreferenceRequest,
    session: AsyncSession = Depends(get_session),
):
    """Name the connector that answers for one metric.

    The choice survives a connector that later reports more: it is a statement
    about which device the reader trusts, and volume does not overrule it.
    """
    tenant_id = get_current_tenant_id()
    canonical = _canonical_or_400(metric_type)

    source = await _resolve_source(session, tenant_id, source_id=req.primary_source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Connector not found")

    statement = insert(MetricSourcePreference).values(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        metric_type=canonical,
        primary_source_id=source.id,
        updated_at=datetime.now(timezone.utc),
    ).on_conflict_do_update(
        index_elements=["tenant_id", "metric_type"],
        set_={
            "primary_source_id": source.id,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    await session.execute(statement)
    await session.commit()
    # The stored analysis was computed against the previous choice, so it is now
    # wrong rather than merely old. Queue a fresh one instead of waiting for the
    # next data change, which may be hours away.
    await _queue_insights_refresh(tenant_id)
    return {
        "tenant_id": tenant_id,
        "metric_type": canonical,
        "primary_source_id": source.id,
        "primary_reason": REASON_PREFERENCE,
    }


@app.delete("/api/v1/data/metrics/source-preferences/{metric_type}", status_code=200)
async def clear_metric_source_preference(
    metric_type: str,
    session: AsyncSession = Depends(get_session),
):
    """Drop a stated preference and go back to deciding by coverage."""
    tenant_id = get_current_tenant_id()
    canonical = _canonical_or_400(metric_type)
    await session.execute(
        delete(MetricSourcePreference).where(
            MetricSourcePreference.tenant_id == tenant_id,
            MetricSourcePreference.metric_type == canonical,
        )
    )
    await session.commit()
    await _queue_insights_refresh(tenant_id)
    return {
        "tenant_id": tenant_id,
        "metric_type": canonical,
        "primary_reason": REASON_COVERAGE,
    }


def _canonical_or_400(metric_type: str) -> str:
    try:
        return canonical_metric_type(metric_type)
    except UnknownMetricTypeError:
        raise HTTPException(
            status_code=400, detail="Unknown metric type"
        ) from None


async def _queue_insights_refresh(tenant_id: str) -> None:
    """Ask for a fresh insights bundle after something changed what it means.

    Its own session and never fatal: a preference was saved either way, and a
    report that fails to queue is recomputed by the next scheduler tick.
    """
    try:
        async with async_session_maker() as session:
            await acquire_report_lock(session, tenant_id, "insights")
            if not await has_in_flight_report(
                session, tenant_id, "insights", now=datetime.now(timezone.utc)
            ):
                await enqueue_report_run(
                    session,
                    tenant_id=tenant_id,
                    kind="insights",
                    trigger="manual",
                    request_id=get_current_request_id() or str(uuid.uuid4()),
                )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - the preference is saved either way
        logger.warning(
            "Could not queue an insights refresh for tenant=%s (%s)",
            tenant_id,
            type(exc).__name__,
        )


@app.get("/api/v1/data/metrics/types")
async def list_metric_types(
    session: AsyncSession = Depends(get_session),
):
    """List all distinct metric types stored for the authenticated tenant.

    Each name is returned with its registry definition, so a caller does not have to
    hold a second copy of the catalog to know that `energy_active` is kilocalories and
    sums rather than averages. Names under a dynamic namespace get a synthesised
    definition; rows written before a catalog change get a null one rather than
    disappearing from the list.
    """
    tenant_id = get_current_tenant_id()
    stmt = (
        select(distinct(DataPoint.metric_type))
        .where(DataPoint.tenant_id == tenant_id)
        .order_by(DataPoint.metric_type.asc())
    )
    res = await session.execute(stmt)
    metric_types = list(res.scalars().all())
    custom_rules = await session.execute(
        select(MetricMappingRule).where(
            MetricMappingRule.tenant_id == tenant_id,
            MetricMappingRule.action == "adopt",
        )
    )
    custom_definitions = custom_definitions_from_rules(list(custom_rules.scalars()))

    return {
        "tenant_id": tenant_id,
        "metric_types": metric_types,
        "definitions": {
            name: _definition_payload(name, custom_definitions) for name in metric_types
        },
    }


@app.get("/api/v1/data/metrics/summary")
async def get_metrics_summary(
    session: AsyncSession = Depends(get_session),
):
    """Get summary statistics from day rollups, with a compatibility fallback.

    The fallback covers points stored before rollups existed. It has no time
    window to bound it — the answer is the workspace's whole history — so it is
    the one query here that scales with the size of the data rather than with the
    number of days. `core.rollup_coverage` explains why it only ever has to run
    until it comes back empty once.
    """
    tenant_id = get_current_tenant_id()
    rollup_stmt = (
        select(
            MetricRollup.metric_type,
            func.sum(MetricRollup.sample_count).label("count"),
            (
                func.sum(MetricRollup.sum_value)
                / func.nullif(func.sum(MetricRollup.sample_count), 0)
            ).label("avg_value"),
            func.min(MetricRollup.min_value).label("min_value"),
            func.max(MetricRollup.max_value).label("max_value"),
            func.sum(MetricRollup.sum_value).label("sum_value"),
            func.max(MetricRollup.last_timestamp).label("latest_timestamp"),
        )
        .where(
            MetricRollup.tenant_id == tenant_id,
            MetricRollup.resolution == "day",
        )
        .group_by(MetricRollup.metric_type)
        .order_by(MetricRollup.metric_type.asc())
    )
    rollup_rows = (await session.execute(rollup_stmt)).all()

    raw_rows: list[Any] = []
    if may_hold_points_outside_day_rollups(tenant_id):
        raw_stmt = (
            select(
                DataPoint.metric_type,
                func.count(DataPoint.id).label("count"),
                func.avg(DataPoint.value).label("avg_value"),
                func.min(DataPoint.value).label("min_value"),
                func.max(DataPoint.value).label("max_value"),
                func.sum(DataPoint.value).label("sum_value"),
                func.max(DataPoint.timestamp).label("latest_timestamp"),
            )
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.value.is_not(None),
                ~_rollup_covers_point("day"),
            )
            .group_by(DataPoint.metric_type)
            .order_by(DataPoint.metric_type.asc())
        )
        raw_rows = (await session.execute(raw_stmt)).all()
        if not raw_rows:
            # Proven, not assumed: this workspace holds no point outside a day
            # rollup, and ingestion cannot produce one. The scan is now unnecessary
            # work forever, so stop doing it.
            remember_day_rollup_coverage(tenant_id)

    # Merge the aggregate state rather than choosing either source wholesale. The
    # weighted average is reconstructed from count and sum, so legacy points and
    # rollup buckets contribute with their real sample weight.
    aggregates: dict[str, dict[str, Any]] = {}
    for row in [*rollup_rows, *raw_rows]:
        count = int(row.count or 0)
        sum_value = row.sum_value
        if sum_value is None and row.avg_value is not None:
            sum_value = float(row.avg_value) * count
        item = aggregates.setdefault(
            row.metric_type,
            {
                "count": 0,
                "sum_value": 0.0,
                "min_value": None,
                "max_value": None,
                "latest_timestamp": None,
            },
        )
        item["count"] += count
        item["sum_value"] += float(sum_value or 0.0)
        if row.min_value is not None:
            item["min_value"] = (
                float(row.min_value)
                if item["min_value"] is None
                else min(item["min_value"], float(row.min_value))
            )
        if row.max_value is not None:
            item["max_value"] = (
                float(row.max_value)
                if item["max_value"] is None
                else max(item["max_value"], float(row.max_value))
            )
        if row.latest_timestamp is not None and (
            item["latest_timestamp"] is None
            or row.latest_timestamp > item["latest_timestamp"]
        ):
            item["latest_timestamp"] = row.latest_timestamp
    custom_rules = await session.execute(
        select(MetricMappingRule).where(
            MetricMappingRule.tenant_id == tenant_id,
            MetricMappingRule.action == "adopt",
        )
    )
    custom_definitions = custom_definitions_from_rules(list(custom_rules.scalars()))

    summary = {}
    for metric_name, aggregate in aggregates.items():
        definition = _definition_payload(metric_name, custom_definitions)
        # Rounding follows the metric rather than a blanket one decimal: a step count
        # with a fractional part is noise, a coordinate rounded to 0.1° is a different
        # town.
        digits = definition["precision"] if definition else 1

        average = (
            aggregate["sum_value"] / aggregate["count"]
            if aggregate["count"]
            else None
        )
        summary[metric_name] = {
            "count": aggregate["count"],
            "average": _round(average, digits),
            "min": _round(aggregate["min_value"], digits),
            "max": _round(aggregate["max_value"], digits),
            # Which of average and total is the meaningful one is a property of the
            # metric (`definition.aggregation`), so both are returned and the caller
            # picks: averaging a day's step counts answers a question nobody asked.
            "sum": _round(aggregate["sum_value"], digits),
            "latest_timestamp": (
                aggregate["latest_timestamp"].isoformat()
                if aggregate["latest_timestamp"]
                else None
            ),
            "definition": definition,
        }

    return {
        "tenant_id": tenant_id,
        "resolution": "day" if rollup_rows else "raw",
        "rollup_available": bool(rollup_rows),
        "contains_legacy_raw": bool(raw_rows),
        "metrics": summary,
    }


@app.get("/api/v1/data/quality/gaps")
async def get_data_gaps(
    start_date: date = Query(...),
    end_date: date = Query(...),
    offset_minutes: int = Query(
        0,
        ge=-16 * 60,
        le=16 * 60,
        description="Reader's UTC offset in minutes; days are bucketed in it",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Detect missing tracking days using only the authenticated tenant's timeline.

    Two questions, because "missing" means two different things. A metric expected
    daily is judged against calendar days; one sampled continuously is judged
    against the rate it actually kept. Metrics that simply happen when they happen
    are not judged at all — see `Cadence`.

    Computed on demand, because the window is a parameter and a caller may ask for
    any of them. The dashboard does not use this: it reads the scheduled run from
    `/api/v1/data/reports/gaps`, which is the same computation over a fixed window
    and costs one indexed row. See `core.reports`.
    """
    tenant_id = get_current_tenant_id()
    if end_date < start_date or (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Date range must contain at most 367 ordered days")

    return await compute_gaps_report(
        session,
        tenant_id,
        start_date=start_date,
        end_date=end_date,
        local_timezone=_window_timezone(offset_minutes),
    )


@app.post("/api/v1/data/import", status_code=202)
async def import_mapped_rows(
    request: BatchImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Persist visually mapped rows with exact-once tenant-scoped semantics."""
    tenant_id = get_current_tenant_id()
    source_ids = {row.source_id for row in request.rows}
    known = await session.execute(
        select(DataSource.id).where(
            DataSource.tenant_id == tenant_id,
            DataSource.deleted_at.is_(None),
            DataSource.id.in_(source_ids),
        )
    )
    if set(known.scalars()) != source_ids:
        raise HTTPException(status_code=400, detail="Every source_id must belong to the authenticated tenant")
    accepted = 0
    for row in request.rows:
        normalized_timestamp = row.timestamp.astimezone(timezone.utc)
        key = idempotency_key(
            tenant_id, row.source_id, row.metric_type, normalized_timestamp
        )
        statement = insert(DataPoint).values(
            id=str(uuid.uuid4()), tenant_id=tenant_id, source_id=row.source_id,
            metric_type=row.metric_type, timestamp=normalized_timestamp, value=row.value,
            metadata_=row.metadata, idempotency_key=key,
        ).on_conflict_do_nothing(
            index_elements=["tenant_id", "idempotency_key", "timestamp"]
        )
        result = await session.execute(statement)
        inserted = (result.rowcount or 0) > 0
        if inserted:
            accepted += 1
            await update_rollups_for_point(
                session,
                tenant_id=tenant_id,
                source_id=row.source_id,
                metric_type=row.metric_type,
                timestamp=normalized_timestamp,
                value=row.value,
                metadata=row.metadata,
            )
    await session.commit()
    return {"tenant_id": tenant_id, "submitted": len(request.rows), "accepted": accepted}


@app.get("/api/v1/data/quality/conflicts")
async def get_cross_source_conflicts(
    tolerance: float = Query(0.05, ge=0, le=1),
    session: AsyncSession = Depends(get_session),
):
    """Return ambiguous same-day values across tenant-owned sources for user review.

    On demand because `tolerance` is a parameter. The dashboard reads the scheduled
    run from `/api/v1/data/reports/conflicts` instead.
    """
    return await compute_conflicts_report(
        session, get_current_tenant_id(), tolerance=tolerance
    )


@app.get("/api/v1/data/day")
async def get_day_story(
    day: date | None = Query(None, description="Calendar day in the reader's zone; default today"),
    offset_minutes: int = Query(
        0,
        ge=-16 * 60,
        le=16 * 60,
        description="Reader's UTC offset in minutes; the day is bounded in it",
    ),
    session: AsyncSession = Depends(get_session),
):
    """One day as a reader experiences it: lanes, a timeline, and how current it is.

    A separate endpoint rather than a client assembling `/api/v1/data/metrics`
    calls, for three reasons the client cannot solve on its own: day rollups are
    bucketed in UTC and that endpoint takes no timezone, so a reader two hours
    east gets a day running 22:00 to 22:00; a whole day would otherwise be one
    unfiltered query sharing a single `limit` between a GPS trace and per-minute
    heart rate, which truncates silently; and the rule deciding which connector
    answers for a metric two of them report existed only over gRPC. See
    `core.daily_story`.
    """
    tenant_id = get_current_tenant_id()
    reader_today = (
        datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    ).date()
    target = day or reader_today
    if target > reader_today:
        raise HTTPException(status_code=400, detail="That day has not happened yet")
    if (reader_today - target).days > 366:
        raise HTTPException(status_code=400, detail="Only the last 367 days can be told")

    return await build_day_story(
        session, tenant_id, day=target, offset_minutes=offset_minutes
    )


@app.get("/api/v1/data/day/track")
async def get_day_track(
    day: date | None = Query(None, description="Calendar day in the reader's zone; default today"),
    offset_minutes: int = Query(
        0,
        ge=-16 * 60,
        le=16 * 60,
        description="Reader's UTC offset in minutes; the day is bounded in it",
    ),
    days: int = Query(
        1,
        ge=1,
        le=31,
        description="How many calendar days back from `day` the track covers, inclusive",
    ),
    track_points: int = Query(
        DEFAULT_DAY_TRACK_POINTS,
        ge=1,
        le=MAX_DAY_TRACK_POINTS,
        description="Most points to return; the span is decimated evenly to fit",
    ),
    session: AsyncSession = Depends(get_session),
):
    """A whole day's movement (or several days'), decimated in the database.

    The overview map used to ask `/api/v1/data/metrics` for `location_point` with
    `limit=1000`. That endpoint sorts ascending and reports no truncation, so a day
    with more fixes than the limit returned the *earliest* thousand and the map drew
    a track that stopped mid-morning — while labelling the count as the day's own.
    A partial track is indistinguishable from a short day, which is the failure mode
    this endpoint exists to remove.

    Every fix is considered and the stride is computed from the true total, so what
    comes back is the shape of the whole day rather than the beginning of it.
    `fix_count` is always the real number and `truncated` says whether the returned
    samples are a subset, so the reader is never told a decimated track is complete.
    """
    tenant_id = get_current_tenant_id()
    reader_today = (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).date()
    target = day or reader_today
    if target > reader_today:
        raise HTTPException(status_code=400, detail="That day has not happened yet")
    if (reader_today - target).days > 366:
        raise HTTPException(status_code=400, detail="Only the last 367 days can be told")

    first = target - timedelta(days=days - 1)
    start = day_window(first, offset_minutes).start
    end = day_window(target, offset_minutes).end
    envelope = {
        "day": target.isoformat(),
        "start_day": first.isoformat(),
        "days": days,
        "offset_minutes": offset_minutes,
    }

    track = await track_for_window(
        session, tenant_id, start, end, route_points=track_points
    )
    if track is None:
        # An explicit empty track, not a 404: "no movement recorded" is an answer
        # about the day, and a client that had to read it from a status code would
        # have to tell it apart from a day that failed to load.
        return {
            **envelope,
            "source": "none",
            "measured_distance_m": None,
            "fix_count": 0,
            "samples": [],
            "sample_count": 0,
            "truncated": False,
        }
    return {**envelope, **track}


# ─── Jobs ───────────────────────────────────────────────────


@app.get("/api/v1/data/jobs")
async def list_background_jobs(
    limit: int = Query(50, ge=1, le=MAX_JOBS),
    since: datetime | None = Query(
        None,
        description="When the reader last looked; anything finished after it is unseen",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Every import and report run this workspace has going on, newest first.

    One list, because the platform's work already lives in two tables and a reader
    could previously only see either by knowing which page to open. A nightly
    analysis that failed at 03:00 was visible nowhere until somebody opened the
    analysis tab and read a sentence about a run timeout.

    A read model over `sync_runs` and `report_runs` — no new table and no second
    lifecycle. A notification that can disagree with the thing it notifies about is
    worse than no notification, because the reader then has two sources and no way
    to tell which is lying.

    `since` is the moment the reader last opened the panel; it is a parameter rather
    than stored state because "have I seen this" belongs to one person's browser,
    not to the workspace — stored, two people sharing a workspace would clear each
    other's notifications.
    """
    tenant_id = get_current_tenant_id()
    return await list_jobs(session, tenant_id, limit=limit, since=since)


# ─── Workouts ───────────────────────────────────────────────


@app.get("/api/v1/data/workouts")
async def list_workouts(
    start_date: date | None = Query(None, description="First calendar day, reader's zone"),
    end_date: date | None = Query(None, description="Last calendar day, reader's zone"),
    offset_minutes: int = Query(
        0,
        ge=-16 * 60,
        le=16 * 60,
        description="Reader's UTC offset in minutes; the range is bounded in it",
    ),
    category: Literal["all", "workout", "strength"] = Query("all"),
    limit: int = Query(50, ge=1, le=MAX_LIST_SESSIONS),
    session: AsyncSession = Depends(get_session),
):
    """Every workout and strength session in a range, newest first.

    A session is a group of points, not a row: see `core.workouts`. The reader's
    offset bounds the range through the same `day_window` the daily story uses,
    because a reader whose day starts at a different moment on two pages of one
    product is being told two different things about one dataset.
    """
    tenant_id = get_current_tenant_id()
    reader_today = (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).date()
    last = end_date or reader_today
    first = start_date or (last - timedelta(days=30))
    if first > last:
        raise HTTPException(status_code=400, detail="start_date is after end_date")
    if (last - first).days > MAX_LIST_DAYS:
        raise HTTPException(
            status_code=400, detail=f"At most {MAX_LIST_DAYS} days can be listed at once"
        )

    return await build_workout_list(
        session,
        tenant_id,
        start_date=first,
        end_date=last,
        offset_minutes=offset_minutes,
        category=category,
        limit=limit,
    )


@app.get("/api/v1/data/workouts/{session_key}")
async def get_workout_detail(
    session_key: str,
    pad_seconds: int = Query(
        DEFAULT_PAD_SECONDS,
        ge=0,
        le=MAX_PAD_SECONDS,
        description="Seconds of slack at each end, for fixes just outside the session",
    ),
    stream_points: int = Query(DEFAULT_STREAM_POINTS, ge=1, le=MAX_STREAM_POINTS),
    route_points: int = Query(DEFAULT_ROUTE_POINTS, ge=1, le=MAX_ROUTE_POINTS),
    session: AsyncSession = Depends(get_session),
):
    """One session, and every reading any connector took while it was happening.

    The key is unsigned on purpose. Every query behind this filters on the tenant
    the Gateway injected (rule 2), so a forged key can only ever address the
    caller's own workspace — which is what makes it uninteresting to forge, and
    what `SessionDetailIsTenantScoped` model-checks.
    """
    tenant_id = get_current_tenant_id()
    try:
        ref = decode_session_key(session_key)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_session_key", "message": "That is not a session key."},
        ) from None

    try:
        return await build_workout_detail(
            session,
            tenant_id,
            ref,
            pad_seconds=pad_seconds,
            stream_points=stream_points,
            route_points=route_points,
        )
    except SessionNotFound:
        raise HTTPException(
            status_code=404,
            detail={"code": "session_not_found", "message": "No such session in this workspace."},
        ) from None


# ─── Precomputed Reports ────────────────────────────────────


def _validated_report_kind(kind: str) -> str:
    if kind not in REPORT_KINDS:
        raise HTTPException(
            status_code=404, detail=f"Unknown report kind. Expected one of: {', '.join(REPORT_KINDS)}"
        )
    return kind


@app.get("/api/v1/data/reports/{kind}")
async def get_report(
    kind: str,
    session: AsyncSession = Depends(get_session),
):
    """The newest completed run of one report, with the time it was computed.

    Never computes. A reader gets the last good answer or an explicit
    ``never_computed``, and in both cases learns whether newer data has arrived
    since — `stale` is a comparison of two timestamps, not a recomputation.
    """
    tenant_id = get_current_tenant_id()
    kind = _validated_report_kind(kind)
    run = await latest_successful_report(session, tenant_id, kind)
    failed = await latest_failed_report(session, tenant_id, kind)
    high_water = await tenant_data_high_water(session, tenant_id)
    # Only expose a failure when it happened after the answer currently served.
    # An old failed attempt is historical noise once a newer run succeeded.
    error = (
        failed
        if failed is not None
        and (
            run is None
            or failed.finished_at is None
            or run.finished_at is None
            or failed.finished_at > run.finished_at
        )
        else None
    )
    payload = report_payload(run, stale=report_is_stale(run, high_water), error=error)
    payload["kind"] = kind
    payload["running"] = await has_in_flight_report(
        session, tenant_id, kind, now=datetime.now(timezone.utc)
    )
    return payload


class RefreshReportRequest(BaseModel):
    """What to compute, when the caller wants something other than the default.

    A window is part of a report's identity, not a filter over it: a 30-day gap
    scan and a 365-day one are different answers, so asking for another window
    asks for another run. Bounded here rather than trusted, because this is the
    one place a reader can size the work a background job will do.
    """

    window_days: int | None = Field(None, ge=1, le=366)
    tolerance: float | None = Field(None, ge=0, le=1)
    offset_minutes: int | None = Field(None, ge=-16 * 60, le=16 * 60)
    days: int | None = Field(None, ge=14, le=365)
    # Restricts the insights bundle to one connector. Not validated against the
    # tenant's connectors here: the Analysis Service reads through Core's
    # tenant-scoped gRPC API, so an identifier from elsewhere returns nothing
    # rather than another workspace's data.
    source_id: str | None = Field(None, max_length=64)
    # Declared, because a field this model does not declare is dropped in
    # silence: the dashboard sent `compare_to_previous`, Pydantic discarded it,
    # and the worker then read `False` from every run — so `period_comparisons`
    # was permanently empty and nothing anywhere reported a problem.
    compare_to_previous: bool | None = None


@app.post("/api/v1/data/reports/{kind}/refresh", status_code=202)
async def refresh_report(
    kind: str,
    req: RefreshReportRequest | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Ask for one report to be recomputed now.

    202 rather than the result: the caller's request is that the work *start*, and
    an insights run is computed by another service entirely. The dashboard polls
    `GET /api/v1/data/reports/{kind}` while `running` is true.

    An already-running report is not queued a second time — the response says so
    and the caller waits for the run that exists, which is what stops a row of
    impatient clicks from becoming a row of identical scans.
    """
    tenant_id = get_current_tenant_id()
    kind = _validated_report_kind(kind)
    now = datetime.now(timezone.utc)
    request_id = get_current_request_id() or str(uuid.uuid4())
    params = resolved_report_params(
        kind,
        {
            key: value
            for key, value in (req.model_dump() if req else {}).items()
            if value is not None
        },
    )

    # Waited on, not tried: a second click must re-check the guard after the first
    # has committed, or both pass it. Same reasoning as `acquire_connector_lock`.
    await acquire_report_lock(session, tenant_id, kind)
    if await has_in_flight_report(session, tenant_id, kind, now=now):
        # What the in-flight run is actually computing. A reader who asked for a
        # 365-day window while a scheduled 30-day run was under way otherwise got
        # `started: false` and no way to see that the answer arriving is not the
        # one they asked for.
        running = (
            await session.execute(
                select(ReportRun)
                .where(
                    ReportRun.tenant_id == tenant_id,
                    ReportRun.kind == kind,
                    ReportRun.status.in_(("queued", "running")),
                )
                .order_by(ReportRun.started_at.desc())
                .limit(1)
            )
        ).scalars().first()
        await session.commit()
        return {
            "kind": kind,
            "status": "already_running",
            "started": False,
            "running_params": (running.params or {}) if running else {},
            "requested_params": params,
        }

    if kind in CORE_COMPUTED_KINDS:
        run = await open_report_run(
            session,
            tenant_id=tenant_id,
            kind=kind,
            trigger="manual",
            request_id=request_id,
            params=params,
        )
        run_id = run.id
        await session.commit()
        # Computed outside the request. Doing it inline would hold this connection
        # for the length of a full scan and give the caller a timeout instead of an
        # acknowledgement; a process that dies mid-computation leaves a run that
        # `expire_stale_report_runs` fails, rather than one that is lost.
        _spawn_background_report(tenant_id, kind, run_id)
        return {"kind": kind, "status": "running", "started": True, "run_id": run_id}

    run = await enqueue_report_run(
        session,
        tenant_id=tenant_id,
        kind=kind,
        trigger="manual",
        request_id=request_id,
        params=params,
    )
    run_id = run.id
    await session.commit()
    return {"kind": kind, "status": "queued", "started": True, "run_id": run_id}


# The event loop keeps only a weak reference to a task, so one with no strong
# reference anywhere can be collected mid-await. For a report that means the run
# sits `running` until `expire_stale_report_runs` fails it half an hour later,
# while the dashboard polls every 2.5 seconds for an answer that is not coming.
_background_reports: set[asyncio.Task[None]] = set()


def _spawn_background_report(tenant_id: str, kind: str, run_id: str) -> None:
    """Start a report computation and keep it alive until it finishes."""
    task = asyncio.create_task(_compute_report_in_background(tenant_id, kind, run_id))
    _background_reports.add(task)
    task.add_done_callback(_background_reports.discard)


async def _compute_report_in_background(tenant_id: str, kind: str, run_id: str) -> None:
    """Finish a run that `refresh_report` opened, in its own session."""
    try:
        async with async_session_maker() as session:
            run = (
                await session.execute(
                    select(ReportRun).where(
                        ReportRun.tenant_id == tenant_id, ReportRun.id == run_id
                    )
                )
            ).scalars().first()
            if run is None:
                return
            try:
                payload = await compute_core_report(
                    session, tenant_id, kind, run.params or {}
                )
            except Exception as exc:
                logger.exception("Manual report %s failed for tenant=%s", kind, tenant_id)
                fail_report_run(run, "report_failed", type(exc).__name__)
            else:
                finish_report_run(run, payload)
            await session.commit()
    except Exception:
        # The run is left in flight and `expire_stale_report_runs` will fail it.
        logger.exception("Background report task for %s could not complete", kind)


@app.get("/api/v1/data/analysis/correlations")
async def get_correlations(session: AsyncSession = Depends(get_session)):
    """Build daily metric correlations for the tenant; Analysis can consume this through Core."""
    tenant_id = get_current_tenant_id()
    rows = await session.execute(
        select(DataPoint.metric_type, DataPoint.timestamp, DataPoint.value).where(
            DataPoint.tenant_id == tenant_id, DataPoint.value.is_not(None)
        ).order_by(DataPoint.timestamp.desc()).limit(10000)
    )
    series: dict[str, dict[str, float]] = {}
    for metric, timestamp, value in rows.all():
        series.setdefault(metric, {})[timestamp.date().isoformat()] = float(value)
    return {"tenant_id": tenant_id, "correlations": pearson_pairs(series)}


# The insights bundle moved to services/analysis. It reads through Core's
# gRPC API rather than the database directly, which is what AGENTS.md rule 3
# asks for and what this endpoint -- living in Core and querying SQL straight
# from the request handler -- did not do. The Gateway routes
# /api/v1/analysis/* there.


# ─── Coverage, Gaps and Import Planning ─────────────────────


def _bucket_fetcher(
    session: AsyncSession,
    tenant_id: str,
    *,
    source_id: str | None = None,
    metric_type: str | None = None,
):
    """Build a tenant-scoped bucket counter for the ingest planner.

    One aggregate query per call, bucketed in SQL. The planner calls this a handful
    of times (once coarse, then a few times while bisecting a boundary) instead of
    reading individual points, which is the whole point of the coarse-to-fine
    approach.
    """

    async def fetch(start: datetime, end: datetime, bucket_seconds: int):
        seconds = max(1, int(bucket_seconds))
        bucket_expr = func.to_timestamp(
            func.floor(func.extract("epoch", DataPoint.timestamp) / seconds) * seconds
        ).label("bucket")

        stmt = (
            select(bucket_expr, func.count().label("n"))
            .where(
                DataPoint.tenant_id == tenant_id,
                DataPoint.timestamp >= start,
                DataPoint.timestamp < end,
            )
            .group_by(bucket_expr)
            .order_by(bucket_expr)
        )
        if source_id:
            stmt = stmt.where(DataPoint.source_id == source_id)
        if metric_type:
            stmt = stmt.where(DataPoint.metric_type == metric_type)

        rows = (await session.execute(stmt)).all()
        counts: dict[datetime, int] = {}
        for bucket_start, n in rows:
            if bucket_start.tzinfo is None:
                bucket_start = bucket_start.replace(tzinfo=timezone.utc)
            counts[bucket_start] = int(n)

        # Emit a dense series so the planner sees empty buckets as empty rather
        # than as absent.
        buckets: list[BucketCount] = []
        cursor = start
        step = timedelta(seconds=seconds)
        while cursor < end:
            bucket_end = min(cursor + step, end)
            total = sum(v for k, v in counts.items() if cursor <= k < bucket_end)
            buckets.append(BucketCount(start=cursor, end=bucket_end, count=total))
            cursor = bucket_end
        return buckets

    return fetch


async def _resolve_source(
    session: AsyncSession,
    tenant_id: str,
    source_type: str | None = None,
    *,
    source_id: str | None = None,
) -> DataSource | None:
    """The connector a request is about, addressed by instance or by type.

    `source_id` is the precise form and the one the dashboard uses. Addressing by
    type is kept for the callers that still speak that way, but it is only
    meaningful while a tenant holds one connector of the type — with two, it
    resolves to whichever the database returns first, so it is ordered by creation
    to at least be *stable* rather than arbitrary.
    """
    query = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.deleted_at.is_(None),
    )
    if source_id is not None:
        query = query.where(DataSource.id == source_id)
    if source_type is not None:
        query = query.where(DataSource.source_type == source_type)
    res = await session.execute(query.order_by(DataSource.created_at, DataSource.id))
    return res.scalars().first()


def _window_timezone(offset_minutes: int) -> timezone:
    """The reader's zone as a fixed offset.

    An offset rather than a zone name because that is what a browser can state
    without ambiguity, and because a gap window is short enough that a DST change
    inside it moves one boundary by an hour rather than corrupting the answer.
    """
    return timezone(timedelta(minutes=offset_minutes))


def _typical_duration_seconds(runs: Sequence[SyncRun]) -> float | None:
    """How long this connector's finished imports usually take, or ``None``.

    The median of what actually happened, not an estimate of what should: a mean
    would let one stuck six-hour run dominate the answer forever. ``None`` when
    there is nothing to go on, so the interface can stay silent rather than invent
    a number for a connector that has never run.
    """
    durations = [
        (run.finished_at - run.started_at).total_seconds()
        for run in runs
        if run.finished_at is not None
        and run.started_at is not None
        and run.status == "success"
        and run.finished_at >= run.started_at
    ]
    return round(median(durations), 1) if durations else None


def _run_duration_seconds(run: SyncRun, *, now: datetime | None = None) -> float | None:
    """Return the elapsed time for a run, including the live time of an open run."""
    if run.started_at is None:
        return None
    finished_at = run.finished_at or now or datetime.now(timezone.utc)
    started_at = run.started_at
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=timezone.utc)
    if finished_at < started_at:
        return None
    return round((finished_at - started_at).total_seconds(), 1)


def _sync_run_payload(
    run: SyncRun,
    *,
    connector_name: str | None = None,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    """Serialize the run shape, exposing operator diagnostics only by role."""
    return {
        "id": run.id,
        "request_id": run.request_id if include_diagnostics else None,
        "source_id": run.source_id,
        "source_type": run.source_type,
        "connector_name": connector_name,
        "mode": run.mode,
        "trigger": run.trigger,
        "status": run.status,
        "window_start": run.window_start.isoformat() if run.window_start else None,
        "window_end": run.window_end.isoformat() if run.window_end else None,
        "window_reason": _display_window_reason(run.window_reason),
        "points_expected": run.points_expected,
        "points_received": run.points_received,
        "points_processed": run.points_processed,
        "points_accepted": run.points_accepted,
        "points_duplicate": run.points_duplicate,
        "points_rejected": run.points_rejected,
        "unsupported_fields": run.unsupported_fields,
        "provider_window_start": run.provider_window_start.isoformat() if run.provider_window_start else None,
        "provider_window_end": run.provider_window_end.isoformat() if run.provider_window_end else None,
        "provider_exported_at": run.provider_exported_at.isoformat() if run.provider_exported_at else None,
        "backlog_at_start": run.backlog_at_start,
        "backlog_at_end": run.backlog_at_end,
        "skipped_ranges": run.skipped_ranges,
        "message": run.message if include_diagnostics else None,
        "message_code": run.message_code,
        "message_params": run.message_params or {},
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": _run_duration_seconds(run),
    }


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


async def _resolve_source_ref(
    session: AsyncSession, tenant_id: str, ref: str
) -> DataSource | None:
    """Resolve a path segment that names either a connector instance or a type.

    One route rather than two. No `source_type` is a UUID, so the two forms cannot
    collide, and importers that still address their own type keep working while the
    dashboard addresses the exact instance the user clicked.
    """
    if _looks_like_uuid(ref):
        return await _resolve_source(session, tenant_id, source_id=ref)
    return await _resolve_source(session, tenant_id, ref)


_COVERAGE_MARKER_PREFIX = "[coverage-contract:"
_COVERAGE_MARKER_SUFFIX = "]"


def _configured_supported_metrics(
    config: dict[str, Any] | None,
) -> tuple[str, ...] | None:
    """Return the canonical metric manifest configured for a connector.

    A missing or malformed manifest is intentionally represented as ``None``. Core
    must not guess that all metrics are covered from a connector-wide point count.
    """
    config = config or {}
    values = [
        config[key]
        for key in ("supported_metrics", "supported_metric_types")
        if key in config
    ]
    if not values or any(value != values[0] for value in values[1:]):
        return None

    raw_metrics = values[0]
    if not isinstance(raw_metrics, (list, tuple, set)) or not raw_metrics:
        return None

    canonical: set[str] = set()
    for raw_metric in raw_metrics:
        if not isinstance(raw_metric, str):
            return None
        try:
            canonical.add(canonical_metric_type(raw_metric))
        except UnknownMetricTypeError:
            return None
    return tuple(sorted(canonical)) or None


def _configured_coverage_version(
    config: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> str | None:
    """Read the first configured schema/transform version as a stable string."""
    config = config or {}
    for key in keys:
        if key not in config:
            continue
        value = config[key]
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return str(value)
        return None
    return None


def _source_coverage_contract(source: DataSource) -> tuple[tuple[str, ...], str] | None:
    """Build the source/metric/schema contract used to trust historical coverage."""
    config = source.config or {}
    metrics = _configured_supported_metrics(config)
    manifest_is_configured = any(
        key in config for key in ("supported_metrics", "supported_metric_types")
    )
    if metrics is None and not manifest_is_configured:
        # Static providers already have an exact metric ownership list in the shared
        # registry. Using it as the built-in manifest makes the safe planner useful
        # for existing connectors created before the manifest field was introduced.
        # Dynamic providers are intentionally excluded: their user's installation
        # determines which fields exist, so a catalog list cannot prove completeness.
        has_dynamic_namespace = any(
            source.source_type in namespace.sources for namespace in DYNAMIC_NAMESPACES
        )
        registry_metrics = tuple(sorted(d.key for d in metrics_for_source(source.source_type)))
        if has_dynamic_namespace or not registry_metrics:
            return None
        metrics = registry_metrics
        manifest_source = "registry"
    elif metrics is not None:
        manifest_source = "configured"
    else:
        # A malformed explicit manifest must not silently fall back to a broader
        # registry assumption. Keep the conservative full-window behavior.
        return None

    contract = {
        "source_id": source.id,
        "source_type": source.source_type,
        "supported_metrics": metrics,
        "manifest_source": manifest_source,
        "schema_version": _configured_coverage_version(
            config, ("schema_version", "provider_schema_version")
        )
        or "registry-v1",
        "transform_version": _configured_coverage_version(
            config, ("transform_version", "importer_transform_version")
        ),
        "contract_version": 1,
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()
    return metrics, hashlib.sha256(encoded).hexdigest()


def _coverage_marker(signature: str) -> str:
    """Return the durable machine marker kept at the start of ``window_reason``."""
    return f"{_COVERAGE_MARKER_PREFIX}{signature}{_COVERAGE_MARKER_SUFFIX}"


def _coverage_signature_from_reason(reason: str | None) -> str | None:
    """Extract a coverage contract marker without relying on human wording."""
    if not reason or not reason.startswith(_COVERAGE_MARKER_PREFIX):
        return None
    end = reason.find(_COVERAGE_MARKER_SUFFIX, len(_COVERAGE_MARKER_PREFIX))
    if end < 0:
        return None
    return reason[len(_COVERAGE_MARKER_PREFIX) : end]


def _with_coverage_marker(reason: str, signature: str | None) -> str:
    """Prefix a run reason with its contract while keeping the existing text."""
    if not signature:
        return reason
    return f"{_coverage_marker(signature)} {reason}".strip()


def _display_window_reason(reason: str | None) -> str | None:
    """Remove the internal contract marker from user-facing sync history."""
    if reason is None:
        return None
    if not reason.startswith(_COVERAGE_MARKER_PREFIX):
        return reason
    end = reason.find(_COVERAGE_MARKER_SUFFIX, len(_COVERAGE_MARKER_PREFIX))
    if end < 0:
        return reason
    return reason[end + 1 :].lstrip() or None


async def _coverage_contract_is_current(
    session: AsyncSession,
    tenant_id: str,
    source_id: str,
    signature: str | None,
) -> bool:
    """Whether the latest successful run used the current coverage contract.

    A connector with no successful history is allowed to use its configured metric
    manifest. Once history exists, an unmarked or different contract invalidates
    smart skipping until a run under the current contract succeeds.
    """
    if not signature:
        return False
    result = await session.execute(
        select(SyncRun.id, SyncRun.window_reason)
        .where(
            SyncRun.tenant_id == tenant_id,
            SyncRun.source_id == source_id,
            SyncRun.status == "success",
        )
        .order_by(SyncRun.finished_at.desc(), SyncRun.id.desc())
        .limit(1)
    )
    row = result.first()
    if row is None:
        return True
    return _coverage_signature_from_reason(row.window_reason) == signature


async def _source_coverage_plan(
    session: AsyncSession,
    tenant_id: str,
    source: DataSource,
) -> tuple[dict[str, Any], str | None, str, str | None]:
    """Return metric fetchers, contract signature, scope and an optional reason."""
    contract = _source_coverage_contract(source)
    if contract is None:
        return (
            {},
            None,
            "unknown",
            (
                "The connector has no valid canonical metric manifest. The full requested "
                "period will be imported conservatively."
            ),
        )

    metrics, signature = contract
    fetchers = {
        metric: _bucket_fetcher(
            session,
            tenant_id,
            source_id=source.id,
            metric_type=metric,
        )
        for metric in metrics
    }
    if not await _coverage_contract_is_current(
        session, tenant_id, source.id, signature
    ):
        return (
            fetchers,
            signature,
            "unknown",
            (
                "The connector's supported metrics or transformation contract changed. "
                "The full requested period will be imported to revalidate coverage."
            ),
        )
    return fetchers, signature, "metric_set", None


async def _last_successful_sync_end(
    session: AsyncSession,
    tenant_id: str,
    source_id: str,
    *,
    coverage_signature: str | None = None,
    require_coverage_contract: bool = False,
) -> datetime | None:
    """Return the last provider-confirmed coverage end for adaptive resumption.

    Keyed on the instance, not the type: with two calendars, the type would let
    one connector's successful window advance the other's resume point, and the
    second calendar would silently skip everything the first had already fetched.
    A requested window end is deliberately not used as a watermark. Providers can
    return a shorter range than requested, and advancing from the request alone can
    create a permanent gap after the overlap expires.
    """
    if require_coverage_contract and not coverage_signature:
        return None

    res = await session.execute(
        select(SyncRun.provider_window_end, SyncRun.window_reason)
        .where(
            SyncRun.tenant_id == tenant_id,
            SyncRun.source_id == source_id,
            SyncRun.status == "success",
            SyncRun.provider_window_end.is_not(None),
        )
        .order_by(SyncRun.provider_window_end.desc())
    )
    value: datetime | None = None
    for provider_end, window_reason in res.all():
        if coverage_signature is not None and (
            _coverage_signature_from_reason(window_reason) != coverage_signature
        ):
            continue
        value = provider_end
        break
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


#: Open-Meteo's place-name lookup. Configurable so a self-hosted deployment can
#: point it elsewhere, and so a test never reaches the network.
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"


@app.get("/api/v1/data/geocode")
async def geocode_place(
    query: str = Query(..., min_length=2, max_length=120, description="Place name to look up"),
):
    """Resolve a place name to coordinates, for configuring a weather connector.

    Proxied rather than called from the browser for two reasons. The dashboard
    ships a `connect-src` allowlist (`apps/dashboard/next.config.ts`), and widening
    it for a convenience feature would permit that origin for every script on the
    page. And a direct call would hand the user's IP address and the name of the
    place they live to a third party — the very thing this platform exists to keep
    in one place.

    Answers in English with a stable shape (rule 17): the dashboard formats it.
    """
    tenant_id = get_current_tenant_id()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                GEOCODING_URL,
                params={"name": query, "count": 5, "format": "json"},
                headers={"Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        logger.warning(
            "[tenant=%s] Geocoding provider unreachable: %s", tenant_id, type(exc).__name__
        )
        raise HTTPException(
            status_code=502, detail="The place-name service could not be reached."
        ) from None

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"The place-name service returned HTTP {response.status_code}.",
        )

    payload = response.json() if response.content else {}
    results = payload.get("results") or []
    return {
        "query": query,
        "results": [
            {
                "name": entry.get("name"),
                "country": entry.get("country"),
                "admin1": entry.get("admin1"),
                "latitude": entry.get("latitude"),
                "longitude": entry.get("longitude"),
            }
            for entry in results
            if isinstance(entry, dict)
            and entry.get("latitude") is not None
            and entry.get("longitude") is not None
        ],
    }


@app.get("/api/v1/data/coverage")
async def get_coverage(
    start: datetime = Query(..., description="Window start (ISO 8601)"),
    end: datetime = Query(..., description="Window end (ISO 8601)"),
    source_type: str | None = Query(None),
    metric_type: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """Report which parts of a window the tenant already has data for."""
    tenant_id = get_current_tenant_id()
    window = _validated_window(start, end)

    source: DataSource | None = None
    source_id = None
    if source_type:
        source = await _resolve_source(session, tenant_id, source_type)
        if not source:
            raise HTTPException(status_code=404, detail="Connector not configured")
        source_id = source.id

    canonical_metric = None
    if metric_type:
        try:
            canonical_metric = canonical_metric_type(metric_type)
        except UnknownMetricTypeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    coverage_reason: str | None = None
    coverage_metrics: list[str] = []
    if canonical_metric:
        fetch = _bucket_fetcher(
            session,
            tenant_id,
            source_id=source_id,
            metric_type=canonical_metric,
        )
        covered, missing, confidence, expectation, total = await analyse_coverage(
            fetch, window
        )
        coverage_scope = "single_metric"
        coverage_metrics = [canonical_metric]
    elif source is not None:
        fetchers, _signature, coverage_scope, coverage_reason = await _source_coverage_plan(
            session, tenant_id, source
        )
        if coverage_scope == "metric_set":
            covered, missing, confidence, expectation, total = await analyse_metric_coverage(
                fetchers, window
            )
            coverage_metrics = sorted(fetchers)
        else:
            covered, missing, confidence, expectation, total = (
                [],
                [window],
                "low",
                None,
                0,
            )
    else:
        covered, missing, confidence, expectation, total = (
            [],
            [window],
            "low",
            None,
            0,
        )
        coverage_scope = "unknown"
        coverage_reason = (
            "A source and canonical metric were not specified. Coverage cannot be "
            "evaluated safely across all connectors."
        )

    return {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "metric_type": canonical_metric,
        "window": window.to_dict(),
        "covered_ranges": [r.to_dict() for r in covered],
        "missing_ranges": [r.to_dict() for r in missing],
        "confidence": confidence,
        "expected_points_per_bucket": expectation or None,
        "total_points": total,
        "coverage_scope": coverage_scope,
        "coverage_metrics": coverage_metrics,
        "coverage_reason": coverage_reason,
    }


class ImportPlanRequest(BaseModel):
    start: datetime | None = Field(None, description="Requested window start")
    end: datetime | None = Field(None, description="Requested window end")
    metric_type: str | None = Field(
        None,
        description=(
            "Canonical metric whose coverage may be used for smart skipping. "
            "Omit to force a conservative full-window import."
        ),
    )
    mode: Literal["smart", "force"] = Field("smart", description="Smart skips known-complete ranges")


@app.post("/api/v1/data/sources/{source_ref}/import-plan")
async def get_import_plan(
    source_ref: str,
    req: ImportPlanRequest,
    session: AsyncSession = Depends(get_session),
):
    """Explain what a sync would actually do, without running it.

    The dashboard calls this to prefill the import dialog and to show the user which
    ranges will be skipped and why.
    """
    tenant_id = get_current_tenant_id()
    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    config = source.config or {}
    now = datetime.now(timezone.utc)

    canonical_metric = None
    if req.metric_type:
        try:
            canonical_metric = canonical_metric_type(req.metric_type)
        except UnknownMetricTypeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    (
        configured_fetchers,
        configured_signature,
        configured_scope,
        configured_reason,
    ) = await _source_coverage_plan(session, tenant_id, source)
    # Keep a changed manifest/transform contract visible even when the user asks
    # for one metric explicitly. A stale provider watermark must not advance the
    # new contract; the planner will conservatively revalidate it.
    coverage_signature = configured_signature

    if req.start and req.end:
        window = _validated_window(req.start, req.end)
        window_reason = "Period chosen by the user."
    else:
        window, window_reason = compute_sync_window(
            now=now,
            poll_interval_hours=float(config.get("poll_interval_hours", 6)),
            lookback_days=int(config.get("lookback_days", 7)),
            lookback_hours=_configured_lookback_hours(config),
            last_success_end=await _last_successful_sync_end(
                session,
                tenant_id,
                source.id,
                coverage_signature=coverage_signature,
                require_coverage_contract=coverage_signature is not None,
            ),
        )

    coverage_scope = "single_metric" if canonical_metric else configured_scope
    metric_fetchers = None if canonical_metric else configured_fetchers
    coverage_reason = None if canonical_metric else configured_reason
    fetch = _bucket_fetcher(
        session,
        tenant_id,
        source_id=source.id,
        metric_type=canonical_metric,
    )
    plan = await plan_import(
        fetch,
        window,
        mode=req.mode,
        metric_type=canonical_metric,
        require_metric_scope=False,
        metric_fetchers=metric_fetchers,
        coverage_scope=coverage_scope,
        coverage_reason=coverage_reason,
    )

    payload = plan.to_dict()
    payload["window_reason"] = window_reason
    payload["tenant_id"] = tenant_id
    payload["source_id"] = source.id
    payload["source_type"] = source.source_type
    payload["metric_type"] = canonical_metric
    payload["docs_url"] = "/docs/features/smart-import/"
    return payload


@app.get("/api/v1/data/sources/{source_ref}/sync-runs")
async def list_sync_runs(
    source_ref: str,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
):
    """Import history for one connector, newest first.

    Filtered by connector id. Filtered by type, a tenant's two calendars would
    share one interleaved history with nothing to tell the rows apart.
    """
    tenant_id = get_current_tenant_id()
    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    res = await session.execute(
        select(SyncRun)
        .where(SyncRun.tenant_id == tenant_id, SyncRun.source_id == source.id)
        .order_by(SyncRun.started_at.desc())
        .offset(offset)
        .limit(limit)
    )
    runs = res.scalars().all()

    return {
        "tenant_id": tenant_id,
        "source_id": source.id,
        "source_type": source.source_type,
        # How long this connector usually takes, from its own finished runs. An
        # estimate about *this* connector rather than a guess: before it has ever
        # run there is simply nothing here, and the interface says nothing.
        "typical_duration_seconds": _typical_duration_seconds(runs),
        "offset": offset,
        "limit": limit,
        "has_more": len(runs) == limit,
        "runs": [
            _sync_run_payload(
                run,
                connector_name=source.display_name,
                include_diagnostics=principal.kind == "user"
                and principal.role in {"owner", "admin"},
            )
            for run in runs
        ],
    }


@app.get("/api/v1/data/sync-runs")
async def list_all_sync_runs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    status: str | None = Query(None, min_length=1, max_length=32),
    source_type: str | None = Query(None, min_length=1, max_length=64),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_session),
):
    """List the tenant's import runs across all connector instances."""
    tenant_id = get_current_tenant_id()
    query = (
        select(SyncRun, DataSource.display_name)
        .outerjoin(
            DataSource,
            and_(
                DataSource.id == SyncRun.source_id,
                DataSource.tenant_id == tenant_id,
            ),
        )
        .where(SyncRun.tenant_id == tenant_id)
    )
    if status:
        query = query.where(SyncRun.status == status)
    if source_type:
        query = query.where(SyncRun.source_type == source_type)
    query = query.order_by(SyncRun.started_at.desc()).offset(offset).limit(limit)

    rows = (await session.execute(query)).all()
    runs = [
        _sync_run_payload(
            run,
            connector_name=connector_name,
            include_diagnostics=principal.kind == "user"
            and principal.role in {"owner", "admin"},
        )
        for run, connector_name in rows
    ]
    return {
        "tenant_id": tenant_id,
        "offset": offset,
        "limit": limit,
        "has_more": len(runs) == limit,
        "runs": runs,
    }


def _validated_window(start: datetime, end: datetime) -> TimeRange:
    """Reject inverted or absurdly large windows before touching the database."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise HTTPException(status_code=400, detail="end must be after start")
    if (end - start).days > 3660:
        raise HTTPException(status_code=400, detail="Window must span at most 10 years")
    return TimeRange(start, end)


# ─── Connector Configuration Endpoints ──────────────────────

class WeatherConnectorConfig(BaseModel):
    """The parts of a weather connector's `config` the importer actually reads.

    Everywhere else `config` is an untyped blob, and for weather that was the bug:
    the connector could be saved with no coordinates at all, because nothing on
    the way in looked, and the importer then failed with a message naming fields
    the form had never offered. Validating here turns a silent misconfiguration
    into a 422 at the moment it is made.

    `extra="allow"` on purpose -- Core's own bookkeeping keys (`status`,
    `last_sync_at`, …) are merged into the same dictionary and must survive.
    """

    model_config = ConfigDict(extra="allow")

    # Optional only because the expert mode supplies a complete `request_url`
    # instead, which already carries the location in its query.
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    base_url: str | None = None
    request_url: str | None = None
    hourly_variables: list[str] | None = None

    @field_validator("base_url", "request_url")
    @classmethod
    def _absolute_http_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        candidate = v.strip()
        if not candidate:
            return None
        if not candidate.lower().startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return candidate

    @model_validator(mode="after")
    def _location_or_request_url(self) -> "WeatherConnectorConfig":
        """One of the two modes has to be complete.

        Without this the connector saves happily and then fails in the importer
        with a message naming fields the form never showed — which is exactly how
        weather came to be unconfigurable in the first place.
        """
        if self.request_url:
            return self
        if self.latitude is None or self.longitude is None:
            raise ValueError("latitude and longitude are required unless request_url is given")
        return self


class CalendarConnectorConfig(BaseModel):
    """A calendar is its feed URL, and nothing else is required.

    Until the API mode was removed, a calendar without a URL was refused by the
    credential check as a side effect. Making the credential unconditionally
    optional removed that guard, so the requirement is stated here instead —
    where it belongs, because a URL is configuration and not a credential.
    """

    model_config = ConfigDict(extra="allow")

    ics_url: str | None = None
    base_url: str | None = None

    @model_validator(mode="after")
    def _needs_a_feed_url(self) -> "CalendarConnectorConfig":
        url = (self.ics_url or self.base_url or "").strip()
        if not url:
            raise ValueError("a calendar feed URL is required")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("the calendar URL must start with http:// or https://")
        return self


#: Per-source-type validation for the otherwise free-form `config` blob. A type
#: absent from here keeps the old behaviour, which is "anything goes".
CONNECTOR_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "weather": WeatherConnectorConfig,
    "calendar": CalendarConnectorConfig,
}


def _validate_connector_config(source_type: str, config: dict[str, Any]) -> None:
    """Reject a connector whose stored configuration could not work.

    Checked against the *merged* result rather than the request, so editing only
    the poll interval stays legal while the state that gets written is always one
    the importer can act on.
    """
    # `import_mode` is not part of any provider's config model, because it says how
    # the connector is fed rather than how to reach the provider. Checked here so a
    # value that means nothing cannot be stored: it decides whether a credential is
    # required and whether the scheduler ever looks at this row.
    import_mode = config.get("import_mode")
    if import_mode is not None:
        if import_mode != IMPORT_MODE_FILE:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown import_mode '{import_mode}'. The only file-fed mode is 'file'.",
            )
        if not supports_file_import(source_type):
            raise HTTPException(
                status_code=422,
                detail=f"{source_type} has no export file this platform can read.",
            )

    model = CONNECTOR_CONFIG_MODELS.get(source_type)
    if model is None:
        return
    try:
        model.model_validate(config)
    except ValidationError as exc:
        # Field *and* reason. A whole-model rule (such as "latitude and longitude
        # are required unless request_url is given") has an empty `loc`, so naming
        # only the field produced the useless "configuration: config".
        problems = []
        for error in exc.errors():
            where = ".".join(str(part) for part in error["loc"])
            message = error.get("msg", "is invalid")
            problems.append(f"{where}: {message}" if where else message)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {source_type} connector configuration — {'; '.join(problems)}",
        ) from None


class ConfigureConnectorRequest(BaseModel):
    source_type: ValidSourceType = Field(..., description="Connector provider: oura, whoop, apple_health, fitbit, yazio")
    # Which instance to update. Absent means "create a new one" -- a tenant may
    # hold several connectors of the same type, so the type alone no longer
    # identifies a row. Editing used to overwrite whichever one existed.
    source_id: str | None = Field(None, description="Existing connector to update")
    # What the user calls this instance. Required on create, because "which of my
    # three calendars is this?" has no answer the system could invent; optional on
    # update, where leaving it out keeps the current name.
    display_name: str | None = Field(None, min_length=1, max_length=128)
    # SECURITY H6: Optional access_token to allow editing frequency without re-entering token
    access_token: str | None = Field(None, description="Raw API access token / credential", max_length=2048)
    status: ValidStatus = Field("active", description="active / inactive")
    poll_interval_hours: int = Field(6, ge=1, le=168, description="Poll frequency in hours")
    lookback_days: int = Field(7, ge=1, le=365, description="Lookback window in days")
    lookback_hours: int | None = Field(
        None, ge=1, le=365 * 24, description="Lookback window in hours; takes precedence over days"
    )
    config: dict[str, Any] | None = Field(None, description="Custom configuration for the connector")

    # The OAuth refresh grant, for providers whose access token is short-lived.
    # WHOOP's lasts about an hour against a six-hour poll interval, so without
    # these the connector works once and then needs a token pasted in by hand
    # again. All three are required together -- a refresh token with no client
    # credentials cannot be exchanged for anything.
    refresh_token: str | None = Field(
        None, description="OAuth refresh token, stored encrypted", max_length=2048
    )
    client_id: str | None = Field(None, max_length=256)
    client_secret: str | None = Field(
        None, description="OAuth client secret, stored encrypted", max_length=512
    )
    expires_in: int | None = Field(
        None, ge=1, le=60 * 60 * 24 * 365, description="Access token lifetime in seconds"
    )


@app.post("/api/v1/data/sources/configure")
async def configure_connector(
    req: ConfigureConnectorRequest,
    session: AsyncSession = Depends(get_session),
):
    """Safely configure or edit a connector for the tenant.

    Encrypts raw access tokens with Fernet symmetric AES before database persistence.
    If access_token is omitted when editing an existing connector, preserves existing encrypted credentials.
    """
    tenant_id = get_current_tenant_id()
    raw_token = (req.access_token or "").strip()

    t_stmt = select(Tenant).where(Tenant.id == tenant_id)
    t_res = await session.execute(t_stmt)
    if not t_res.scalar_one_or_none():
        session.add(Tenant(id=tenant_id, name="Default Workspace"))
        await session.flush()

    # Which instance is being edited, if any. Without an explicit `source_id` this
    # is a *create*: a tenant may hold several connectors of the same type, so the
    # type alone no longer names a row, and assuming it did is what made a second
    # calendar overwrite the first.
    existing: DataSource | None = None
    if req.source_id:
        existing = await _resolve_source(session, tenant_id, source_id=req.source_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Connector not found")
        if existing.source_type != req.source_type:
            raise HTTPException(
                status_code=400, detail="source_type does not match the connector being edited"
            )
    elif not (req.display_name or "").strip():
        # `.strip()` because `min_length=1` counts characters, and three spaces is
        # three characters that name nothing.
        raise HTTPException(
            status_code=422,
            detail="display_name is required when creating a connector",
        )

    if req.source_type == "yazio" and req.config and "yazio_email" in req.config and "yazio_password" in req.config and req.config["yazio_email"] and req.config["yazio_password"]:
        email = req.config["yazio_email"]
        password = req.config["yazio_password"]
        base_url = os.getenv("YAZIO_API_BASE_URL", "https://yzapi.yazio.com").rstrip("/")
        oauth_url = f"{base_url}/v15/oauth/token"
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    oauth_url,
                    data={
                        # Yazio's own mobile-app OAuth client, not a secret of
                        # ours: it ships inside a published app and we could not
                        # rotate it. It was hardcoded here *and* in the importer;
                        # the importer's copy moved to configuration and this one
                        # was missed, which is exactly why a second copy of a
                        # credential-shaped string is worth removing.
                        "client_id": settings.YAZIO_CLIENT_ID,
                        "client_secret": settings.YAZIO_CLIENT_SECRET,
                        "grant_type": "password",
                        "username": email,
                        "password": password,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 401:
                    raise HTTPException(status_code=401, detail="Yazio sign-in failed: wrong email address or password.")
                if not resp.is_success:
                    logger.warning(
                        "Yazio sign-in failed with HTTP %s", resp.status_code
                    )
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=f"Yazio sign-in failed (HTTP {resp.status_code}).",
                    )
                token_data = resp.json()
                raw_token = token_data.get("access_token", "")
                if not raw_token:
                    raise HTTPException(status_code=400, detail="The Yazio OAuth response contained no access_token.")
            except HTTPException:
                raise
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
                logger.warning(
                    "Yazio OAuth connection failed with %s",
                    type(exc).__name__,
                )
                raise HTTPException(
                    status_code=502,
                    detail="Yazio OAuth connection failed.",
                ) from None

    config_data: dict[str, Any] = {
        "status": req.status,
        "poll_interval_hours": req.poll_interval_hours,
        "lookback_days": math.ceil(
            (req.lookback_hours or req.lookback_days * 24) / 24
        ),
        "lookback_hours": req.lookback_hours or req.lookback_days * 24,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Against the configuration that will be *stored*, not against the request
    # alone: a file-import connector holds no provider credential, and the field
    # that says so arrives in `config`, which is merged further down.
    intended_config = dict((existing.config if existing else None) or {})
    intended_config.update(req.config or {})
    credential_optional = credential_is_optional(req.source_type, intended_config)

    if raw_token:
        encrypted_token = encrypt_secret(raw_token)
        masked_token = mask_secret(raw_token)
        config_data["encrypted_token"] = encrypted_token
        config_data["masked_token"] = masked_token
    elif existing and existing.config and "encrypted_token" in existing.config:
        config_data["encrypted_token"] = existing.config["encrypted_token"]
        config_data["masked_token"] = existing.config.get("masked_token", "••••••••")
    elif credential_optional:
        config_data["masked_token"] = "—"
    else:
        raise HTTPException(
            status_code=400,
            detail="Credentials or an access token are required for the initial setup."
        )

    # OAuth refresh grant. Encrypted at rest like the access token, and carried
    # over when the user edits the connector without re-entering it -- otherwise
    # changing the poll interval would silently strip the connector's ability to
    # refresh and it would die at the next expiry.
    if req.refresh_token:
        config_data["encrypted_refresh_token"] = encrypt_secret(req.refresh_token.strip())
    elif existing and existing.config and "encrypted_refresh_token" in existing.config:
        config_data["encrypted_refresh_token"] = existing.config["encrypted_refresh_token"]

    if req.client_secret:
        config_data["encrypted_client_secret"] = encrypt_secret(req.client_secret.strip())
    elif existing and existing.config and "encrypted_client_secret" in existing.config:
        config_data["encrypted_client_secret"] = existing.config["encrypted_client_secret"]

    if req.client_id:
        config_data["client_id"] = req.client_id.strip()
    elif existing and existing.config and existing.config.get("client_id"):
        config_data["client_id"] = existing.config["client_id"]

    if req.expires_in:
        config_data["token_expires_at"] = (
            datetime.now(timezone.utc) + timedelta(seconds=req.expires_in)
        ).isoformat()
    elif (
        not raw_token
        and existing
        and existing.config
        and existing.config.get("token_expires_at")
    ):
        # Keep the recorded expiry only if the access token itself was kept. A new
        # token with an old expiry would be refreshed immediately, or worse,
        # treated as valid long after it died.
        config_data["token_expires_at"] = existing.config["token_expires_at"]

    if req.config:
        clean_config = {
            k: v
            for k, v in req.config.items()
            # Never let a client write the encrypted fields directly; they are
            # derived above from the plaintext inputs.
            if k
            not in (
                "yazio_email",
                "yazio_password",
                "encrypted_token",
                "encrypted_refresh_token",
                "encrypted_client_secret",
            )
        }
        config_data.update(clean_config)
        if req.lookback_hours is None:
            configured_hours = clean_config.get("lookback_hours")
            if configured_hours is None and "lookback_days" in clean_config:
                try:
                    configured_hours = math.ceil(float(clean_config["lookback_days"]) * 24)
                except (TypeError, ValueError):
                    configured_hours = None
            if configured_hours is not None:
                try:
                    config_data["lookback_hours"] = max(1, math.ceil(float(configured_hours)))
                except (TypeError, ValueError):
                    pass
    if req.lookback_hours is not None:
        # The typed top-level field is authoritative when both the legacy nested
        # setting and the new sub-day setting are supplied.
        config_data["lookback_hours"] = req.lookback_hours
        config_data["lookback_days"] = math.ceil(req.lookback_hours / 24)

    if existing:
        merged_config = dict(existing.config or {})
        merged_config.update(config_data)
        _validate_connector_config(req.source_type, merged_config)
        existing.config = merged_config
        if (req.display_name or "").strip():
            existing.display_name = req.display_name.strip()
        source_id = existing.id
        display_name = existing.display_name
    else:
        _validate_connector_config(req.source_type, config_data)
        source_id = str(uuid.uuid4())
        display_name = (req.display_name or "").strip()
        new_source = DataSource(
            id=source_id,
            tenant_id=tenant_id,
            source_type=req.source_type,
            display_name=display_name,
            config=config_data,
        )
        session.add(new_source)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="A connector of this type already uses that name.",
        ) from None

    req_id = str(uuid.uuid4())
    payload = json.dumps({
        "tenant_id": tenant_id,
        # The importer needs to know *which* instance it was asked to sync: it is
        # what the credential lookup keys on and what every idempotency key it
        # derives is built from.
        "source_id": source_id,
        "source_type": req.source_type,
        "request_id": req_id
    }).encode("utf-8")

    nc = getattr(app.state, "nats_client", None)
    if nc:
        try:
            if hasattr(nc, "jetstream"):
                js = nc.jetstream()
                try:
                    await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
                except (nats.errors.Error, nats.js.errors.Error, asyncio.TimeoutError) as exc:
                    logger.debug(
                        "Could not create the task stream; it may already exist (%s)",
                        type(exc).__name__,
                    )
                await js.publish(f"qs.task.sync.{req.source_type}", payload)
            else:
                await nc.publish(f"qs.task.sync.{req.source_type}", payload)
        except (nats.errors.Error, nats.js.errors.Error, asyncio.TimeoutError) as exc:
            logger.warning(
                "Failed to publish task sync event for source_type=%s (%s)",
                req.source_type,
                type(exc).__name__,
            )

    return {
        "status": "success",
        "message": f"Connector {req.source_type} updated.",
        "source_id": source_id,
        "tenant_id": tenant_id,
        "source_type": req.source_type,
        "display_name": display_name,
        "masked_token": config_data.get("masked_token", "••••••••"),
        "poll_interval_hours": req.poll_interval_hours,
        "lookback_days": config_data["lookback_days"],
        "lookback_hours": config_data["lookback_hours"],
    }



class TriggerSyncRequest(BaseModel):
    # Either identifies the connector. `source_id` is exact and is what the
    # dashboard sends; `source_type` remains for callers that predate instances.
    source_id: str | None = Field(None, description="Connector instance to sync")
    source_type: str | None = Field(
        None, description="Connector provider name (e.g. yazio, dawarich)"
    )
    start: datetime | None = Field(None, description="Explicit window start; omit to derive one")
    end: datetime | None = Field(None, description="Explicit window end; omit to use now")
    mode: Literal["smart", "force"] = Field(
        "smart", description="smart skips known-complete ranges; force re-processes everything"
    )


@app.post("/api/v1/data/sources/sync", status_code=202)
async def trigger_sync_post(
    req: TriggerSyncRequest,
    session: AsyncSession = Depends(get_session),
):
    ref = req.source_id or req.source_type
    if not ref:
        raise HTTPException(
            status_code=422, detail="Either source_id or source_type is required"
        )
    return await trigger_sync(
        source_ref=ref,
        session=session,
        start=req.start,
        end=req.end,
        mode=req.mode,
    )


async def _record_failed_sync_request(
    session: AsyncSession,
    tenant_id: str,
    source: DataSource,
    *,
    request_id: str,
    mode: Literal["smart", "force"],
    trigger: str,
    message: str,
    message_code: str = "sync_failed",
    message_params: dict[str, Any] | None = None,
    update_connector: bool = True,
    status: Literal["error", "skipped"] = "error",
) -> SyncRun:
    """Persist a failed import request after its connector was resolved.

    A request that fails before a task reaches an importer still belongs in the
    connector's audit trail. The source and tenant are already authenticated here,
    so recording this row does not require guessing either boundary.
    """
    now = datetime.now(timezone.utc)
    run = SyncRun(
        tenant_id=tenant_id,
        source_id=source.id,
        source_type=source.source_type,
        request_id=request_id,
        mode=mode,
        trigger=trigger,
        status=status,
        message=message[:512],
        message_code=message_code,
        message_params=message_params or {},
        started_at=now,
        finished_at=now,
    )
    session.add(run)

    if update_connector:
        config = dict(source.config or {})
        config["sync_status"] = "error"
        config["last_sync_message"] = message[:512]
        config["last_request_id"] = request_id
        source.config = config
    await session.commit()
    return run


async def plan_and_enqueue_sync(
    session: AsyncSession,
    tenant_id: str,
    source: DataSource,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    mode: Literal["smart", "force"] = "smart",
    trigger: str = "manual",
    window_reason: str | None = None,
) -> dict[str, Any]:
    """Plan a sync window, record the run, and publish the task.

    Extracted from the HTTP handler so the scheduler can enqueue exactly the same
    way a button press does -- same window derivation, same SyncRun row, same NATS
    subject. A second, parallel implementation for scheduled runs is how the two
    quietly drift apart.
    """
    config = source.config or {}
    source_type = source.source_type
    now = datetime.now(timezone.utc)
    req_id = str(uuid.uuid4())

    # Nothing subscribes to a push or file connector's task subject: one is fed by
    # its device, the other by an upload. Enqueueing anyway produced a run that
    # could only expire, and the connector read as "queued" for six hours while it
    # waited for a consumer that does not exist.
    if not is_scheduled(source_type, config):
        run = await _record_failed_sync_request(
            session,
            tenant_id,
            source,
            request_id=req_id,
            mode=mode,
            trigger=trigger,
            message=(
                "This connector does not support scheduled imports; use its webhook "
                "or upload flow."
            ),
            message_code="sync_not_scheduled",
        )
        return {
            "status": "error",
            "source_type": source_type,
            "tenant_id": tenant_id,
            "request_id": req_id,
            "sync_run_id": run.id,
            "message": run.message,
        }

    # The check and the following plan/run insert must be one single-flight
    # critical section. The HTTP handler creates one database session per request,
    # so a plain SELECT here still lets two simultaneous clicks both see an empty
    # in-flight set. The transaction-scoped connector lock makes the second request
    # wait, then re-check after the first run has committed.
    await acquire_connector_lock(session, tenant_id, source.id)

    # Core is the single authority on whether a connector is already busy. The
    # importers each kept a process-local `active_syncs` set, which stops nothing
    # once a second replica exists -- both would accept the same task. Refusing to
    # enqueue here means the duplicate never reaches them, whatever they run.
    # `force` bypasses coverage skipping, not single-flight execution. Allowing it
    # through here was the source of two concurrent provider runs for one click.
    if await has_in_flight_run(
        session, tenant_id, source.id, now=now
    ):
        logger.info(
            "[req_id=%s] Sync for %s not enqueued: a run is already in flight.",
            req_id,
            source_type,
        )
        run = await _record_failed_sync_request(
            session,
            tenant_id,
            source,
            request_id=req_id,
            mode=mode,
            trigger=trigger,
            message="The connector already has an import in flight.",
            message_code="sync_in_flight",
            update_connector=False,
            status="skipped",
        )
        return {
            "status": "skipped",
            "source_type": source_type,
            "tenant_id": tenant_id,
            "request_id": req_id,
            "sync_run_id": run.id,
            "message": run.message,
        }

    try:
        (
            configured_fetchers,
            configured_signature,
            coverage_scope,
            coverage_reason,
        ) = await _source_coverage_plan(session, tenant_id, source)
        coverage_signature = configured_signature

        if start and end:
            window = _validated_window(start, end)
            # A caller that derived the period itself says why. Without this every
            # explicit window claimed to be "chosen by the user", including the ones
            # no user chose — and the import history is where somebody looks to find
            # out why a connector re-fetched three months.
            window_reason = window_reason or "Period chosen by the user."
        else:
            window, window_reason = compute_sync_window(
                now=now,
                poll_interval_hours=float(config.get("poll_interval_hours", 6)),
                lookback_days=int(config.get("lookback_days", 7)),
                lookback_hours=_configured_lookback_hours(config),
                last_success_end=await _last_successful_sync_end(
                    session,
                    tenant_id,
                    source.id,
                    coverage_signature=coverage_signature,
                    require_coverage_contract=True,
                ),
            )

        fetch = _bucket_fetcher(session, tenant_id, source_id=source.id)
        plan = await plan_import(
            fetch,
            window,
            mode=mode,
            metric_fetchers=configured_fetchers,
            coverage_scope=coverage_scope,
            coverage_reason=coverage_reason,
        )
    except HTTPException as exc:
        await _record_failed_sync_request(
            session,
            tenant_id,
            source,
            request_id=req_id,
            mode=mode,
            trigger=trigger,
            message=str(exc.detail),
            message_code="sync_plan_failed",
        )
        raise
    except Exception as exc:
        await _record_failed_sync_request(
            session,
            tenant_id,
            source,
            request_id=req_id,
            mode=mode,
            trigger=trigger,
            message=f"Import planning failed: {type(exc).__name__}.",
            message_code="sync_plan_failed",
        )
        raise

    effective = plan.recommended or window
    nothing_to_do = plan.recommended is None and mode == "smart"

    run = SyncRun(
        tenant_id=tenant_id,
        source_id=source.id,
        source_type=source_type,
        request_id=req_id,
        mode=mode,
        trigger=trigger,
        window_start=effective.start,
        window_end=effective.end,
        window_reason=_with_coverage_marker(
            f"{window_reason} {plan.reason}".strip(), coverage_signature
        )[:255],
        status="skipped" if nothing_to_do else "queued",
        skipped_ranges=[r.to_dict() for r in plan.covered],
        message=plan.reason[:512],
        message_code="sync_skipped" if nothing_to_do else "sync_queued",
        message_params={},
        finished_at=now if nothing_to_do else None,
    )
    session.add(run)

    new_config = dict(config)
    new_config["last_sync_at"] = now.isoformat()
    new_config["sync_status"] = "idle" if nothing_to_do else "queued"
    new_config["last_request_id"] = req_id
    new_config["last_sync_message"] = plan.reason[:512]
    source.config = new_config
    await session.commit()

    if nothing_to_do:
        logger.info(
            "[req_id=%s] Sync for %s skipped: range already complete.", req_id, source_type
        )
        return {
            "status": "skipped",
            "source_type": source_type,
            "tenant_id": tenant_id,
            "request_id": req_id,
            "sync_run_id": run.id,
            "message": run.message,
            "mode": mode,
            "plan": plan.to_dict(),
        }

    payload = json.dumps({
        "tenant_id": tenant_id,
        # Which instance to sync. The importer fetches its credential by this id
        # and keys every point it produces on it, so without it a tenant's second
        # calendar would import the first one's feed.
        "source_id": source.id,
        "source_type": source_type,
        "request_id": req_id,
        "sync_run_id": run.id,
        "mode": mode,
        "window_start": effective.start.isoformat(),
        "window_end": effective.end.isoformat(),
    }).encode("utf-8")
    
    nc = getattr(app.state, "nats_client", None)
    publish_error: Exception | None = None
    if nc:
        try:
            if hasattr(nc, "jetstream"):
                js = nc.jetstream()
                try:
                    await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
                except (nats.errors.Error, nats.js.errors.Error, asyncio.TimeoutError) as exc:
                    logger.debug(
                        "Could not create the task stream; it may already exist (%s)",
                        type(exc).__name__,
                    )
                await js.publish(f"qs.task.sync.{source_type}", payload)
            else:
                await nc.publish(f"qs.task.sync.{source_type}", payload)
        except (nats.errors.Error, nats.js.errors.Error, asyncio.TimeoutError) as exc:
            publish_error = exc
    else:
        publish_error = RuntimeError("NATS client is unavailable")

    if publish_error is not None:
        message = f"Could not queue the import ({type(publish_error).__name__})."
        logger.warning(
            "Could not queue import for source_type=%s (%s)",
            source_type,
            type(publish_error).__name__,
        )
        run.status = "error"
        run.message = message[:512]
        run.message_code = "sync_queue_failed"
        run.message_params = {}
        run.finished_at = datetime.now(timezone.utc)
        source_config = dict(source.config or {})
        source_config["sync_status"] = "error"
        source_config["last_sync_message"] = message[:512]
        source.config = source_config
        await session.commit()
        logger.warning("[req_id=%s] %s", req_id, message)
        return {
            "status": "error",
            "source_type": source_type,
            "tenant_id": tenant_id,
            "request_id": req_id,
            "sync_run_id": run.id,
            "message": run.message,
        }

    # The importer can call back immediately after NATS accepts the task. Move
    # the run to the importer phase only if it is still queued; a conditional
    # update prevents this request from overwriting a faster `loading` or
    # `success` transition made by the importer/consumer.
    importer_message = "Import task queued for the importer."
    transition = await session.execute(
        sa_update(SyncRun)
        .where(
            SyncRun.id == run.id,
            SyncRun.tenant_id == tenant_id,
            SyncRun.status == "queued",
        )
        .values(
            status="running",
            message=importer_message,
            message_code="sync_queued",
            message_params={},
        )
    )
    if transition.rowcount:
        source_config = dict(source.config or {})
        source_config["sync_status"] = "running"
        source_config["last_sync_message"] = importer_message
        source.config = source_config
    await session.commit()

    return {
        "status": "sync_queued",
        "source_type": source_type,
        "tenant_id": tenant_id,
        "request_id": req_id,
        "sync_run_id": run.id,
    }


@app.post("/api/v1/data/sources/{source_ref}/sync", status_code=202)
async def trigger_sync(
    source_ref: str,
    session: AsyncSession = Depends(get_session),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    mode: Literal["smart", "force"] = Query("smart"),
):
    """Trigger an on-demand sync for a connector.

    Core decides the window rather than the importer: it owns the sync history the
    decision depends on. In smart mode the window is narrowed to what is actually
    missing; in force mode the full range is sent and the extra work is recorded on
    the run so the audit trail shows it was deliberate.
    """
    tenant_id = get_current_tenant_id()

    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    return await plan_and_enqueue_sync(
        session, tenant_id, source, start=start, end=end, mode=mode, trigger="manual"
    )


@app.get("/api/v1/data/sources")
async def list_connectors(
    session: AsyncSession = Depends(get_session),
):
    """List configured connectors for the tenant with masked secrets and sync details."""
    tenant_id = get_current_tenant_id()

    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.deleted_at.is_(None),
    )
    res = await session.execute(stmt)
    sources = res.scalars().all()

    # One grouped query for every connector's newest write, not one per connector.
    #
    # This is the endpoint the connector page refreshes on a timer, so its cost is
    # paid continuously rather than once: with eight connectors configured it ran
    # eight `max(created_at)` aggregates over the largest table in the database
    # every ten seconds, per open tab. The grouped form reads the same index once.
    last_write_stmt = (
        select(DataPoint.source_id, func.max(DataPoint.created_at))
        .where(DataPoint.tenant_id == tenant_id)
        .group_by(DataPoint.source_id)
    )
    last_write_at = {
        source_id: created_at
        for source_id, created_at in (await session.execute(last_write_stmt)).all()
    }

    connectors = []
    for s in sources:
        config = s.config or {}
        # A credential-optional connector has no stored token, so absence of one is
        # not evidence that the connector is unconfigured.
        credential_optional = credential_is_optional(s.source_type, config)
        if config.get("status") == "inactive":
            continue
        if not config.get("encrypted_token") and not credential_optional:
            continue

        last_dp_dt = last_write_at.get(s.id)

        last_sync_at = (
            last_dp_dt.isoformat()
            if last_dp_dt
            else config.get("last_sync_at")
        )

        connectors.append({
            "id": s.id,
            "source_id": s.id,
            "tenant_id": s.tenant_id,
            "source_type": s.source_type,
            "display_name": s.display_name,
            "status": config.get("status", "active"),
            "sync_status": config.get("sync_status", "idle" if last_dp_dt else "pending"),
            # Services answer in English (rule 16); the dashboard renders its own
            # wording for a connector that has not run yet.
            "last_sync_message": config.get("last_sync_message", "Ready."),
            "last_request_id": config.get("last_request_id"),
            "nats_subject": f"qs.task.sync.{s.source_type}",
            "nats_queue_group": f"{s.source_type}_importer_task_group",
            "masked_token": config.get("masked_token", "••••••••"),
            # How this connector is fed, and whether it *could* be fed by a file.
            # The dashboard offers an upload on the strength of these two rather
            # than keeping its own list of which providers ship an export.
            "import_mode": config.get("import_mode"),
            "supports_file_import": supports_file_import(s.source_type),
            "poll_interval_hours": config.get("poll_interval_hours", 6),
            "lookback_days": config.get(
                "lookback_days", math.ceil(_configured_lookback_hours(config) / 24)
            ),
            "lookback_hours": _configured_lookback_hours(config),
            "last_sync_at": last_sync_at,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": config.get("updated_at"),
        })

    return {
        "tenant_id": tenant_id,
        "connectors": connectors,
    }


@app.delete("/api/v1/data/sources/{source_ref}")
async def delete_connector(
    source_ref: str,
    session: AsyncSession = Depends(get_session),
):
    """Wipe one connector's credentials without deleting its ingested data points.

    `source_ref` is the connector's id. A bare source type still resolves, but with
    several instances of a type it would disconnect an arbitrary one, so the
    dashboard always sends the id.
    """
    tenant_id = get_current_tenant_id()
    source = await _resolve_source_ref(session, tenant_id, source_ref)

    if not source:
        raise HTTPException(status_code=404, detail="Connector configuration not found")

    # Clear encrypted token and deactivate connector while preserving the source
    # row and all ingested data_points. The deletion timestamp lets a new active
    # connector reuse this display name without changing historical provenance.
    deleted_at = datetime.now(timezone.utc)
    source.config = {
        "status": "inactive",
        "updated_at": deleted_at.isoformat(),
    }
    source.deleted_at = deleted_at
    await session.commit()

    return {
        "status": "success",
        "message": (
            f"Token for connector '{source.display_name}' deleted successfully. "
            "Ingested metric data preserved."
        ),
        "source_id": source.id,
        "source_type": source.source_type,
        "tenant_id": tenant_id,
    }


@app.get("/api/v1/internal/data/sources/{source_ref}/token")
async def get_connector_token(
    source_ref: str,
    session: AsyncSession = Depends(get_session),
):
    """Internal endpoint for Importer microservices to fetch decrypted credentials.

    `source_ref` is the connector's id -- the sync task carries it, because with
    several connectors of one type the type alone no longer says whose credential
    is wanted. A bare type still resolves, for the importers and tests that address
    themselves that way.
    """
    tenant_id = get_current_tenant_id()
    source = await _resolve_source_ref(session, tenant_id, source_ref)

    if not source or not source.config:
        raise HTTPException(status_code=404, detail=f"No connector configured for {source_ref}")

    source_type = source.source_type

    encrypted_token = source.config.get("encrypted_token")
    if not encrypted_token:
        # A credential-optional connector has no provider credential. The importer
        # still needs source_id and config, so return those with a null token
        # rather than a 404 it would have to special-case.
        if not credential_is_optional(source_type, source.config):
            raise HTTPException(
                status_code=404, detail="Token not found in connector configuration"
            )
        return {
            "tenant_id": tenant_id,
            "source_id": str(source.id),
            "source_type": source_type,
            "access_token": None,
            "status": source.config.get("status", "active"),
            "config": {
                k: v
                for k, v in (source.config or {}).items()
                if k not in {"encrypted_token", "masked_token"}
            },
        }

    # Refresh here, ahead of expiry, rather than letting the importer discover the
    # problem as a 401. WHOOP access tokens last about an hour while the connector
    # polls every six, so without this the connector worked for one hour after
    # somebody pasted a token by hand and then failed silently until they did it
    # again. Core does it because rotating a credential means writing the new one
    # back encrypted, and only Core may touch the database (rules 1 and 8).
    now = datetime.now(timezone.utc)
    config = source.config or {}
    if needs_refresh(config, now=now) and can_refresh(source_type, config):
        req_id = get_current_request_id()
        try:
            refreshed = await refresh_credential(source_type, config, req_id=req_id)
        except RefreshError as exc:
            # Surface it as an unusable connector rather than handing back a token
            # already known to be expired.
            logger.warning(
                "[req_id=%s] Could not refresh %s credential: %s",
                req_id,
                source_type,
                exc,
            )
            raise HTTPException(
                status_code=409,
                detail=(
                    "The credentials for this connector have expired and could "
                    "not be renewed. Please connect it again."
                ),
            ) from exc

        source.config = apply_refresh(config, refreshed)
        await session.commit()
        config = source.config
        encrypted_token = config["encrypted_token"]

    try:
        decrypted_token = decrypt_secret(encrypted_token)
        return {
            "tenant_id": tenant_id,
            "source_id": str(source.id),
            "source_type": source_type,
            "access_token": decrypted_token,
            "status": config.get("status", "active"),
            "config": {
                k: v
                for k, v in config.items()
                # The refresh token and client secret never leave this service --
                # the importer gets only the short-lived access token (rule 12).
                if k
                not in {
                    "encrypted_token",
                    "masked_token",
                    "encrypted_refresh_token",
                    "encrypted_client_secret",
                }
            },
        }
    except DecryptionError:
        raise HTTPException(status_code=500, detail="Failed to decrypt connector secret")


@app.get("/api/v1/internal/data/sources/{source_ref}/ingest-policy")
async def get_connector_ingest_policy(
    source_ref: str,
    session: AsyncSession = Depends(get_session),
):
    """Return tenant-scoped ingest policies to a stateless importer."""
    tenant_id = get_current_tenant_id()
    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {
        "tenant_id": tenant_id,
        "source_id": str(source.id),
        "source_type": source.source_type,
        "policies": await _effective_ingest_policies(session, tenant_id),
        "applies_to": "future_imports",
    }


# ─── Tenant-bound Inbound API Keys ──────────────────────────


async def _resolve_connector_for_key(
    session: AsyncSession, tenant_id: str, source_type: str, source_id: str | None
) -> DataSource:
    """The connector instance an inbound key will push to.

    Named explicitly, or inferred when the tenant has exactly one connector of the
    type. Two candidates and no choice is an error rather than a guess: the id
    picked here ends up in every idempotency key derived from data pushed with this
    credential, so guessing wrong is not a routing mistake but a data one.
    """
    if source_id:
        source = await _resolve_source(session, tenant_id, source_type, source_id=source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Connector not found")
        return source

    res = await session.execute(
        select(DataSource)
        .where(
            DataSource.tenant_id == tenant_id,
            DataSource.deleted_at.is_(None),
            DataSource.source_type == source_type,
        )
        .order_by(DataSource.created_at, DataSource.id)
    )
    candidates = res.scalars().all()
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No {source_type} connector is configured. Create one first.",
        )
    if len(candidates) > 1:
        raise HTTPException(
            status_code=409,
            detail="Several connectors of this type exist; name the one with source_id.",
        )
    return candidates[0]


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., description="Connector this key may push to")
    # Which connector instance the pushed data belongs to. Optional only so a
    # tenant with a single connector of the type need not name it; the endpoint
    # resolves it and refuses when the choice is ambiguous.
    source_id: str | None = Field(None, description="Connector instance this key pushes to")
    expires_in_days: int | None = Field(
        None, ge=1, le=3650, description="Optional expiry; omit for a non-expiring key"
    )
    scopes: list[str] = Field(default_factory=lambda: ["ingest"], max_length=8)


def _serialize_api_key(key: ApiKey) -> dict[str, Any]:
    """Public representation of a key. Never includes the key itself."""
    return {
        "id": key.id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "source_type": key.source_type,
        "source_id": key.source_id,
        "scopes": key.scopes,
        "status": key.status,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
        "rotated_from_id": key.rotated_from_id,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


@app.post("/api/v1/data/api-keys", status_code=201)
async def create_api_key_endpoint(
    req: CreateApiKeyRequest,
    principal: Principal = Depends(require_role("owner", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """Create an inbound API key bound to the authenticated tenant.

    The plaintext key is returned in this response and never again — not in the
    list endpoint, not in logs, not in errors.
    """
    if req.source_type not in PUSH_SOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"source_type must be one of: {', '.join(sorted(PUSH_SOURCE_TYPES))}",
        )

    # A key has to name the connector *instance* it pushes to: that id becomes the
    # `source_id` of every point ingested under it, and therefore part of every
    # idempotency key. With two connectors of the type and no choice made, guessing
    # would quietly file one device's readings under the other.
    target = await _resolve_connector_for_key(
        session, principal.tenant_id, req.source_type, req.source_id
    )

    raw_key, key_prefix, key_hash = create_api_key()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)
        if req.expires_in_days
        else None
    )

    record = ApiKey(
        tenant_id=principal.tenant_id,
        created_by_user_id=principal.user_id,
        name=req.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
        source_type=req.source_type,
        source_id=target.id,
        scopes=req.scopes,
        expires_at=expires_at,
    )
    session.add(record)
    await session.commit()

    logger.info(
        "Created API key prefix=%s source_type=%s tenant=%s",
        key_prefix,
        req.source_type,
        principal.tenant_id,
    )

    return {
        "status": "success",
        "api_key": raw_key,
        "warning": "This key is shown only once. Store it somewhere safe.",
        **_serialize_api_key(record),
    }


@app.get("/api/v1/data/api-keys")
async def list_api_keys(
    session: AsyncSession = Depends(get_session),
):
    """List the tenant's API keys, without ever disclosing key material."""
    tenant_id = get_current_tenant_id()
    res = await session.execute(
        select(ApiKey)
        .where(ApiKey.tenant_id == tenant_id)
        .order_by(ApiKey.created_at.desc())
    )
    return {
        "tenant_id": tenant_id,
        "api_keys": [_serialize_api_key(k) for k in res.scalars().all()],
    }


@app.post("/api/v1/data/api-keys/{key_id}/revoke")
async def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(require_role("owner", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """Revoke a key immediately. Ingest with a revoked key fails closed."""
    res = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == principal.tenant_id)
    )
    key = res.scalars().first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.status = "revoked"
    key.revoked_at = datetime.now(timezone.utc)
    await session.commit()

    return {"status": "revoked", **_serialize_api_key(key)}


@app.post("/api/v1/data/api-keys/{key_id}/rotate")
async def rotate_api_key(
    key_id: str,
    principal: Principal = Depends(require_role("owner", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """Issue a replacement key, leaving the old one active for a grace period.

    Both keys work until the old one is explicitly revoked, so an external pusher
    can be reconfigured without an ingest gap. Multiple active keys per tenant are
    intentional.
    """
    res = await session.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.tenant_id == principal.tenant_id)
    )
    old_key = res.scalars().first()
    if not old_key:
        raise HTTPException(status_code=404, detail="API key not found")
    if old_key.status != "active":
        raise HTTPException(status_code=400, detail="Only active keys can be rotated")

    raw_key, key_prefix, key_hash = create_api_key()
    replacement = ApiKey(
        tenant_id=principal.tenant_id,
        created_by_user_id=principal.user_id,
        name=f"{old_key.name} (rotated)",
        key_prefix=key_prefix,
        key_hash=key_hash,
        source_type=old_key.source_type,
        # The replacement pushes to the same connector instance. Rotation changes
        # the credential, not where the data lands -- and since this id is part of
        # every idempotency key derived from it, a different one would make the
        # same readings arrive again as new points.
        source_id=old_key.source_id,
        scopes=old_key.scopes,
        expires_at=old_key.expires_at,
        rotated_from_id=old_key.id,
    )
    session.add(replacement)
    await session.commit()

    logger.info(
        "Rotated API key old_prefix=%s new_prefix=%s tenant=%s",
        old_key.key_prefix,
        key_prefix,
        principal.tenant_id,
    )

    return {
        "status": "rotated",
        "api_key": raw_key,
        "warning": "The old key stays active until it is revoked.",
        "previous_key_id": old_key.id,
        **_serialize_api_key(replacement),
    }


class ResolveApiKeyRequest(BaseModel):
    key_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    source_type: str = Field(..., max_length=64)


class RecordApiKeyFailureRequest(BaseModel):
    """A rejected inbound request, identified without sending its plaintext key."""

    key_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    source_type: str = Field(..., max_length=64)
    request_id: str = Field(..., min_length=1, max_length=128)
    status_code: int = Field(..., ge=400, le=599)
    message: str = Field(..., min_length=1, max_length=512)


@app.post("/api/v1/internal/auth/api-keys/resolve")
async def resolve_api_key(
    req: ResolveApiKeyRequest,
    session: AsyncSession = Depends(get_session),
):
    """Resolve a presented API key hash to its owning tenant.

    Edge services hash the key locally and send only the digest, so the raw key
    never travels between services. A rejected key yields ``401`` with no detail
    about *why* — expired, revoked and unknown are indistinguishable to the caller.
    """
    res = await session.execute(select(ApiKey).where(ApiKey.key_hash == req.key_hash))
    key = res.scalars().first()

    now = datetime.now(timezone.utc)
    if not key or key.status != "active":
        raise HTTPException(status_code=401, detail="Invalid API key")

    if key.expires_at is not None:
        expires_at = key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise HTTPException(status_code=401, detail="Invalid API key")

    if key.source_type != req.source_type:
        # A key minted for one connector must not be replayable against another.
        raise HTTPException(status_code=403, detail="API key not valid for this source")

    key.last_used_at = now
    await session.commit()

    # The key names the connector *instance*, not just its type. Once a tenant can
    # hold two Apple Health connectors, the type no longer answers "whose reading
    # is this?" — and that answer is the `source_id` every idempotency key derived
    # from this push is built from, so getting it wrong would merge two people's
    # phones into one series.
    return {
        "tenant_id": key.tenant_id,
        "source_id": key.source_id,
        "source_type": key.source_type,
        "key_id": key.id,
        "key_prefix": key.key_prefix,
        "scopes": key.scopes,
    }


@app.post("/api/v1/internal/auth/api-keys/failure", status_code=202)
async def record_api_key_failure(
    req: RecordApiKeyFailureRequest,
    session: AsyncSession = Depends(get_session),
):
    """Record a rejected request when its key still identifies a connector.

    The importer sends only the SHA-256 digest. Unknown or missing keys cannot be
    assigned to a tenant safely and therefore produce no tenant-visible run; a
    revoked or expired key can still be attributed to its own connector here.
    """
    result = await session.execute(select(ApiKey).where(ApiKey.key_hash == req.key_hash))
    key = result.scalars().first()
    if key is None or key.source_type != req.source_type or not key.source_id:
        return {"status": "accepted"}

    now = datetime.now(timezone.utc)
    run = SyncRun(
        tenant_id=key.tenant_id,
        source_id=key.source_id,
        source_type=key.source_type,
        request_id=req.request_id,
        mode="force",
        trigger="push",
        status="error",
        points_received=0,
        message=f"HTTP {req.status_code}: {req.message}"[:512],
        started_at=now,
        finished_at=now,
    )
    session.add(run)
    await session.commit()
    return {"status": "accepted"}


# ─── Explorer Saved Views Endpoints ─────────────────────────

class CreateExplorerViewRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Name of the saved view")
    query_config: dict[str, Any] = Field(..., description="Query configuration JSON")
    is_shared: bool = Field(False, description="Share view with workspace members")


@app.get("/api/v1/data/explorer/views")
async def list_explorer_views(
    session: AsyncSession = Depends(get_session),
):
    """List all saved Explorer Views for the authenticated tenant from PostgreSQL."""
    tenant_id = get_current_tenant_id()
    stmt = (
        select(ExplorerView)
        .where(ExplorerView.tenant_id == tenant_id)
        .order_by(ExplorerView.created_at.desc())
    )
    res = await session.execute(stmt)
    views = res.scalars().all()
    return {
        "status": "success",
        "tenant_id": tenant_id,
        "views": [
            {
                "id": str(v.id),
                "name": v.name,
                "query_config": v.query_config,
                "is_shared": v.is_shared,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in views
        ],
    }


@app.post("/api/v1/data/explorer/views")
async def create_explorer_view(
    req: CreateExplorerViewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Save a custom Explorer View query configuration directly in PostgreSQL."""
    tenant_id = get_current_tenant_id()
    view_id = str(uuid.uuid4())
    new_view = ExplorerView(
        id=view_id,
        tenant_id=tenant_id,
        name=req.name,
        query_config=req.query_config,
        is_shared=req.is_shared,
    )
    session.add(new_view)
    await session.commit()

    return {
        "status": "success",
        "message": "View saved.",
        "view_id": view_id,
        "tenant_id": tenant_id,
        "name": req.name,
        "query_config": req.query_config,
    }


@app.delete("/api/v1/data/explorer/views/{view_id}")
async def delete_explorer_view(
    view_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Delete a saved Explorer View from PostgreSQL with tenant isolation."""
    tenant_id = get_current_tenant_id()
    stmt = select(ExplorerView).where(
        ExplorerView.id == view_id,
        ExplorerView.tenant_id == tenant_id,
    )
    res = await session.execute(stmt)
    view = res.scalars().first()

    if not view:
        raise HTTPException(status_code=404, detail="View not found, or not yours.")

    await session.delete(view)
    await session.commit()

    return {
        "status": "success",
        "message": f"View {view_id} deleted.",
        "view_id": view_id,
    }


class UpdateConnectorStatusRequest(BaseModel):
    sync_status: str
    last_sync_message: str
    sync_run_id: str | None = Field(None, description="Run to close out, if known")
    points_received: int | None = Field(None, ge=0)
    points_rejected: int | None = Field(None, ge=0)
    unsupported_fields: int | None = Field(None, ge=0)
    backlog: int | None = Field(None, ge=0)
    provider_window_start: datetime | None = None
    provider_window_end: datetime | None = None
    provider_exported_at: datetime | None = None
    code: str | None = Field(None, max_length=64)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class FieldReportPayload(FieldReport):
    """What an importer sends, which is a `FieldReport` plus the run it belongs to.

    Inherited rather than restated: both ends of this contract were written in the
    same change, and a hand-written twin would silently drop any field added to the
    shared model.
    """

    sync_run_id: str | None = None


@app.post("/api/v1/internal/data/sources/{source_ref}/field-report", status_code=202)
async def record_field_report_internal(
    source_ref: str,
    req: FieldReportPayload,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """Record which provider fields an import used, and which it ignored.

    Upserted per path, so the table holds a rolling picture of the provider's shape
    rather than one row per import. `occurrences` accumulates, which is what makes
    "seen 4 000 times and never stored" distinguishable from a one-off oddity.
    """
    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    now = datetime.now(timezone.utc)
    # Merged by path first. `ON CONFLICT DO UPDATE` cannot touch the same row twice
    # in one statement, so two sightings of one path would have failed the whole
    # request with a 500 — and the collector happening to deduplicate today is a
    # property of one client, not a guarantee this endpoint can rely on.
    merged: dict[str, dict[str, Any]] = {}
    for sighting in (*req.mapped, *req.unmapped):
        row = merged.get(sighting.path)
        if row is None:
            merged[sighting.path] = {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "source_id": source.id,
                "source_type": source.source_type,
                "field_path": sighting.path,
                "value_kind": sighting.kind,
                "metric_type": sighting.metric_type,
                "occurrences": sighting.occurrences,
                "first_seen_at": now,
                "last_seen_at": now,
                "last_sync_run_id": req.sync_run_id,
            }
            continue
        row["occurrences"] += sighting.occurrences
        # A path mapped anywhere in this report is mapped, whichever order it came in.
        row["metric_type"] = row["metric_type"] or sighting.metric_type
    rows = list(merged.values())
    if not rows:
        return {"status": "ok", "recorded": 0}

    statement = pg_insert(IngestFieldReport).values(rows)
    statement = statement.on_conflict_do_update(
        constraint="uq_field_reports_tenant_source_path",
        set_={
            "value_kind": statement.excluded.value_kind,
            # A path that has *become* mapped must stop being reported as a gap —
            # that transition is precisely the evidence a fix worked.
            #
            # `coalesce`, not a bare overwrite. One import can legitimately see a path
            # in a payload shape where it maps to nothing — a provider that omits the
            # field it usually nests under, an entry of a kind the transformer has no
            # rule for — and a bare overwrite let that single run flip an established
            # mapping back to NULL. The field would then reappear in "not yet
            # supported" while being stored perfectly well, which is the one thing
            # that page must never say.
            "metric_type": func.coalesce(
                statement.excluded.metric_type, IngestFieldReport.metric_type
            ),
            # The moment support arrived, recorded once and never revised. It is what
            # separates "became supported" from "was always supported", and therefore
            # the only thing that can tell a user their missing field now works — and
            # that its history is worth re-importing.
            "supported_since": case(
                (
                    and_(
                        IngestFieldReport.metric_type.is_(None),
                        statement.excluded.metric_type.is_not(None),
                    ),
                    statement.excluded.last_seen_at,
                ),
                else_=IngestFieldReport.supported_since,
            ),
            "occurrences": IngestFieldReport.occurrences + statement.excluded.occurrences,
            "last_seen_at": statement.excluded.last_seen_at,
            "last_sync_run_id": statement.excluded.last_sync_run_id,
        },
    )
    await session.execute(statement)
    await session.commit()

    return {"status": "ok", "recorded": len(rows), "truncated": req.truncated}


@app.get("/api/v1/data/quality/unsupported-fields")
async def list_unsupported_fields(
    session: AsyncSession = Depends(get_session),
):
    """Fields this platform is being given and is not storing.

    The question a user cannot otherwise ask: *is my device sending something that
    never arrives?* Answered from shape alone — there are no values here, and the
    response says so in its own field names.
    """
    tenant_id = get_current_tenant_id()
    res = await session.execute(
        select(IngestFieldReport, DataSource.display_name)
        .join(DataSource, DataSource.id == IngestFieldReport.source_id)
        .where(
            IngestFieldReport.tenant_id == tenant_id,
            IngestFieldReport.metric_type.is_(None),
        )
        .order_by(IngestFieldReport.occurrences.desc(), IngestFieldReport.field_path)
        .limit(500)
    )

    fields = [
        {
            "source_id": row.source_id,
            "source_type": row.source_type,
            "connector_name": display_name,
            "field_path": row.field_path,
            "value_kind": row.value_kind,
            "occurrences": row.occurrences,
            "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row, display_name in res.all()
    ]
    return {"tenant_id": tenant_id, "fields": fields}


#: How long a field stays on the "newly supported" list after it becomes supported.
#:
#: It is a notice, not a permanent record. A field supported six months ago is simply
#: a supported field, and leaving it here forever would turn a list meant to prompt
#: an action into a changelog nobody reads.
NEWLY_SUPPORTED_WINDOW = timedelta(days=90)


@app.get("/api/v1/data/quality/newly-supported-fields")
async def list_newly_supported_fields(
    within_days: int = Query(
        NEWLY_SUPPORTED_WINDOW.days,
        ge=1,
        le=365,
        description="How far back a support transition still counts as recent",
    ),
    session: AsyncSession = Depends(get_session),
):
    """Fields that used to arrive unstored and are now being stored.

    The other half of `unsupported-fields`, and the half that answers the question
    a user actually comes back with: *the thing I reported as missing — does it work
    now?* Before this, a field that became supported simply vanished from the
    unsupported list, which is indistinguishable from a field that stopped arriving.

    **Re-checking is a property of importing, not of a sweep.** Whether a provider
    field maps to a metric is decided by that provider's transformer, which lives in
    the importer; Core holds no such table and could not evaluate it. So the check
    happens on every scheduled import, for free, and this endpoint reports the
    transitions it produced.

    `history_recoverable` is what makes it actionable: a field supported today has a
    history that was never stored, and a force import over that period is what
    recovers it. A connector that is fed by a device or an archive cannot do that —
    its history is in the device or the archive — and saying so is better than
    offering a button that silently does nothing. `is_scheduled` rather than a
    push-type test, because a file-import connector cannot be re-fetched either and
    was previously told it could.

    `history_backfilled_at` is the follow-up: for a recoverable field the sweep in
    `core.field_backfill` queues that force import by itself, and this says whether
    it has happened yet. A recoverable field with no timestamp is waiting for the
    next sweep, not stuck.
    """
    tenant_id = get_current_tenant_id()
    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    res = await session.execute(
        select(IngestFieldReport, DataSource.display_name, DataSource.config)
        .join(DataSource, DataSource.id == IngestFieldReport.source_id)
        .where(
            IngestFieldReport.tenant_id == tenant_id,
            IngestFieldReport.supported_since.is_not(None),
            IngestFieldReport.supported_since >= cutoff,
        )
        .order_by(IngestFieldReport.supported_since.desc(), IngestFieldReport.field_path)
        .limit(500)
    )

    fields = [
        {
            "source_id": row.source_id,
            "source_type": row.source_type,
            "connector_name": display_name,
            "field_path": row.field_path,
            "metric_type": row.metric_type,
            "value_kind": row.value_kind,
            "occurrences": row.occurrences,
            "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "supported_since": row.supported_since.isoformat(),
            # The span whose data was never stored for this field: from the first
            # time it was seen to the moment it started being kept.
            "unstored_from": row.first_seen_at.isoformat() if row.first_seen_at else None,
            "unstored_until": row.supported_since.isoformat(),
            "history_recoverable": is_scheduled(row.source_type, config),
            "history_backfilled_at": (
                row.history_backfilled_at.isoformat() if row.history_backfilled_at else None
            ),
        }
        for row, display_name, config in res.all()
    ]
    return {"tenant_id": tenant_id, "fields": fields, "within_days": within_days}


class MetricMappingRequest(BaseModel):
    """A tenant's decision for one connector-specific unresolved metric name."""

    source_id: str = Field(..., min_length=1, max_length=64)
    raw_metric_type: str = Field(..., min_length=1, max_length=128)
    action: MappingAction
    target_metric_type: str | None = Field(None, max_length=128)
    source_unit: str | None = Field(None, max_length=32)
    target_unit: str | None = Field(None, max_length=32)
    aggregation: str | None = Field(None, max_length=16)
    cadence: str | None = Field(None, max_length=16)
    keep_indefinitely: bool = False


async def _replay_quarantined_rows(
    session: AsyncSession,
    *,
    tenant_id: str,
    source: DataSource,
    rule: MetricMappingRule,
    mapping: ValidatedMapping,
) -> dict[str, Any]:
    """Replay or discard active rows in one tenant-scoped audit run.

    Rows are processed in bounded batches. Quarantine has a deliberately generous
    cap for recovery, but loading every point and its metadata into one Python list
    would turn that safety valve into an API-triggered memory exhaustion vector.
    """
    await session.execute(
        select(DataSource.id)
        .where(DataSource.tenant_id == tenant_id, DataSource.id == source.id)
        .with_for_update()
    )
    filters = (
        QuarantinedDataPoint.tenant_id == tenant_id,
        QuarantinedDataPoint.source_id == source.id,
        QuarantinedDataPoint.raw_metric_type == rule.raw_metric_type,
        QuarantinedDataPoint.status == "active",
    )
    total_result = await session.execute(
        select(func.count(QuarantinedDataPoint.id)).where(*filters)
    )
    total = total_result.scalar_one() or 0
    if total == 0:
        return {"replayed": 0, "accepted": 0, "duplicates": 0, "discarded": 0, "sync_run_id": None}

    first_result = await session.execute(
        select(QuarantinedDataPoint.timestamp)
        .where(*filters)
        .order_by(QuarantinedDataPoint.timestamp, QuarantinedDataPoint.id)
        .limit(1)
    )
    last_result = await session.execute(
        select(QuarantinedDataPoint.timestamp)
        .where(*filters)
        .order_by(QuarantinedDataPoint.timestamp.desc(), QuarantinedDataPoint.id.desc())
        .limit(1)
    )
    window_start = first_result.scalar_one()
    window_end = last_result.scalar_one()

    now = datetime.now(timezone.utc)
    run = SyncRun(
        tenant_id=tenant_id,
        source_id=source.id,
        source_type=source.source_type,
        request_id=get_current_request_id() or str(uuid.uuid4()),
        mode="force",
        trigger="mapping_replay",
        window_start=window_start,
        window_end=window_end,
        window_reason="Replay of values held for a resolved metric mapping.",
        status="running",
        points_expected=total,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    accepted = 0
    duplicates = 0
    discarded = 0
    processed = 0
    while processed < total:
        result = await session.execute(
            select(QuarantinedDataPoint)
            .where(*filters)
            .order_by(QuarantinedDataPoint.timestamp, QuarantinedDataPoint.id)
            .limit(QUARANTINE_REPLAY_BATCH_SIZE)
        )
        rows = list(result.scalars())
        if not rows:
            break
        for row in rows:
            if mapping.action == "discard":
                row.status = "discarded"
                discarded += 1
            else:
                value, metadata = replay_value(row.value, row.metadata_, mapping)
                if mapping.target_metric_type is None:
                    raise ValueError("replay mapping has no target metric")
                statement = pg_insert(DataPoint).values(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_id=source.id,
                    metric_type=mapping.target_metric_type,
                    timestamp=row.timestamp,
                    value=value,
                    metadata_=metadata,
                    idempotency_key=idempotency_key(
                        tenant_id,
                        row.idempotency_source_id or source.id,
                        mapping.target_metric_type,
                        row.timestamp,
                    ),
                ).on_conflict_do_nothing(
                    index_elements=["tenant_id", "idempotency_key", "timestamp"]
                )
                inserted = (await session.execute(statement)).rowcount or 0
                if inserted:
                    accepted += 1
                    await update_rollups_for_point(
                        session,
                        tenant_id=tenant_id,
                        source_id=source.id,
                        metric_type=mapping.target_metric_type,
                        timestamp=row.timestamp,
                        value=value,
                        metadata=metadata,
                    )
                else:
                    duplicates += 1
                row.status = "promoted"
            row.resolved_at = now
            row.resolution_rule_id = rule.id
        processed += len(rows)

    run.status = "success"
    run.points_received = processed
    run.points_accepted = accepted
    run.points_duplicate = duplicates
    run.message = (
        f"Replayed {accepted} value(s), skipped {duplicates} duplicate(s), "
        f"discarded {discarded} value(s)."
    )[:512]
    run.finished_at = datetime.now(timezone.utc)
    return {
        "replayed": processed,
        "accepted": accepted,
        "duplicates": duplicates,
        "discarded": discarded,
        "sync_run_id": run.id,
    }


@app.get("/api/v1/data/quality/quarantine")
async def list_quarantined_metrics(
    session: AsyncSession = Depends(get_session),
):
    """List unresolved metrics and tenant-scoped capacity warnings.

    The response exposes counts and stable warning codes only. Held values remain
    inaccessible through this summary endpoint, while the capacity data lets the
    dashboard warn before the bounded quarantine can refuse a new point.
    """
    tenant_id = get_current_tenant_id()
    result = await session.execute(
        select(QuarantinedDataPoint, DataSource.display_name)
        .join(
            DataSource,
            (DataSource.id == QuarantinedDataPoint.source_id)
            & (DataSource.tenant_id == tenant_id),
        )
        .where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.status == "active",
        )
        .order_by(QuarantinedDataPoint.last_seen_at.desc())
        .limit(MAX_QUARANTINE_LIST_ROWS)
    )
    rules_result = await session.execute(
        select(MetricMappingRule).where(MetricMappingRule.tenant_id == tenant_id)
    )
    rules = {
        (rule.source_id, rule.raw_metric_type): rule
        for rule in rules_result.scalars()
    }

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row, display_name in result.all():
        key = (row.source_id, row.raw_metric_type)
        item = grouped.get(key)
        if item is None:
            rule = rules.get(key)
            item = {
                "source_id": row.source_id,
                "source_type": row.source_type,
                "connector_name": display_name,
                "raw_metric_type": row.raw_metric_type,
                "points": 0,
                "seen": 0,
                "units": (row.metadata_ or {}).get("units") or None,
                "first_seen_at": row.first_seen_at.isoformat(),
                "last_seen_at": row.last_seen_at.isoformat(),
                "action": rule.action if rule else None,
            }
            grouped[key] = item
        item["points"] += 1
        item["seen"] += row.seen_count
        item["first_seen_at"] = min(item["first_seen_at"], row.first_seen_at.isoformat())
        item["last_seen_at"] = max(item["last_seen_at"], row.last_seen_at.isoformat())
        if not item["units"]:
            item["units"] = (row.metadata_ or {}).get("units") or None

    active_counts_result = await session.execute(
        select(
            QuarantinedDataPoint.source_id,
            func.count(QuarantinedDataPoint.id),
            func.count(func.distinct(QuarantinedDataPoint.raw_metric_type)),
        )
        .where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.status == "active",
        )
        .group_by(QuarantinedDataPoint.source_id)
    )
    active_counts = {
        source_id: (int(row_count), int(name_count))
        for source_id, row_count, name_count in active_counts_result.all()
    }

    refusal_counts_result = await session.execute(
        select(
            QuarantineRefusal.source_id,
            func.coalesce(func.sum(QuarantineRefusal.occurrences), 0),
        )
        .where(QuarantineRefusal.tenant_id == tenant_id)
        .group_by(QuarantineRefusal.source_id)
    )
    refusal_counts = {
        source_id: int(occurrences)
        for source_id, occurrences in refusal_counts_result.all()
    }

    capacity_source_ids = set(active_counts) | set(refusal_counts)
    capacity: list[dict[str, Any]] = []
    if capacity_source_ids:
        sources_result = await session.execute(
            select(DataSource).where(
                DataSource.tenant_id == tenant_id,
                DataSource.id.in_(capacity_source_ids),
            )
        )
        for source in sources_result.scalars():
            active_rows, active_names = active_counts.get(source.id, (0, 0))
            refused_occurrences = refusal_counts.get(source.id, 0)
            warning_code, limiting_dimension = _quarantine_capacity_warning(
                active_rows=active_rows,
                active_names=active_names,
                refused_occurrences=refused_occurrences,
            )
            capacity.append(
                {
                    "source_id": source.id,
                    "source_type": source.source_type,
                    "connector_name": source.display_name,
                    "active_rows": active_rows,
                    "max_rows": MAX_QUARANTINED_ROWS,
                    "active_names": active_names,
                    "max_names": MAX_QUARANTINED_NAMES,
                    "usage_percent": round(
                        max(
                            active_rows / MAX_QUARANTINED_ROWS,
                            active_names / MAX_QUARANTINED_NAMES,
                        )
                        * 100,
                        1,
                    ),
                    "limiting_dimension": limiting_dimension,
                    "refused_occurrences": refused_occurrences,
                    "warning_code": warning_code,
                }
            )

    return {
        "tenant_id": tenant_id,
        "metrics": list(grouped.values()),
        "capacity": capacity,
    }


@app.get("/api/v1/data/quality/mapping-rules")
async def list_metric_mapping_rules(
    session: AsyncSession = Depends(get_session),
):
    """List connector rules and their current unresolved point counts."""
    tenant_id = get_current_tenant_id()
    result = await session.execute(
        select(MetricMappingRule, DataSource.display_name)
        .join(
            DataSource,
            (DataSource.id == MetricMappingRule.source_id)
            & (DataSource.tenant_id == tenant_id),
        )
        .where(MetricMappingRule.tenant_id == tenant_id)
        .order_by(MetricMappingRule.updated_at.desc())
    )
    counts_result = await session.execute(
        select(
            QuarantinedDataPoint.source_id,
            QuarantinedDataPoint.raw_metric_type,
            func.count(QuarantinedDataPoint.id),
        )
        .where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.status == "active",
        )
        .group_by(QuarantinedDataPoint.source_id, QuarantinedDataPoint.raw_metric_type)
    )
    counts = {(source_id, raw): count for source_id, raw, count in counts_result.all()}
    return {
        "tenant_id": tenant_id,
        "rules": [
            {
                "id": rule.id,
                "source_id": rule.source_id,
                "source_type": rule.source_type,
                "connector_name": display_name,
                "raw_metric_type": rule.raw_metric_type,
                "action": rule.action,
                "target_metric_type": rule.target_metric_type,
                "source_unit": rule.source_unit,
                "target_unit": rule.target_unit,
                "aggregation": rule.aggregation,
                "cadence": rule.cadence,
                "keep_indefinitely": rule.retention_days is None,
                "unresolved_points": counts.get((rule.source_id, rule.raw_metric_type), 0),
                "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
            }
            for rule, display_name in result.all()
        ],
    }


@app.get("/api/v1/data/quality/mapping-summary")
async def summarize_metric_mapping_rules(
    session: AsyncSession = Depends(get_session),
):
    """Summarize repeated tenant decisions without returning values or identifiers."""
    tenant_id = get_current_tenant_id()
    result = await session.execute(
        select(MetricMappingRule).where(MetricMappingRule.tenant_id == tenant_id)
    )
    counts_result = await session.execute(
        select(
            QuarantinedDataPoint.raw_metric_type,
            func.count(QuarantinedDataPoint.id),
        )
        .where(
            QuarantinedDataPoint.tenant_id == tenant_id,
            QuarantinedDataPoint.status == "active",
        )
        .group_by(QuarantinedDataPoint.raw_metric_type)
    )
    unresolved = {raw: count for raw, count in counts_result.all()}
    summary: dict[str, dict[str, Any]] = {}
    for rule in result.scalars():
        item = summary.setdefault(
            rule.raw_metric_type,
            {"raw_metric_type": rule.raw_metric_type, "connector_count": 0, "actions": {}, "unresolved_points": 0},
        )
        item["connector_count"] += 1
        item["actions"][rule.action] = item["actions"].get(rule.action, 0) + 1
        item["unresolved_points"] = unresolved.get(rule.raw_metric_type, 0)
    # This is the registry-feedback view: names and counts only, with no connector
    # identifiers, tenant identifiers, held values or other personal data.
    return {"metrics": list(summary.values())}


@app.post("/api/v1/data/quality/mapping-rules", status_code=202)
async def save_metric_mapping_rule(
    request: MetricMappingRequest,
    principal: Principal = Depends(require_role("owner", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """Save one mapping decision and replay its held points atomically."""
    tenant_id = principal.tenant_id
    source_result = await session.execute(
        select(DataSource)
        .where(
            DataSource.id == request.source_id,
            DataSource.tenant_id == tenant_id,
        )
        .with_for_update()
    )
    source = source_result.scalars().first()
    if source is None:
        raise HTTPException(status_code=404, detail="Connector not configured")

    try:
        canonical_metric_type(request.raw_metric_type)
    except UnknownMetricTypeError:
        pass
    else:
        raise HTTPException(
            status_code=422,
            detail="A catalogued or namespaced metric cannot be redefined by a tenant rule.",
        )

    try:
        mapping = validate_mapping(
            raw_metric_type=request.raw_metric_type,
            action=request.action,
            target_metric_type=request.target_metric_type,
            source_unit=request.source_unit,
            target_unit=request.target_unit,
            aggregation=request.aggregation,
            cadence=request.cadence,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if request.keep_indefinitely and request.action != "keep":
        raise HTTPException(
            status_code=422,
            detail="keep_indefinitely is only valid for a keep rule.",
        )

    result = await session.execute(
        select(MetricMappingRule).where(
            MetricMappingRule.tenant_id == tenant_id,
            MetricMappingRule.source_id == source.id,
            MetricMappingRule.raw_metric_type == mapping.raw_metric_type,
        )
    )
    rule = result.scalars().first()
    if mapping.action == "adopt" and mapping.target_metric_type is not None:
        # Serialize tenant-local custom-definition changes so two connectors cannot
        # concurrently give the same custom name different meanings.
        await session.execute(
            select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
        )
        conflict_filters = [
            MetricMappingRule.tenant_id == tenant_id,
            MetricMappingRule.action == "adopt",
            MetricMappingRule.target_metric_type == mapping.target_metric_type,
            or_(
                MetricMappingRule.source_unit != mapping.source_unit.value,
                MetricMappingRule.target_unit != mapping.target_unit.value,
                MetricMappingRule.aggregation != mapping.aggregation.value,
                MetricMappingRule.cadence != mapping.cadence.value,
            ),
        ]
        if rule is not None:
            conflict_filters.append(MetricMappingRule.id != rule.id)
        conflicting = await session.execute(
            select(MetricMappingRule.id).where(*conflict_filters)
            .limit(1)
        )
        if conflicting.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="This custom metric name already has a different tenant definition.",
            )
    now = datetime.now(timezone.utc)
    values = {
        "source_type": source.source_type,
        "action": mapping.action,
        "target_metric_type": mapping.target_metric_type,
        "source_unit": mapping.source_unit.value if mapping.source_unit else None,
        "target_unit": mapping.target_unit.value if mapping.target_unit else None,
        "aggregation": mapping.aggregation.value if mapping.aggregation else None,
        "cadence": mapping.cadence.value if mapping.cadence else None,
        "retention_days": None if request.keep_indefinitely else 30,
        "updated_at": now,
    }
    if rule is None:
        rule = MetricMappingRule(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            source_id=source.id,
            raw_metric_type=mapping.raw_metric_type,
            created_at=now,
            **values,
        )
        session.add(rule)
    else:
        for key, value in values.items():
            setattr(rule, key, value)

    replay = {"replayed": 0, "accepted": 0, "duplicates": 0, "discarded": 0, "sync_run_id": None}
    if mapping.action in {"map", "adopt", "discard"}:
        replay = await _replay_quarantined_rows(
            session,
            tenant_id=tenant_id,
            source=source,
            rule=rule,
            mapping=mapping,
        )
    await session.commit()
    return {
        "tenant_id": tenant_id,
        "source_id": source.id,
        "raw_metric_type": mapping.raw_metric_type,
        "action": mapping.action,
        **replay,
    }


@app.get("/api/v1/data/quality/quarantine-refusals")
async def list_quarantine_refusals(
    session: AsyncSession = Depends(get_session),
):
    """Show bounded-queue refusals without exposing any refused point value."""
    tenant_id = get_current_tenant_id()
    result = await session.execute(
        select(QuarantineRefusal, DataSource.display_name)
        .join(
            DataSource,
            (DataSource.id == QuarantineRefusal.source_id)
            & (DataSource.tenant_id == tenant_id),
        )
        .where(QuarantineRefusal.tenant_id == tenant_id)
        .order_by(QuarantineRefusal.last_seen_at.desc())
        .limit(500)
    )
    return {
        "tenant_id": tenant_id,
        "refusals": [
            {
                "source_id": row.source_id,
                "source_type": row.source_type,
                "connector_name": display_name,
                "raw_metric_type": row.raw_metric_type,
                "reason": row.reason,
                "occurrences": row.occurrences,
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row, display_name in result.all()
        ],
    }


class OpenSyncRunRequest(BaseModel):
    """Start an import that Core did not schedule."""

    trigger: Literal["push", "upload"] = Field(
        "push", description="How this import was started"
    )
    request_id: str | None = Field(None, max_length=128)
    # Known up front for a file upload, unknowable for a webhook. Where it is
    # unknown the interface counts rather than showing an invented percentage.
    points_expected: int | None = Field(None, ge=0)
    provider_window_start: datetime | None = None
    provider_window_end: datetime | None = None
    provider_exported_at: datetime | None = None
    message: str | None = Field(None, max_length=512)
    code: str | None = Field(None, max_length=64)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


class UpdateSyncRunProgressRequest(BaseModel):
    """Update known progress without finishing an import run."""

    points_expected: int | None = Field(None, ge=0)
    points_received: int | None = Field(None, ge=0)
    points_rejected: int | None = Field(None, ge=0)
    unsupported_fields: int | None = Field(None, ge=0)
    backlog: int | None = Field(None, ge=0)
    provider_window_start: datetime | None = None
    provider_window_end: datetime | None = None
    provider_exported_at: datetime | None = None
    message: str | None = Field(None, max_length=512)
    code: str | None = Field(None, max_length=64)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict)


@app.post("/api/v1/internal/data/sources/{source_ref}/sync-runs", status_code=201)
async def open_sync_run_internal(
    source_ref: str,
    req: OpenSyncRunRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """Open a run for an import nobody planned.

    Scheduled and manual imports get their `SyncRun` from `plan_and_enqueue_sync`.
    Pushed data had none at all: the Apple Health webhook wrote data points with no
    `sync_run_id`, so `_tally` never counted them and the whole import was invisible
    in the history — there was nothing to show a progress display, and no record
    that it had happened.
    """
    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    now = datetime.now(timezone.utc)
    run = SyncRun(
        tenant_id=tenant_id,
        source_id=source.id,
        source_type=source.source_type,
        request_id=req.request_id or get_current_request_id() or str(uuid.uuid4()),
        mode="force",
        trigger=req.trigger,
        status="running",
        window_start=None,
        window_end=None,
        points_expected=req.points_expected,
        points_received=0,
        provider_window_start=req.provider_window_start,
        provider_window_end=req.provider_window_end,
        provider_exported_at=req.provider_exported_at,
        message=(req.message or "")[:512] or None,
        message_code=req.code or "sync_running",
        message_params=req.params,
        started_at=now,
    )
    session.add(run)

    config = dict(source.config or {})
    config["sync_status"] = "running"
    config["last_sync_message"] = req.message or "Import running."
    source.config = config

    await session.commit()

    return {
        "sync_run_id": run.id,
        "source_id": source.id,
        "source_type": source.source_type,
        "tenant_id": tenant_id,
    }


@app.post("/api/v1/internal/data/sources/{source_ref}/sync-runs/{sync_run_id}/progress")
async def update_sync_run_progress_internal(
    source_ref: str,
    sync_run_id: str,
    req: UpdateSyncRunProgressRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """Record an expected count while an importer is still running."""
    source = await _resolve_source_ref(session, tenant_id, source_ref)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    result = await session.execute(
        select(SyncRun).where(
            SyncRun.id == sync_run_id,
            SyncRun.tenant_id == tenant_id,
            SyncRun.source_id == source.id,
        )
    )
    run = result.scalars().first()
    if not run:
        raise HTTPException(status_code=404, detail="Sync run not found")
    if run.finished_at is not None:
        raise HTTPException(status_code=409, detail="Sync run is already finished")

    if req.points_expected is not None:
        run.points_expected = req.points_expected
    if req.points_received is not None:
        run.points_received = req.points_received
    if req.points_rejected is not None:
        run.points_rejected = req.points_rejected
    if req.unsupported_fields is not None:
        run.unsupported_fields = req.unsupported_fields
    if req.backlog is not None:
        run.backlog_at_end = req.backlog
    if req.provider_window_start is not None:
        run.provider_window_start = req.provider_window_start
    if req.provider_window_end is not None:
        run.provider_window_end = req.provider_window_end
    if req.provider_exported_at is not None:
        run.provider_exported_at = req.provider_exported_at
    if run.status == "queued":
        run.status = "running"
        config = dict(source.config or {})
        config["sync_status"] = "running"
        source.config = config
    if req.message:
        run.message = req.message[:512]
    if req.code:
        run.message_code = req.code
        run.message_params = req.params
    await session.commit()
    return {"status": "ok", "sync_run_id": run.id}


@app.post("/api/v1/internal/data/sources/{source_ref}/status")
async def update_connector_status_internal(
    source_ref: str,
    req: UpdateConnectorStatusRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """Importers report the outcome of a sync here.

    Closing out the ``SyncRun`` is what makes the next window adaptive: only a run
    that reached ``success`` is allowed to move the resume point forward.

    Resolved through `_resolve_source_ref`, which also removes a `scalar_one_or_none`
    that would have raised `MultipleResultsFound` -- a 500 -- the moment a tenant
    held two connectors of one type.
    """
    ds = await _resolve_source_ref(session, tenant_id, source_ref)
    if not ds:
        raise HTTPException(status_code=404, detail="Connector not configured")

    cfg = dict(ds.config or {})
    cfg["sync_status"] = req.sync_status
    cfg["last_sync_message"] = req.last_sync_message
    ds.config = cfg

    if req.sync_run_id:
        run_query = select(SyncRun).where(
            SyncRun.id == req.sync_run_id,
            SyncRun.tenant_id == tenant_id,
        )
        run_query = run_query.where(SyncRun.source_id == ds.id)
        run_res = await session.execute(run_query)
        run = run_res.scalars().first()
        if run:
            if req.points_received is not None:
                run.points_received = req.points_received
                if run.points_expected is None and req.sync_status in {"idle", "success", "ok"}:
                    run.points_expected = req.points_received
            if req.points_rejected is not None:
                run.points_rejected = req.points_rejected
            if req.unsupported_fields is not None:
                run.unsupported_fields = req.unsupported_fields
            if req.backlog is not None:
                run.backlog_at_end = req.backlog
            if req.provider_window_start is not None:
                run.provider_window_start = req.provider_window_start
            if req.provider_window_end is not None:
                run.provider_window_end = req.provider_window_end
            if req.provider_exported_at is not None:
                run.provider_exported_at = req.provider_exported_at

            now = datetime.now(timezone.utc)
            if req.sync_status in {"idle", "success", "ok"}:
                run.message = (
                    f"{req.last_sync_message[:450]} Core is loading the published data."
                )[:512]
                run.status = "loading"
                run.message_code = req.code or "sync_loading"
                run.message_params = req.params
                run.finished_at = None
                if (
                    run.points_expected is not None
                    and run.points_processed >= run.points_expected
                ):
                    run.status = "success"
                    run.finished_at = now
                    run.message = "Core loaded all published data points."
                    run.message_code = "core_loaded"
                    run.message_params = {}
                    cfg = dict(ds.config or {})
                    cfg["sync_status"] = "idle"
                    cfg["last_sync_at"] = now.isoformat()
                    cfg["last_sync_message"] = run.message
                    ds.config = cfg
                else:
                    cfg = dict(ds.config or {})
                    cfg["sync_status"] = "loading"
                    cfg["last_sync_message"] = run.message
                    ds.config = cfg
            elif req.sync_status in {"queued", "running", "loading"}:
                run.status = req.sync_status
                run.message = req.last_sync_message[:512]
                run.message_code = req.code or "sync_queued"
                run.message_params = req.params
                run.finished_at = None
            else:
                run.status = req.sync_status
                run.message = req.last_sync_message[:512]
                run.message_code = req.code or "sync_failed"
                run.message_params = req.params
                run.finished_at = now

    await session.commit()
    return {"status": "ok"}


@app.delete("/api/v1/data/wipe")
async def wipe_tenant_data_points(
    principal: Principal = Depends(require_role("owner", "admin")),
    session: AsyncSession = Depends(get_session),
):
    """1-Click deletion of all ingested and held point values for current tenant."""
    tenant_id = principal.tenant_id
    stmt = delete(DataPoint).where(DataPoint.tenant_id == tenant_id)
    result = await session.execute(stmt)
    rollup_result = await session.execute(
        delete(MetricRollup).where(MetricRollup.tenant_id == tenant_id)
    )
    quarantine_result = await session.execute(
        delete(QuarantinedDataPoint).where(QuarantinedDataPoint.tenant_id == tenant_id)
    )
    await session.commit()
    # An empty workspace holds no point outside a rollup, so the first summary
    # after a wipe has nothing to prove by scanning for one.
    remember_day_rollup_coverage(tenant_id)

    return {
        "status": "wiped",
        "deleted_count": (result.rowcount or 0) + (quarantine_result.rowcount or 0),
        "deleted_rollup_count": rollup_result.rowcount or 0,
        "message": (
            f"Successfully deleted {(result.rowcount or 0) + (quarantine_result.rowcount or 0)} "
            "data points for tenant."
        ),
    }


@app.delete("/api/v1/data/account")
async def delete_tenant_account(
    principal: Principal = Depends(require_role("owner")),
    session: AsyncSession = Depends(get_session),
):
    """1-Click full account wipe (data points, data sources, tenant shares)."""
    tenant_id = principal.tenant_id
    dp_res = await session.execute(delete(DataPoint).where(DataPoint.tenant_id == tenant_id))
    ds_res = await session.execute(delete(DataSource).where(DataSource.tenant_id == tenant_id))
    # Cross-tenant sharing was withdrawn before it could read anything, so nothing
    # writes `tenant_shares` any more. The delete stays: an installation that ran an
    # earlier version has rows in there, and Art. 17 covers those too.
    ts_res = await session.execute(
        delete(TenantShare).where(
            or_(
                TenantShare.grantor_tenant_id == tenant_id,
                TenantShare.grantee_tenant_id == tenant_id,
            )
        )
    )
    await session.commit()

    return {
        "status": "deleted",
        "deleted_data_points": dp_res.rowcount,
        "deleted_sources": ds_res.rowcount,
        "deleted_shares": ts_res.rowcount,
        "message": "Full account data wiped successfully.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
