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
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from sqlalchemy import delete, distinct, func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.analytics import detect_daily_gaps, find_cross_source_conflicts, pearson_pairs
from core.config import settings
from core.db.models import (
    ApiKey,
    DataPoint,
    DataSource,
    ExplorerView,
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

    # The caller's own session was just revoked along with the rest, so leave the
    # browser genuinely signed out. Without this the cookies survive a change that
    # invalidated them, and the UI keeps rendering as signed-in until some later
    # request happens to 401.
    clear_session_cookies(response)

    return {
        "status": "success",
        "message": "Passwort wurde erfolgreich geändert. Bitte melde dich erneut an.",
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
            detail=f"Issuer konnte nicht verifiziert werden: {exc.detail}",
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
        raise HTTPException(status_code=409, detail="Ein Anbieter mit diesem Slug existiert bereits.")

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
        raise HTTPException(status_code=404, detail="Anbieter nicht gefunden.")

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
        raise HTTPException(status_code=404, detail="Anbieter nicht gefunden.")

    linked = await session.execute(
        select(func.count())
        .select_from(UserIdentity)
        .where(UserIdentity.provider_slug == slug)
    )
    if (linked.scalar() or 0) > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Dieser Anbieter wird noch von Konten verwendet. Deaktiviere ihn, "
                "statt ihn zu löschen."
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
                "Der Anbieter hat diese E-Mail-Adresse nicht als verifiziert bestätigt. "
                "Bitte melde dich mit E-Mail und Passwort an und verknüpfe den Anbieter "
                "in den Einstellungen."
            ),
        )
    if not identity.email:
        raise HTTPException(
            status_code=403, detail="Der Anbieter hat keine E-Mail-Adresse übermittelt."
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
                "Für diese E-Mail-Adresse existiert bereits ein Konto. Melde dich mit "
                "E-Mail und Passwort an und verknüpfe den Anbieter in den Einstellungen."
            ),
        )

    if not provider.allow_signup or not settings.ALLOW_REGISTRATION:
        raise HTTPException(
            status_code=403, detail="Registrierung über diesen Anbieter ist deaktiviert."
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
                "Das ist die einzige Anmeldemöglichkeit für dieses Konto. Lege zuerst "
                "ein Passwort fest oder verknüpfe einen weiteren Anbieter."
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
        session, tenant_id, source_type, now=now
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
                    "Die Zugangsdaten für diesen Connector sind abgelaufen und "
                    "konnten nicht erneuert werden. Bitte neu verbinden."
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

