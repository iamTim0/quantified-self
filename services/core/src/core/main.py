# ruff: noqa: B008
"""Core Data Service FastAPI Entry Point.

Serves REST endpoints for time-series metric data queries, metric type listing, summary statistics,
and secure encrypted connector configuration management.

Enforces multi-tenant isolation via TenantMiddleware & contextvars.
"""

import asyncio
import json
import logging
import os
import uuid
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any, Literal
from urllib.parse import parse_qs

import httpx
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
from shared_schemas import FieldReport, idempotency_key
from shared_schemas.metrics import (
    CANONICAL_KEYS,
    DYNAMIC_NAMESPACES,
    METRIC_ALIASES,
    METRIC_CATALOG,
    Cadence,
    UnknownMetricTypeError,
    canonical_metric_type,
    describe,
)
from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.analytics import (
    detect_cadence_gaps,
    detect_daily_gaps,
    find_cross_source_conflicts,
    pearson_pairs,
)
from core.config import settings
from core.connectors import PUSH_SOURCE_TYPES, credential_is_optional
from core.db.models import (
    ApiKey,
    DataPoint,
    DataSource,
    ExplorerView,
    IngestFieldReport,
    OidcAuthRequest,
    OidcProvider,
    RefreshToken,
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
from core.events.consumer import run_consumer_forever
from core.grpc.server import serve_grpc
from core.ingest_planning import (
    BucketCount,
    TimeRange,
    analyse_coverage,
    compute_sync_window,
    plan_import,
)
from core.oauth_refresh import (
    RefreshError,
    apply_refresh,
    can_refresh,
    needs_refresh,
    refresh_credential,
)
from core.scheduler import DueConnector, has_in_flight_run, run_scheduler
from core.security.auth import (
    AuthenticationMiddleware,
    Principal,
    get_current_principal,
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
from core.tracing import (
    RequestTracingMiddleware,
    get_current_request_id,
    setup_tracing_logger,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# SECURITY H3: Constrain source_type to known connectors
ValidSourceType = Literal[
    "oura", "whoop", "apple_health", "fitbit", "garmin", "strava", "yazio",
    "dawarich", "streak", "home_assistant", "weather", "calendar",
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


class CreateShareRequest(BaseModel):
    grantee_email: str = Field(..., description="Email of the user to share data with")
    scope: str = Field("read_all", description="Scope of shared data e.g. read_all or read_metric:sleep_score")


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

    # The gRPC server is how the Analysis Service reads data (AGENTS.md rule 3).
    # It starts before the NATS consumer and outside that try block on purpose:
    # the consumer's failure path deliberately still yields so Core serves HTTP
    # without a broker, and folding gRPC into it would have let the read API for
    # another service disappear silently.
    grpc_server = None
    try:
        grpc_server = await serve_grpc()
        app.state.grpc_server = grpc_server
    except Exception:
        logger.exception("gRPC server failed to start; Analysis Service reads will fail")

    scheduler_task = None
    if settings.SCHEDULER_ENABLED:
        scheduler_task = asyncio.create_task(run_scheduler(_enqueue_scheduled_sync))

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

    def _remember(nc):
        app.state.nats_client = nc

    consumer_task = asyncio.create_task(run_consumer_forever(_remember))

    try:
        yield
    finally:
        consumer_task.cancel()
        with suppress(asyncio.CancelledError):
            await consumer_task
        if (nc := getattr(app.state, "nats_client", None)) is not None:
            with suppress(Exception):
                await nc.close()
        if scheduler_task is not None:
            scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler_task
        if grpc_server is not None:
            await grpc_server.stop(grace=2.0)


async def _enqueue_scheduled_sync(connector: DueConnector) -> None:
    """Enqueue one due connector, on its own session and tenant scope.

    A separate session per connector so one failure cannot roll back another's
    SyncRun row, and the tenant context is bound explicitly because there is no
    request to derive it from -- the scheduler acts for every tenant in turn.
    """
    token = _current_tenant_id.set(connector.tenant_id)
    try:
        async with async_session_maker() as session:
            source = await session.get(DataSource, connector.source_id)
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
    }


@app.post("/api/v1/auth/login")
async def login(
    req: UserLoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(User).where(User.email == req.email)
    res = await session.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not pwd_context.verify(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

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
    _principal: Principal = Depends(require_role("owner", "admin")),
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
    _principal: Principal = Depends(require_role("owner", "admin")),
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
    _principal: Principal = Depends(require_role("owner", "admin")),
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
    _principal: Principal = Depends(require_role("owner", "admin")),
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

    return {"warnings": [w.as_dict() for w in warnings]}


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

def _definition_payload(metric_type: str) -> dict[str, Any] | None:
    """Registry definition for a stored metric name, or ``None`` if it has none.

    A tenant can hold rows written before a catalog entry was renamed or removed, and
    those rows must still list and still chart. Returning ``None`` says "this is data
    without a current definition", which a caller can render; omitting the metric would
    make it look like the data were gone.
    """
    try:
        return describe(metric_type).model_dump(mode="json")
    except UnknownMetricTypeError:
        return None


def _round(value: float | None, digits: int) -> float | None:
    """Round an aggregate to the precision the metric declares."""
    return round(float(value), digits) if value is not None else None



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

    return {
        "tenant_id": tenant_id,
        "metric_types": metric_types,
        "definitions": {name: _definition_payload(name) for name in metric_types},
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
            func.sum(DataPoint.value).label("sum_value"),
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
        definition = _definition_payload(row.metric_type)
        # Rounding follows the metric rather than a blanket one decimal: a step count
        # with a fractional part is noise, a coordinate rounded to 0.1° is a different
        # town.
        digits = definition["precision"] if definition else 1

        summary[row.metric_type] = {
            "count": row.count,
            "average": _round(row.avg_value, digits),
            "min": _round(row.min_value, digits),
            "max": _round(row.max_value, digits),
            # Which of average and total is the meaningful one is a property of the
            # metric (`definition.aggregation`), so both are returned and the caller
            # picks: averaging a day's step counts answers a question nobody asked.
            "sum": _round(row.sum_value, digits),
            "latest_timestamp": row.latest_timestamp.isoformat() if row.latest_timestamp else None,
            "definition": definition,
        }

    return {
        "tenant_id": tenant_id,
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
    """
    tenant_id = get_current_tenant_id()
    if end_date < start_date or (end_date - start_date).days > 366:
        raise HTTPException(status_code=400, detail="Date range must contain at most 367 ordered days")

    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    window_end = datetime.combine(
        end_date + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    )

    # Filtered in SQL, not in Python. Half the registry is event-driven and would
    # be discarded after Postgres had selected, transferred and decoded it — and
    # the discarded half is the high-volume one, GPS traces and per-minute samples.
    judged = [
        key
        for key, definition in METRIC_CATALOG.items()
        if definition.cadence in (Cadence.DAILY, Cadence.CONTINUOUS)
    ]
    result = await session.execute(
        select(DataPoint.metric_type, DataPoint.timestamp).where(
            DataPoint.tenant_id == tenant_id,
            DataPoint.metric_type.in_(judged),
            DataPoint.timestamp >= window_start,
            DataPoint.timestamp < window_end,
        )
    )
    rows = result.all()

    # The reader's own zone, not UTC. Without this the parameter added for exactly
    # this purpose was exercised only by its unit test, and the first and last day
    # of every window stayed misreported.
    gaps = detect_daily_gaps(rows, start_date, end_date, local_timezone=_window_timezone(offset_minutes))
    cadence_gaps = detect_cadence_gaps(rows, TimeRange(window_start, window_end))
    return {
        "tenant_id": tenant_id,
        "gaps": gaps,
        "missing_count": sum(len(g["missing_dates"]) for g in gaps),
        # Continuous metrics report interrupted spans rather than missing days:
        # a calendar day is the wrong unit for something sampled every minute.
        "cadence_gaps": cadence_gaps,
    }


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
    query = select(DataSource).where(DataSource.tenant_id == tenant_id)
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


async def _last_successful_sync_end(
    session: AsyncSession, tenant_id: str, source_id: str
) -> datetime | None:
    """When this connector's last successful run ended, for adaptive resumption.

    Keyed on the instance, not the type: with two calendars, the type would let
    one connector's successful window advance the other's resume point, and the
    second calendar would silently skip everything the first had already fetched.
    """
    res = await session.execute(
        select(SyncRun.window_end)
        .where(
            SyncRun.tenant_id == tenant_id,
            SyncRun.source_id == source_id,
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

    if req.start and req.end:
        window = _validated_window(req.start, req.end)
        window_reason = "Period chosen by the user."
    else:
        window, window_reason = compute_sync_window(
            now=now,
            poll_interval_hours=float(config.get("poll_interval_hours", 6)),
            lookback_days=int(config.get("lookback_days", 30)),
            last_success_end=await _last_successful_sync_end(session, tenant_id, source.id),
        )

    fetch = _bucket_fetcher(session, tenant_id, source_id=source.id)
    plan = await plan_import(fetch, window, mode=req.mode)

    payload = plan.to_dict()
    payload["window_reason"] = window_reason
    payload["tenant_id"] = tenant_id
    payload["source_id"] = source.id
    payload["source_type"] = source.source_type
    payload["docs_url"] = "/docs/features/smart-import/"
    return payload


@app.get("/api/v1/data/sources/{source_ref}/sync-runs")
async def list_sync_runs(
    source_ref: str,
    limit: int = Query(20, ge=1, le=200),
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
            for run in runs
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
    lookback_days: int = Field(30, ge=1, le=365, description="Lookback window in days")
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
                        "Yazio sign-in failed with HTTP %s: %s", resp.status_code, resp.text[:500]
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
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Yazio OAuth connection failed: {e}")

    config_data: dict[str, Any] = {
        "status": req.status,
        "poll_interval_hours": req.poll_interval_hours,
        "lookback_days": req.lookback_days,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    credential_optional = credential_is_optional(req.source_type)

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
                except Exception:
                    pass
                await js.publish(f"qs.task.sync.{req.source_type}", payload)
            else:
                await nc.publish(f"qs.task.sync.{req.source_type}", payload)
        except Exception as e:
            logger.warning(f"Failed to publish task sync event: {e}")

    return {
        "status": "success",
        "message": f"Connector {req.source_type} updated.",
        "source_id": source_id,
        "tenant_id": tenant_id,
        "source_type": req.source_type,
        "display_name": display_name,
        "masked_token": config_data.get("masked_token", "••••••••"),
        "poll_interval_hours": req.poll_interval_hours,
        "lookback_days": req.lookback_days,
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


async def plan_and_enqueue_sync(
    session: AsyncSession,
    tenant_id: str,
    source: DataSource,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    mode: Literal["smart", "force"] = "smart",
    trigger: str = "manual",
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

    # Core is the single authority on whether a connector is already busy. The
    # importers each kept a process-local `active_syncs` set, which stops nothing
    # once a second replica exists -- both would accept the same task. Refusing to
    # enqueue here means the duplicate never reaches them, whatever they run.
    # `force` is exempt: an explicit user override should not be blocked by a run
    # that may itself be stuck.
    if mode != "force" and await has_in_flight_run(
        session, tenant_id, source.id, now=now
    ):
        logger.info(
            "[req_id=%s] Sync for %s not enqueued: a run is already in flight.",
            req_id,
            source_type,
        )
        return {
            "status": "already_running",
            "source_type": source_type,
            "tenant_id": tenant_id,
            "request_id": req_id,
        }

    if start and end:
        window = _validated_window(start, end)
        window_reason = "Period chosen by the user."
    else:
        window, window_reason = compute_sync_window(
            now=now,
            poll_interval_hours=float(config.get("poll_interval_hours", 6)),
            lookback_days=int(config.get("lookback_days", 30)),
            last_success_end=await _last_successful_sync_end(session, tenant_id, source.id),
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
        trigger=trigger,
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

    stmt = select(DataSource).where(DataSource.tenant_id == tenant_id)
    res = await session.execute(stmt)
    sources = res.scalars().all()

    connectors = []
    for s in sources:
        config = s.config or {}
        # A credential-optional connector has no stored token, so absence of one is
        # not evidence that the connector is unconfigured.
        credential_optional = credential_is_optional(s.source_type)
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

    # Clear encrypted token and deactivate connector while preserving all ingested data_points
    source.config = {
        "status": "inactive",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
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
        if not credential_is_optional(source_type):
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
        .where(DataSource.tenant_id == tenant_id, DataSource.source_type == source_type)
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
            "metric_type": statement.excluded.metric_type,
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


class OpenSyncRunRequest(BaseModel):
    """Start an import that Core did not schedule."""

    trigger: Literal["push", "upload"] = Field(
        "push", description="How this import was started"
    )
    request_id: str | None = Field(None, max_length=128)
    # Known up front for a file upload, unknowable for a webhook. Where it is
    # unknown the interface counts rather than showing an invented percentage.
    points_expected: int | None = Field(None, ge=0)
    message: str | None = Field(None, max_length=512)


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
        points_received=req.points_expected or 0,
        message=(req.message or "")[:512] or None,
        started_at=now,
    )
    session.add(run)

    config = dict(source.config or {})
    config["sync_status"] = "queued"
    config["last_sync_message"] = req.message or "Import running."
    source.config = config

    await session.commit()

    return {
        "sync_run_id": run.id,
        "source_id": source.id,
        "source_type": source.source_type,
        "tenant_id": tenant_id,
    }


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

