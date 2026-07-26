"""Core Data Service FastAPI Entry Point.

Serves REST endpoints for time-series metric data queries, metric type listing, summary statistics,
and secure encrypted connector configuration management.

Enforces multi-tenant isolation via TenantMiddleware & contextvars.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
import uuid

from fastapi import FastAPI, Depends, Query, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db.models import DataPoint, DataSource
from core.db.session import get_session
from core.db.tenant import get_current_tenant_id, TenantMiddleware
from core.events.consumer import start_consumer
from core.security.crypto import encrypt_secret, mask_secret

class ConfigureConnectorRequest(BaseModel):
    source_type: str = Field(..., description="e.g. oura, whoop, apple_health, fitbit")
    access_token: str = Field(..., description="Raw API access token / credential")
    status: str = Field("active", description="active / inactive")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if getattr(app.state, "testing", False):
        yield
        return
    try:
        nc = await start_consumer()
        yield
        await nc.close()
    except Exception:
        yield

app = FastAPI(title=settings.SERVICE_NAME, lifespan=lifespan)
app.add_middleware(TenantMiddleware)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.SERVICE_NAME}

@app.get("/api/v1/data/metrics")
async def query_metrics(
    metric_type: Optional[str] = Query(None, description="Filter by metric type (e.g. sleep_score, steps)"),
    start_time: Optional[str] = Query(None, description="ISO start timestamp"),
    end_time: Optional[str] = Query(None, description="ISO end timestamp"),
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
            raise HTTPException(status_code=400, detail="Invalid start_time ISO format")

    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
            stmt = stmt.where(DataPoint.timestamp <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_time ISO format")

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
    session: AsyncSession = Depends(get_session)
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
    session: AsyncSession = Depends(get_session)
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

@app.post("/api/v1/data/sources/configure")
async def configure_connector(
    req: ConfigureConnectorRequest,
    session: AsyncSession = Depends(get_session)
):
    """Safely configure a connector for the tenant.

    Encrypts raw access tokens with Fernet symmetric AES before database persistence.
    """
    tenant_id = get_current_tenant_id()

    # Encrypt secret at rest
    encrypted_token = encrypt_secret(req.access_token)
    masked_token = mask_secret(req.access_token)

    # Check existing data source
    stmt = select(DataSource).where(
        DataSource.tenant_id == tenant_id,
        DataSource.source_type == req.source_type
    )
    res = await session.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing:
        existing.config = {
            "encrypted_token": encrypted_token,
            "masked_token": masked_token,
            "status": req.status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        source_id = existing.id
    else:
        source_id = str(uuid.uuid4())
        new_source = DataSource(
            id=source_id,
            tenant_id=tenant_id,
            source_type=req.source_type,
            config={
                "encrypted_token": encrypted_token,
                "masked_token": masked_token,
                "status": req.status,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        session.add(new_source)

    await session.commit()

    return {
        "status": "success",
        "message": f"Connector {req.source_type} configured safely.",
        "source_id": source_id,
        "tenant_id": tenant_id,
        "source_type": req.source_type,
        "masked_token": masked_token,
    }

@app.get("/api/v1/data/sources")
async def list_connectors(
    session: AsyncSession = Depends(get_session)
):
    """List configured connectors for the tenant with masked secrets."""
    tenant_id = get_current_tenant_id()

    stmt = select(DataSource).where(DataSource.tenant_id == tenant_id)
    res = await session.execute(stmt)
    sources = res.scalars().all()

    connectors = []
    for s in sources:
        config = s.config or {}
        connectors.append({
            "id": s.id,
            "tenant_id": s.tenant_id,
            "source_type": s.source_type,
            "status": config.get("status", "active"),
            "masked_token": config.get("masked_token", "••••••••"),
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": config.get("updated_at"),
        })

    return {
        "tenant_id": tenant_id,
        "connectors": connectors,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
