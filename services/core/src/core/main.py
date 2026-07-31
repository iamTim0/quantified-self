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
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db.models import DataPoint, DataSource, ExplorerView, Tenant, TenantShare, User
from core.db.session import get_session
from core.db.tenant import TenantMiddleware, get_current_tenant_id
from core.events.consumer import start_consumer
from core.security.crypto import (
    DecryptionError,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# SECURITY H3: Constrain source_type to known connectors
ValidSourceType = Literal["oura", "whoop", "apple_health", "fitbit", "yazio", "dawarich"]
ValidStatus = Literal["active", "inactive"]



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


from core.tracing import (
    RequestTracingMiddleware,
    setup_tracing_logger,
)

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
    allow_methods=["GET", "POST"],
    allow_headers=["X-Tenant-ID", "X-Request-ID", "Content-Type"],
)
app.add_middleware(TenantMiddleware)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.SERVICE_NAME}


# ─── Auth Endpoints ──────────────────────────────────────────

# ─── Auth Endpoints ──────────────────────────────────────────

@app.post("/api/v1/auth/signup")
async def signup(
    req: UserSignupRequest,
    session: AsyncSession = Depends(get_session),
):
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

    token_payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "email": req.email,
        "role": "owner",
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
        "iat": datetime.now(timezone.utc),
    }
    jwt_secret = getattr(settings, "JWT_SECRET", "dev-secret-key-quantified-self-2026")
    token = jwt.encode(token_payload, jwt_secret, algorithm="HS256")

    return {
        "status": "success",
        "access_token": token,
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

    token_payload = {
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "email": user.email,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(days=30),
        "iat": datetime.now(timezone.utc),
    }
    jwt_secret = getattr(settings, "JWT_SECRET", "dev-secret-key-quantified-self-2026")
    token = jwt.encode(token_payload, jwt_secret, algorithm="HS256")

    return {
        "status": "success",
        "access_token": token,
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
    """Safely update account password for authenticated user."""
    tenant_id = get_current_tenant_id()

    stmt = select(User).where(User.tenant_id == tenant_id)
    res = await session.execute(stmt)
    user = res.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="Benutzerkonto nicht gefunden.")

    if not pwd_context.verify(req.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Aktuelles Passwort ist falsch.")

    user.password_hash = pwd_context.hash(req.new_password)
    await session.commit()

    return {
        "status": "success",
        "message": "Passwort wurde erfolgreich geändert."
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

    stmt = stmt.order_by(DataPoint.timestamp.asc()).limit(limit)
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

    if raw_token:
        encrypted_token = encrypt_secret(raw_token)
        masked_token = mask_secret(raw_token)
        config_data["encrypted_token"] = encrypted_token
        config_data["masked_token"] = masked_token
    elif existing and existing.config and "encrypted_token" in existing.config:
        config_data["encrypted_token"] = existing.config["encrypted_token"]
        config_data["masked_token"] = existing.config.get("masked_token", "••••••••")
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


@app.post("/api/v1/data/sources/{source_type}/sync", status_code=202)
async def trigger_sync(
    source_type: str,
    session: AsyncSession = Depends(get_session),
):
    """Trigger an on-demand sync for a connector."""
    tenant_id = get_current_tenant_id()

    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.source_type == source_type,
    )
    res = await session.execute(stmt)
    source = res.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Connector not configured")

    new_config = dict(source.config or {})
    new_config["last_sync_at"] = datetime.now(timezone.utc).isoformat()
    source.config = new_config
    await session.commit()

    req_id = str(uuid.uuid4())
    payload = json.dumps({
        "tenant_id": tenant_id,
        "source_type": source_type,
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
        if config.get("status") == "inactive" or not config.get("encrypted_token"):
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
        raise HTTPException(status_code=404, detail="Token not found in connector configuration")

    try:
        decrypted_token = decrypt_secret(encrypted_token)
        return {
            "tenant_id": tenant_id,
            "source_id": str(source.id),
            "source_type": source_type,
            "access_token": decrypted_token,
            "status": source.config.get("status", "active"),
            "config": source.config or {},
        }
    except DecryptionError:
        raise HTTPException(status_code=500, detail="Failed to decrypt connector secret")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
