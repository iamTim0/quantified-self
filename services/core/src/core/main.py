# ruff: noqa: B008
"""Core Data Service FastAPI Entry Point.

Serves REST endpoints for time-series metric data queries, metric type listing, summary statistics,
and secure encrypted connector configuration management.

Enforces multi-tenant isolation via TenantMiddleware & contextvars.
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.analytics import detect_daily_gaps, find_cross_source_conflicts, pearson_pairs
from core.db.models import (
    ApiKey,
    DataPoint,
    DataSource,
    ExplorerView,
    RefreshToken,
    RevokedAccessToken,
    SyncRun,
    Tenant,
    TenantShare,
    User,
)
from core.db.session import get_session
from core.db.tenant import get_current_tenant_id
from core.events.consumer import start_consumer
from core.insights import (
    Provenance,
    build_daily_series,
    compare_periods,
    correlation_pairs,
    detect_anomalies,
    lagged_correlations,
    series_quality,
    trend_for_metric,
    weekday_pattern,
)
from core.ingest_planning import (
    BucketCount,
    TimeRange,
    analyse_coverage,
    compute_sync_window,
    plan_import,
)
from core.security.auth import (
    AuthenticationMiddleware,
    Principal,
    get_current_principal,
    require_role,
)
from core.security.crypto import (
    DecryptionError,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)
from core.security.tokens import (
    TokenError,
    create_access_token,
    create_api_key,
    create_refresh_token,
    decode_access_token,
    hash_token,
)
from core.tracing import (
    RequestTracingMiddleware,
    setup_tracing_logger,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# SECURITY H3: Constrain source_type to known connectors
ValidSourceType = Literal[
    "oura", "whoop", "apple_health", "fitbit", "garmin", "strava", "yazio",
    "dawarich", "streak", "home_assistant", "weather", "calendar",
]
ValidStatus = Literal["active", "inactive"]

# Connectors that receive pushed data. They authenticate inbound requests with
# tenant-bound API keys (see the api_keys table), so they hold no provider
# credential of their own and must be configurable without one.
PUSH_SOURCE_TYPES = {"apple_health", "streak"}


class ManualDataPointRequest(BaseModel):
    """Validated manual or visually mapped import row."""

    source_id: str
    metric_type: str = Field(..., min_length=1, max_length=128)
    timestamp: datetime
    value: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class CreateShareRequest(BaseModel):
    grantee_email: str = Field(..., description="Email of the user to share data with")
    scope: str = Field("read_all", description="Scope of shared data e.g. read_all or read_metric:sleep_score")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "testing", False):
        yield
        return
    try:
        nc = await start_consumer()
        app.state.nats_client = nc
        yield
        await nc.close()
    except Exception:
        yield



setup_tracing_logger("qs-core")
logger = logging.getLogger(__name__)

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
async def health_check():
    return {"status": "ok", "service": settings.SERVICE_NAME}


# ─── Auth Endpoints ──────────────────────────────────────────


async def _issue_session(
    session: AsyncSession,
    *,
    user_id: str,
    tenant_id: str,
    email: str,
    role: str,
) -> dict[str, Any]:
    """Mint an access/refresh pair and persist the refresh token's hash.

    Only the hash is stored, so a database disclosure cannot be replayed against
    the API.
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

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_at": access_expires.isoformat(),
        "expires_in": int((access_expires - datetime.now(timezone.utc)).total_seconds()),
    }


async def _revoke_all_sessions(
    session: AsyncSession, *, tenant_id: str, user_id: str, reason: str
) -> None:
    """Invalidate every refresh token for a user (password change, key compromise)."""
    await session.execute(
        sa_update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.tenant_id == tenant_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    logger.info(
        "Revoked all refresh tokens for user=%s tenant=%s reason=%s",
        user_id,
        tenant_id,
        reason,
    )


@app.post("/api/v1/auth/signup")
async def signup(
    req: UserSignupRequest,
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
        session, user_id=user_id, tenant_id=tenant_id, email=req.email, role="owner"
    )

    return {
        "status": "success",
        **tokens,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "email": req.email,
        "name": req.name,
        "role": "owner",
    }


@app.post("/api/v1/auth/login")
async def login(
    req: UserLoginRequest,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(User).where(User.email == req.email)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    tokens = await _issue_session(
        session,
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
    }


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=16, max_length=512)


@app.post("/api/v1/auth/refresh")
async def refresh_session(
    req: RefreshRequest,
    session: AsyncSession = Depends(get_session),
):
    """Exchange a refresh token for a fresh access/refresh pair.

    Rotation is single-use. Presenting a token that has already been rotated is
    treated as replay: the entire chain for that user is revoked rather than
    silently issuing another session.
    """
    presented_hash = hash_token(req.refresh_token)
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

    user_res = await session.execute(select(User).where(User.id == stored.user_id))
    user = user_res.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

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

    return {
        "status": "success",
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_at": access_expires.isoformat(),
        "expires_in": int((access_expires - now).total_seconds()),
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
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

    if auth_header.startswith("Bearer "):
        try:
            claims = decode_access_token(auth_header[7:].strip())
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

    if body.refresh_token:
        await session.execute(
            sa_update(RefreshToken)
            .where(
                RefreshToken.token_hash == hash_token(body.refresh_token),
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
    return Response(status_code=204)


@app.get("/api/v1/auth/me")
async def get_current_user(session: AsyncSession = Depends(get_session)):
    """Return the authenticated identity. Used by the dashboard to validate a session."""
    principal = get_current_principal()
    res = await session.execute(
        select(User).where(
            User.id == principal.user_id, User.tenant_id == principal.tenant_id
        )
    )
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists")

    return {
        "user_id": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
    }


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, description="Current user password")
    new_password: str = Field(..., min_length=6, max_length=128, description="New password")


@app.post("/api/v1/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
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
        raise HTTPException(status_code=404, detail="Benutzerkonto nicht gefunden.")

    if not pwd_context.verify(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort ist falsch.")

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

    return {
        "status": "success",
        "message": "Passwort wurde erfolgreich geändert. Bitte melde dich erneut an.",
        "sessions_revoked": True,
    }


# ─── Tenant Sharing Endpoints ───────────────────────────────

@app.post("/api/v1/data/shares")
async def create_share(
    req: CreateShareRequest,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = get_current_tenant_id()

    stmt = select(User).where(User.email == req.grantee_email)
    res = await session.execute(stmt)
    grantee_user = res.scalar_one_or_none()

    if not grantee_user:
        raise HTTPException(status_code=404, detail="Target user not found")

    if grantee_user.tenant_id == tenant_id:
        raise HTTPException(status_code=400, detail="Cannot share with yourself or users in your own tenant")

    share_id = str(uuid.uuid4())
    new_share = TenantShare(
        id=share_id,
        grantor_tenant_id=tenant_id,
        grantee_tenant_id=grantee_user.tenant_id,
        scope=req.scope,
    )
    session.add(new_share)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Share already exists") from None

    return {"message": "Share created", "share_id": share_id, "grantee_tenant_id": grantee_user.tenant_id}


@app.get("/api/v1/data/shares")
async def list_shares(session: AsyncSession = Depends(get_session)):
    tenant_id = get_current_tenant_id()

    stmt = select(TenantShare).where(TenantShare.grantor_tenant_id == tenant_id)
    res = await session.execute(stmt)
    granted_by_me = res.scalars().all()

    stmt_rec = select(TenantShare).where(TenantShare.grantee_tenant_id == tenant_id)
    res_rec = await session.execute(stmt_rec)
    granted_to_me = res_rec.scalars().all()

    return {
        "granted_by_me": [
            {"id": s.id, "grantee_tenant_id": s.grantee_tenant_id, "scope": s.scope, "created_at": s.created_at.isoformat()}
            for s in granted_by_me
        ],
        "granted_to_me": [
            {"id": s.id, "grantor_tenant_id": s.grantor_tenant_id, "scope": s.scope, "created_at": s.created_at.isoformat()}
            for s in granted_to_me
        ],
    }


@app.delete("/api/v1/data/shares/{share_id}")
async def revoke_share(
    share_id: str,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = get_current_tenant_id()

    stmt = select(TenantShare).where(
        TenantShare.id == share_id,
        TenantShare.grantor_tenant_id == tenant_id,
    )
    res = await session.execute(stmt)
    share = res.scalar_one_or_none()

    if not share:
        raise HTTPException(status_code=404, detail="Share not found or access denied")

    await session.delete(share)
    await session.commit()

    return {"status": "success", "message": "Share revoked"}


# ─── Core Metric Endpoints ───────────────────────────────────

@app.get("/api/v1/data/metrics")
async def query_metrics(
    metric_type: str | None = Query(None, description="Filter by metric type (e.g. sleep_score, steps)"),
    start_time: str | None = Query(None, description="ISO start timestamp"),
    end_time: str | None = Query(None, description="ISO end timestamp"),
    limit: int = Query(100, ge=1, le=1000, description="Max data points to return"),
    sort: Literal["asc", "desc"] = Query("asc", description="Sort by timestamp"),
    session: AsyncSession = Depends(get_session),
):
    """Query time-series metric data points for the authenticated tenant."""
    tenant_id = get_current_tenant_id()
    stmt = select(DataPoint).where(DataPoint.tenant_id == tenant_id)

    if metric_type:
        stmt = stmt.where(DataPoint.metric_type == metric_type)

    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
            stmt = stmt.where(DataPoint.timestamp >= start_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_time ISO format") from None

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
            stmt = stmt.where(DataPoint.timestamp <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_time ISO format") from None

    stmt = stmt.order_by(
        DataPoint.timestamp.desc() if sort == "desc" else DataPoint.timestamp.asc()
    ).limit(limit)
    res = await session.execute(stmt)
    points = res.scalars().all()

    return {
        "tenant_id": tenant_id,
        "count": len(points),
        "data_points": [
            {
                "id": p.id,
                "metric_type": p.metric_type,
                "timestamp": p.timestamp.isoformat(),
                "value": p.value,
                "metadata": p.metadata_,
                "idempotency_key": p.idempotency_key,
            }
            for p in points
        ],
    }


@app.get("/api/v1/data/metrics/types")
async def list_metric_types(
    session: AsyncSession = Depends(get_session),
):
    """List all distinct metric types stored for the authenticated tenant."""
    tenant_id = get_current_tenant_id()
    stmt = (
        select(distinct(DataPoint.metric_type))
        .where(DataPoint.tenant_id == tenant_id)
        .order_by(DataPoint.metric_type.asc())
    )
    res = await session.execute(stmt)
    metric_types = res.scalars().all()

    return {
        "tenant_id": tenant_id,
        "metric_types": list(metric_types),
    }


@app.get("/api/v1/data/metrics/summary")
async def get_metrics_summary(
    session: AsyncSession = Depends(get_session),
):
    """Get summary statistics (latest, average, min, max) for all metric types of the tenant."""
    tenant_id = get_current_tenant_id()
    stmt = (
        select(
            DataPoint.metric_type,
            func.count(DataPoint.id).label("count"),
            func.avg(DataPoint.value).label("avg_value"),
            func.min(DataPoint.value).label("min_value"),
            func.max(DataPoint.value).label("max_value"),
            func.max(DataPoint.timestamp).label("latest_timestamp"),
        )
        .where(DataPoint.tenant_id == tenant_id)
        .group_by(DataPoint.metric_type)
        .order_by(DataPoint.metric_type.asc())
    )

    res = await session.execute(stmt)
    rows = res.all()

    summary = {}
    for row in rows:
        summary[row.metric_type] = {
            "count": row.count,
            "average": round(float(row.avg_value), 1) if row.avg_value is not None else None,
            "min": round(float(row.min_value), 1) if row.min_value is not None else None,
            "max": round(float(row.max_value), 1) if row.max_value is not None else None,
            "latest_timestamp": row.latest_timestamp.isoformat() if row.latest_timestamp else None,
        }

    return {
        "tenant_id": tenant_id,
        "metrics": summary,
    }


@app.get("/api/v1/data/quality/gaps")
async def get_data_gaps(
    start_date: date = Query(...),
    end_date: date = Query(...),
    session: AsyncSession = Depends(get_session),
):
    """Detect missing tracking days using only the authenticated tenant's timeline."""
    tenant_id = get_current_tenant_id()
    if end_date < start_date or (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Date range must contain at most 367 ordered days")
    result = await session.execute(
        select(DataPoint.metric_type, DataPoint.timestamp).where(
            DataPoint.tenant_id == tenant_id,
            DataPoint.timestamp >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
            DataPoint.timestamp < datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
        )
    )
    gaps = detect_daily_gaps(result.all(), start_date, end_date)
    return {"tenant_id": tenant_id, "gaps": gaps, "missing_count": sum(len(g["missing_dates"]) for g in gaps)}


@app.post("/api/v1/data/import", status_code=202)
async def import_mapped_rows(
    request: BatchImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Persist visually mapped rows with exact-once tenant-scoped semantics."""
    tenant_id = get_current_tenant_id()
    source_ids = {row.source_id for row in request.rows}
    known = await session.execute(
        select(DataSource.id).where(DataSource.tenant_id == tenant_id, DataSource.id.in_(source_ids))
    )
    if set(known.scalars()) != source_ids:
        raise HTTPException(status_code=400, detail="Every source_id must belong to the authenticated tenant")
    accepted = 0
    for row in request.rows:
        normalized_timestamp = row.timestamp.astimezone(timezone.utc)
        key = __import__("hashlib").sha256(
            f"{tenant_id}:{row.source_id}:{row.metric_type}:{normalized_timestamp.isoformat()}".encode()
        ).hexdigest()
        statement = insert(DataPoint).values(
            id=str(uuid.uuid4()), tenant_id=tenant_id, source_id=row.source_id,
            metric_type=row.metric_type, timestamp=normalized_timestamp, value=row.value,
            metadata_=row.metadata, idempotency_key=key,
        ).on_conflict_do_nothing(
            index_elements=["tenant_id", "idempotency_key", "timestamp"]
        )
        result = await session.execute(statement)
        accepted += result.rowcount or 0
    await session.commit()
    return {"tenant_id": tenant_id, "submitted": len(request.rows), "accepted": accepted}


@app.get("/api/v1/data/quality/conflicts")
async def get_cross_source_conflicts(
    tolerance: float = Query(0.05, ge=0, le=1),
    session: AsyncSession = Depends(get_session),
):
    """Return ambiguous same-day values across tenant-owned sources for user review."""
    tenant_id = get_current_tenant_id()
    rows = await session.execute(
        select(DataPoint).where(DataPoint.tenant_id == tenant_id).order_by(DataPoint.timestamp.desc()).limit(5000)
    )
    points = [
        {"id": point.id, "source_id": point.source_id, "metric_type": point.metric_type,
         "timestamp": point.timestamp, "value": point.value}
        for point in rows.scalars()
    ]
    conflicts = find_cross_source_conflicts(points, tolerance)
    for conflict in conflicts:
        for candidate in conflict["candidates"]:
            candidate["timestamp"] = candidate["timestamp"].isoformat()
    return {"tenant_id": tenant_id, "conflicts": conflicts}


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


@app.get("/api/v1/data/analysis/insights")
async def get_insights(
    days: int = Query(90, ge=14, le=365, description="Analysis window in days"),
    metric_type: str | None = Query(None, description="Restrict trends/anomalies to one metric"),
    min_strength: float = Query(0.0, ge=0.0, le=1.0, description="Minimum |coefficient|"),
    compare_to_previous: bool = Query(
        False, description="Also compare the window with the equally long window before it"
    ),
    session: AsyncSession = Depends(get_session),
):
    """Full analysis bundle for the dashboard, with provenance on every result.

    One endpoint rather than several because the analyses share the same aligned
    daily series; recomputing it per call would be wasteful and could return
    mutually inconsistent windows.

    Everything reported is an *association*. Nothing here establishes causation, and
    analyses whose input is too thin are omitted rather than shown weakly.
    """
    tenant_id = get_current_tenant_id()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)

    rows = await session.execute(
        select(DataPoint.metric_type, DataPoint.timestamp, DataPoint.value)
        .where(
            DataPoint.tenant_id == tenant_id,
            DataPoint.value.is_not(None),
            DataPoint.timestamp >= window_start,
            DataPoint.timestamp <= now,
        )
        .order_by(DataPoint.timestamp)
    )
    series = build_daily_series(rows.all())

    source_rows = await session.execute(
        select(distinct(DataSource.source_type)).where(DataSource.tenant_id == tenant_id)
    )
    provenance = Provenance(
        computed_at=now.isoformat(),
        window_start=window_start.isoformat(),
        window_end=now.isoformat(),
        sources=sorted(s for s in source_rows.scalars() if s),
    )

    quality = {
        metric: series_quality(daily, days) for metric, daily in sorted(series.items())
    }
    # Analyses only run on series with a defensible amount of data.
    usable = {m: d for m, d in series.items() if quality[m]["sufficient"]}

    correlations = [
        c
        for c in correlation_pairs(usable)
        if abs(c["coefficient"]) >= min_strength
    ]

    trends: dict[str, Any] = {}
    anomalies: dict[str, Any] = {}
    routines: dict[str, Any] = {}
    for metric, daily in usable.items():
        if metric_type and metric != metric_type:
            continue
        ordered_days = sorted(daily)
        values = [daily[d] for d in ordered_days]
        if (trend := trend_for_metric(ordered_days, values)) is not None:
            trends[metric] = trend
        if (anomaly := detect_anomalies(daily)) is not None:
            anomalies[metric] = anomaly
        if (routine := weekday_pattern(daily)) is not None:
            routines[metric] = routine

    comparisons: dict[str, Any] = {}
    if compare_to_previous:
        mid = now - timedelta(days=days // 2)
        earlier = ((now - timedelta(days=days)).date().isoformat(), mid.date().isoformat())
        later = (mid.date().isoformat(), now.date().isoformat())
        for metric, daily in usable.items():
            if metric_type and metric != metric_type:
                continue
            if (cmp := compare_periods(daily, period_a=earlier, period_b=later)) is not None:
                comparisons[metric] = cmp

    excluded = sorted(set(series) - set(usable))

    return {
        "tenant_id": tenant_id,
        "provenance": provenance.to_dict(),
        "disclaimer": (
            "Alle Ergebnisse beschreiben statistische Zusammenhänge, keine "
            "Ursache-Wirkungs-Beziehungen. Sie sind keine medizinische Beratung."
        ),
        "metrics_analysed": sorted(usable),
        "metrics_excluded_for_quality": excluded,
        "data_quality": quality,
        "correlations": correlations,
        "lagged_correlations": lagged_correlations(usable),
        "trends": trends,
        "anomalies": anomalies,
        "routines": routines,
        "period_comparisons": comparisons,
        "docs_url": "/docs/features/correlations/",
    }


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
    session: AsyncSession, tenant_id: str, source_type: str
) -> DataSource | None:
    res = await session.execute(
        select(DataSource).where(
            DataSource.tenant_id == tenant_id, DataSource.source_type == source_type
        )
    )
    return res.scalars().first()


async def _last_successful_sync_end(
    session: AsyncSession, tenant_id: str, source_type: str
) -> datetime | None:
    """When the last successful run's window ended, for adaptive resumption."""
    res = await session.execute(
        select(SyncRun.window_end)
        .where(
            SyncRun.tenant_id == tenant_id,
            SyncRun.source_type == source_type,
            SyncRun.status == "success",
            SyncRun.window_end.is_not(None),
        )
        .order_by(SyncRun.window_end.desc())
        .limit(1)
    )
    value = res.scalar_one_or_none()
    if value is not None and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


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

    source_id = None
    if source_type:
        source = await _resolve_source(session, tenant_id, source_type)
        if not source:
            raise HTTPException(status_code=404, detail="Connector not configured")
        source_id = source.id

    fetch = _bucket_fetcher(
        session, tenant_id, source_id=source_id, metric_type=metric_type
    )
    covered, missing, confidence, expectation, total = await analyse_coverage(fetch, window)

    return {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "metric_type": metric_type,
        "window": window.to_dict(),
        "covered_ranges": [r.to_dict() for r in covered],
        "missing_ranges": [r.to_dict() for r in missing],
        "confidence": confidence,
        "expected_points_per_bucket": expectation or None,
        "total_points": total,
    }


class ImportPlanRequest(BaseModel):
    start: datetime | None = Field(None, description="Requested window start")
    end: datetime | None = Field(None, description="Requested window end")
    mode: Literal["smart", "force"] = Field("smart", description="Smart skips known-complete ranges")


@app.post("/api/v1/data/sources/{source_type}/import-plan")
async def get_import_plan(
    source_type: str,
    req: ImportPlanRequest,
    session: AsyncSession = Depends(get_session),
):
    """Explain what a sync would actually do, without running it.

    The dashboard calls this to prefill the import dialog and to show the user which
    ranges will be skipped and why.
    """
    tenant_id = get_current_tenant_id()
    source = await _resolve_source(session, tenant_id, source_type)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    config = source.config or {}
    now = datetime.now(timezone.utc)

    if req.start and req.end:
        window = _validated_window(req.start, req.end)
        window_reason = "Vom Nutzer gewählter Zeitraum."
    else:
        window, window_reason = compute_sync_window(
            now=now,
            poll_interval_hours=float(config.get("poll_interval_hours", 6)),
            lookback_days=int(config.get("lookback_days", 30)),
            last_success_end=await _last_successful_sync_end(session, tenant_id, source_type),
        )

    fetch = _bucket_fetcher(session, tenant_id, source_id=source.id)
    plan = await plan_import(fetch, window, mode=req.mode)

    payload = plan.to_dict()
    payload["window_reason"] = window_reason
    payload["tenant_id"] = tenant_id
    payload["source_type"] = source_type
    payload["docs_url"] = "/docs/features/smart-import/"
    return payload


@app.get("/api/v1/data/sources/{source_type}/sync-runs")
async def list_sync_runs(
    source_type: str,
    limit: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Import history for a connector, newest first."""
    tenant_id = get_current_tenant_id()
    res = await session.execute(
        select(SyncRun)
        .where(SyncRun.tenant_id == tenant_id, SyncRun.source_type == source_type)
        .order_by(SyncRun.started_at.desc())
        .limit(limit)
    )
    return {
        "tenant_id": tenant_id,
        "source_type": source_type,
        "runs": [
            {
                "id": run.id,
                "request_id": run.request_id,
                "mode": run.mode,
                "trigger": run.trigger,
                "status": run.status,
                "window_start": run.window_start.isoformat() if run.window_start else None,
                "window_end": run.window_end.isoformat() if run.window_end else None,
                "window_reason": run.window_reason,
                "points_received": run.points_received,
                "points_accepted": run.points_accepted,
                "points_duplicate": run.points_duplicate,
                "skipped_ranges": run.skipped_ranges,
                "message": run.message,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
            for run in res.scalars().all()
        ],
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

class ConfigureConnectorRequest(BaseModel):
    source_type: ValidSourceType = Field(..., description="Connector provider: oura, whoop, apple_health, fitbit, yazio")
    # SECURITY H6: Optional access_token to allow editing frequency without re-entering token
    access_token: str | None = Field(None, description="Raw API access token / credential", max_length=2048)
    status: ValidStatus = Field("active", description="active / inactive")
    poll_interval_hours: int = Field(6, ge=1, le=168, description="Poll frequency in hours")
    lookback_days: int = Field(30, ge=1, le=365, description="Lookback window in days")
    config: dict[str, Any] | None = Field(None, description="Custom configuration for the connector")


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

    # Check existing data source
    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.source_type == req.source_type,
    )
    res = await session.execute(stmt)
    existing = res.scalars().first()

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
                        "client_id": "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c",
                        "client_secret": "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o",
                        "grant_type": "password",
                        "username": email,
                        "password": password,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 401:
                    raise HTTPException(status_code=401, detail="Yazio Login fehlgeschlagen: Ungültige E-Mail oder Passwort.")
                if not resp.is_success:
                    raise HTTPException(status_code=resp.status_code, detail=f"Yazio Login fehlgeschlagen: {resp.text}")
                token_data = resp.json()
                raw_token = token_data.get("access_token", "")
                if not raw_token:
                    raise HTTPException(status_code=400, detail="Yazio OAuth Antwort enthielt keinen access_token.")
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Fehler bei Yazio OAuth Verbindung: {e}")

    config_data: dict[str, Any] = {
        "status": req.status,
        "poll_interval_hours": req.poll_interval_hours,
        "lookback_days": req.lookback_days,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    # A connector legitimately has no provider credential when it either receives
    # pushed data (authenticated per-request by a tenant-bound API key) or reads a
    # public/tokenised ICS URL, where the URL itself is the credential.
    incoming_config = req.config or {}
    credential_optional = req.source_type in PUSH_SOURCE_TYPES or (
        req.source_type == "calendar"
        and bool(incoming_config.get("ics_url") or incoming_config.get("base_url"))
    )

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
            detail="Zugangsdaten / Access Token sind für die Erst-Einrichtung erforderlich."
        )

    if req.config:
        clean_config = {k: v for k, v in req.config.items() if k not in ("yazio_email", "yazio_password")}
        config_data.update(clean_config)

    if existing:
        merged_config = dict(existing.config or {})
        merged_config.update(config_data)
        existing.config = merged_config
        source_id = existing.id
    else:
        source_id = str(uuid.uuid4())
        new_source = DataSource(
            id=source_id,
            tenant_id=tenant_id,
            source_type=req.source_type,
            config=config_data,
        )
        session.add(new_source)

    await session.commit()

    req_id = str(uuid.uuid4())
    payload = json.dumps({
        "tenant_id": tenant_id,
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
                except Exception:
                    pass
                await js.publish(f"qs.task.sync.{req.source_type}", payload)
            else:
                await nc.publish(f"qs.task.sync.{req.source_type}", payload)
        except Exception as e:
            logger.warning(f"Failed to publish task sync event: {e}")

    return {
        "status": "success",
        "message": f"Connector {req.source_type} erfolgreich aktualisiert.",
        "source_id": source_id,
        "tenant_id": tenant_id,
        "source_type": req.source_type,
        "masked_token": config_data.get("masked_token", "••••••••"),
        "poll_interval_hours": req.poll_interval_hours,
        "lookback_days": req.lookback_days,
    }



class TriggerSyncRequest(BaseModel):
    source_type: str = Field(..., description="Connector provider name (e.g. yazio, dawarich)")
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
    return await trigger_sync(
        source_type=req.source_type,
        session=session,
        start=req.start,
        end=req.end,
        mode=req.mode,
    )


@app.post("/api/v1/data/sources/{source_type}/sync", status_code=202)
async def trigger_sync(
    source_type: str,
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

    source = await _resolve_source(session, tenant_id, source_type)
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    config = source.config or {}
    now = datetime.now(timezone.utc)
    req_id = str(uuid.uuid4())

    if start and end:
        window = _validated_window(start, end)
        window_reason = "Vom Nutzer gewählter Zeitraum."
    else:
        window, window_reason = compute_sync_window(
            now=now,
            poll_interval_hours=float(config.get("poll_interval_hours", 6)),
            lookback_days=int(config.get("lookback_days", 30)),
            last_success_end=await _last_successful_sync_end(session, tenant_id, source_type),
        )

    fetch = _bucket_fetcher(session, tenant_id, source_id=source.id)
    plan = await plan_import(fetch, window, mode=mode)

    effective = plan.recommended or window
    nothing_to_do = plan.recommended is None and mode == "smart"

    run = SyncRun(
        tenant_id=tenant_id,
        source_id=source.id,
        source_type=source_type,
        request_id=req_id,
        mode=mode,
        trigger="manual",
        window_start=effective.start,
        window_end=effective.end,
        window_reason=f"{window_reason} {plan.reason}".strip()[:255],
        status="skipped" if nothing_to_do else "queued",
        skipped_ranges=[r.to_dict() for r in plan.covered],
        message=plan.reason[:512],
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
            "mode": mode,
            "plan": plan.to_dict(),
        }

    payload = json.dumps({
        "tenant_id": tenant_id,
        "source_type": source_type,
        "request_id": req_id,
        "sync_run_id": run.id,
        "mode": mode,
        "window_start": effective.start.isoformat(),
        "window_end": effective.end.isoformat(),
    }).encode("utf-8")
    
    nc = getattr(app.state, "nats_client", None)
    if nc:
        try:
            if hasattr(nc, "jetstream"):
                js = nc.jetstream()
                try:
                    await js.add_stream(name="tasks", subjects=["qs.task.sync.>"])
                except Exception:
                    pass
                await js.publish(f"qs.task.sync.{source_type}", payload)
            else:
                await nc.publish(f"qs.task.sync.{source_type}", payload)
        except Exception as e:
            logger.warning(f"Failed to publish task sync event: {e}")

    return {
        "status": "sync_queued",
        "source_type": source_type,
        "tenant_id": tenant_id
    }


@app.get("/api/v1/data/sources")
async def list_connectors(
    session: AsyncSession = Depends(get_session),
):
    """List configured connectors for the tenant with masked secrets and sync details."""
    tenant_id = get_current_tenant_id()

    stmt = select(DataSource).where(DataSource.tenant_id == tenant_id)
    res = await session.execute(stmt)
    sources = res.scalars().all()

    connectors = []
    for s in sources:
        config = s.config or {}
        # A push connector or a public ICS feed has no stored credential, so absence
        # of one is not evidence that the connector is unconfigured.
        credential_optional = s.source_type in PUSH_SOURCE_TYPES or (
            s.source_type == "calendar" and bool(config.get("ics_url") or config.get("base_url"))
        )
        if config.get("status") == "inactive":
            continue
        if not config.get("encrypted_token") and not credential_optional:
            continue

        last_dp_stmt = select(func.max(DataPoint.created_at)).where(
            DataPoint.tenant_id == tenant_id,
            DataPoint.source_id == s.id,
        )
        last_dp_res = await session.execute(last_dp_stmt)
        last_dp_dt = last_dp_res.scalar()

        last_sync_at = (
            last_dp_dt.isoformat()
            if last_dp_dt
            else config.get("last_sync_at")
        )

        connectors.append({
            "id": s.id,
            "tenant_id": s.tenant_id,
            "source_type": s.source_type,
            "status": config.get("status", "active"),
            "sync_status": config.get("sync_status", "idle" if last_dp_dt else "pending"),
            "last_sync_message": config.get("last_sync_message", "NATS Task Group bereit"),
            "last_request_id": config.get("last_request_id"),
            "nats_subject": f"qs.task.sync.{s.source_type}",
            "nats_queue_group": f"{s.source_type}_importer_task_group",
            "masked_token": config.get("masked_token", "••••••••"),
            "poll_interval_hours": config.get("poll_interval_hours", 6),
            "lookback_days": config.get("lookback_days", 30),
            "last_sync_at": last_sync_at,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": config.get("updated_at"),
        })

    return {
        "tenant_id": tenant_id,
        "connectors": connectors,
    }


@app.delete("/api/v1/data/sources/{source_type}")
async def delete_connector(
    source_type: str,
    session: AsyncSession = Depends(get_session),
):
    """Safely wipe connector credentials for the tenant without deleting ingested metric data points."""
    tenant_id = get_current_tenant_id()
    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.source_type == source_type,
    )
    res = await session.execute(stmt)
    source = res.scalars().first()

    if not source:
        raise HTTPException(status_code=404, detail="Connector configuration not found")

    # Clear encrypted token and deactivate connector while preserving all ingested data_points
    source.config = {
        "status": "inactive",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await session.commit()

    return {
        "status": "success",
        "message": f"Token for connector '{source_type}' deleted successfully. Ingested metric data preserved.",
        "source_type": source_type,
        "tenant_id": tenant_id,
    }


@app.get("/api/v1/internal/data/sources/{source_type}/token")
async def get_connector_token(
    source_type: str,
    session: AsyncSession = Depends(get_session),
):
    """Internal endpoint for Importer microservices to fetch decrypted credentials."""
    tenant_id = get_current_tenant_id()
    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.source_type == source_type,
    )
    res = await session.execute(stmt)
    source = res.scalars().first()

    if not source or not source.config:
        raise HTTPException(status_code=404, detail=f"No connector configured for {source_type}")

    encrypted_token = source.config.get("encrypted_token")
    if not encrypted_token:
        # Push connectors and public ICS feeds have no provider credential. The
        # importer still needs source_id and config, so return those with a null
        # token rather than a 404 it would have to special-case.
        credential_optional = source_type in PUSH_SOURCE_TYPES or (
            source_type == "calendar"
            and bool(source.config.get("ics_url") or source.config.get("base_url"))
        )
        if not credential_optional:
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

    try:
        decrypted_token = decrypt_secret(encrypted_token)
        return {
            "tenant_id": tenant_id,
            "source_id": str(source.id),
            "source_type": source_type,
            "access_token": decrypted_token,
            "status": source.config.get("status", "active"),
            "config": {
                k: v
                for k, v in (source.config or {}).items()
                if k not in {"encrypted_token", "masked_token"}
            },
        }
    except DecryptionError:
        raise HTTPException(status_code=500, detail="Failed to decrypt connector secret")


# ─── Tenant-bound Inbound API Keys ──────────────────────────


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    source_type: str = Field(..., description="Connector this key may push to")
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
        "warning": "Dieser Schlüssel wird nur einmal angezeigt. Bitte sicher speichern.",
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
        "warning": "Der alte Schlüssel bleibt aktiv, bis er widerrufen wird.",
        "previous_key_id": old_key.id,
        **_serialize_api_key(replacement),
    }


class ResolveApiKeyRequest(BaseModel):
    key_hash: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    source_type: str = Field(..., max_length=64)


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

    source_res = await session.execute(
        select(DataSource).where(
            DataSource.tenant_id == key.tenant_id,
            DataSource.source_type == key.source_type,
        )
    )
    source = source_res.scalars().first()
    await session.commit()

    return {
        "tenant_id": key.tenant_id,
        "source_id": source.id if source else None,
        "source_type": key.source_type,
        "key_id": key.id,
        "key_prefix": key.key_prefix,
        "scopes": key.scopes,
    }


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
        "message": "Ansicht erfolgreich in PostgreSQL gespeichert.",
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
        raise HTTPException(status_code=404, detail="Ansicht nicht gefunden oder keine Berechtigung.")

    await session.delete(view)
    await session.commit()

    return {
        "status": "success",
        "message": f"Ansicht {view_id} erfolgreich aus PostgreSQL gelöscht.",
        "view_id": view_id,
    }


class UpdateConnectorStatusRequest(BaseModel):
    sync_status: str
    last_sync_message: str
    sync_run_id: str | None = Field(None, description="Run to close out, if known")
    points_received: int | None = Field(None, ge=0)


@app.post("/api/v1/internal/data/sources/{source_type}/status")
async def update_connector_status_internal(
    source_type: str,
    req: UpdateConnectorStatusRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """Importers report the outcome of a sync here.

    Closing out the ``SyncRun`` is what makes the next window adaptive: only a run
    that reached ``success`` is allowed to move the resume point forward.
    """
    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.source_type == source_type,
    )
    res = await session.execute(stmt)
    ds = res.scalar_one_or_none()
    if ds:
        cfg = dict(ds.config or {})
        cfg["sync_status"] = req.sync_status
        cfg["last_sync_message"] = req.last_sync_message
        ds.config = cfg

    if req.sync_run_id:
        run_res = await session.execute(
            select(SyncRun).where(
                SyncRun.id == req.sync_run_id, SyncRun.tenant_id == tenant_id
            )
        )
        run = run_res.scalars().first()
        if run:
            run.status = (
                "success" if req.sync_status in {"idle", "success", "ok"} else req.sync_status
            )
            run.message = req.last_sync_message[:512]
            run.finished_at = datetime.now(timezone.utc)
            if req.points_received is not None:
                run.points_received = req.points_received

    await session.commit()
    return {"status": "ok"}


@app.delete("/api/v1/data/wipe")
async def wipe_tenant_data_points(
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """1-Click deletion of all ingested data points for current tenant."""
    stmt = delete(DataPoint).where(DataPoint.tenant_id == tenant_id)
    result = await session.execute(stmt)
    await session.commit()

    return {
        "status": "wiped",
        "deleted_count": result.rowcount,
        "message": f"Successfully deleted {result.rowcount} data points for tenant.",
    }


@app.delete("/api/v1/data/account")
async def delete_tenant_account(
    tenant_id: str = Depends(get_current_tenant_id),
    session: AsyncSession = Depends(get_session),
):
    """1-Click full account wipe (data points, data sources, tenant shares)."""
    dp_res = await session.execute(delete(DataPoint).where(DataPoint.tenant_id == tenant_id))
    ds_res = await session.execute(delete(DataSource).where(DataSource.tenant_id == tenant_id))
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

