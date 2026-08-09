"""SQLAlchemy 2.0 ORM models for Core Data Service.

All models correspond to the PostgreSQL schema defined in infra/db/init.sql.
Includes Tenant & User separation for multi-tenant enterprise support.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from geoalchemy2 import Geometry
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    """Tenant / Organization workspace model."""
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="tenant", cascade="all, delete-orphan")


class User(Base):
    """User identity model belonging to a Tenant workspace."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="owner")  # 'owner', 'admin', 'member'
    # Access tokens issued before this instant are rejected.
    #
    # The denylist in ``revoked_access_tokens`` keys on ``jti``, which works for
    # "log this session out" and cannot express "log *every* session out": we only
    # learn a jti when its token is presented, so there is no list to add. Without
    # this column, revoking all sessions revoked only the refresh tokens, and every
    # outstanding access token stayed valid for the rest of its twelve hours —
    # after a password change, after a credential compromise, and after a provider
    # told us the identity behind the session no longer exists.
    #
    # Null means "no cutoff", which is every account that has never had one.
    sessions_valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="users")


class DataSource(Base):
    """One configured connector instance.

    A tenant may hold several of the same type — three calendars, two weather
    locations — so the row, not the type, is the thing everything else refers to.
    `display_name` is what tells them apart to a reader; `id` is what tells them
    apart to the system, and it is already the second component of every
    `idempotency_key`, so two instances keep separate data without any re-keying.
    """

    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)  # e.g., 'oura', 'whoop'
    #: What the user calls this instance. Required, because "which of my three
    #: calendars is this?" has no answer the system could invent.
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # Two instances of a type are fine; two with the same name are not, because
        # then the list the user picks from has two identical rows. Declared here as
        # well as in the migration -- the ORM used to know about none of this, which
        # is how the constraint and the model drifted apart in the first place.
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "display_name",
            name="uq_data_sources_tenant_type_name",
        ),
    )


class DataPoint(Base):
    __tablename__ = "data_points"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("data_sources.id"), nullable=False, index=True
    )
    metric_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False, index=True
    )
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    embedding: Mapped[Any | None] = mapped_column(Vector(1536), nullable=True)
    location_geom: Mapped[Any | None] = mapped_column("location_geom", Geometry("POINT", srid=4326), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        # TimescaleDB hypertable requirement: partitioning column (timestamp) must be in unique constraint
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            "timestamp",
            name="uq_data_points_tenant_idempotency_time",
        ),
    )


class TenantShare(Base):
    __tablename__ = "tenant_shares"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    grantor_tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False
    )
    grantee_tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String, nullable=False)  # e.g., 'read_all', 'read_metric:sleep_score'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint(
            "grantor_tenant_id", "grantee_tenant_id", "scope", name="uq_tenant_shares_grant"
        ),
    )


class RefreshToken(Base):
    """A long-lived session credential, stored only as a SHA-256 hash.

    Rotation is tracked through ``rotated_to_id`` so that replaying a superseded
    refresh token is detectable: if a token that has already been rotated is
    presented again, the whole chain is treated as compromised and revoked.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_to_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RevokedAccessToken(Base):
    """Denylist of access-token ``jti`` values invalidated before their expiry.

    Rows may be pruned once ``expires_at`` has passed — after that the token is
    rejected by signature validation anyway.
    """
    __tablename__ = "revoked_access_tokens"

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="logout")
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ApiKey(Base):
    """A tenant-bound inbound API key for external push sources.

    The full key is shown exactly once, at creation. Only ``key_hash`` is stored,
    so the tenant is resolved *from the key itself* — no ``X-Tenant-ID`` header is
    involved and none is trusted. ``key_prefix`` exists purely so that a key can be
    named in the UI and in logs without disclosing it.
    """
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # Which connector this key may push to; a key scoped to apple_health cannot
    # be replayed against the streak endpoint.
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Which *instance* it pushes to. Once a tenant can hold two Apple Health
    # connectors, the type alone no longer answers "whose data is this?" — and the
    # answer decides the `source_id` that goes into every idempotency key.
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=lambda: ["ingest"])
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | revoked
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_from_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SyncRun(Base):
    """One import attempt for one connector — the import/audit log.

    This is what makes adaptive windows possible: the next window is derived from
    the last run that actually succeeded, not from wall-clock guesswork. It is also
    where ``force`` imports are recorded, as the brief requires.
    """
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="smart")  # smart | force
    trigger: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    points_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    points_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    points_duplicate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_ranges: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IngestFieldReport(Base):
    """A provider field an importer saw, and whether it became a data point.

    The shape of what arrives, never its contents: a path, the *kind* of value that
    sat there, and how often it was seen. Storing payloads instead would keep a
    second copy of the most sensitive data in the system, and would make the
    account deletion incomplete unless it hunted that copy down too.

    Rolling rather than append-only — one row per (tenant, connector, path), upserted
    — so the table grows with the *provider's schema* and not with the data. That is
    why it needs no retention policy: a provider has a few hundred fields no matter
    how many years of readings pass through.
    """

    __tablename__ = "ingest_field_reports"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("data_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Dotted path into the provider payload, e.g. `metrics.heart_rate.Avg`.
    field_path: Mapped[str] = mapped_column(String(512), nullable=False)
    #: `number`, `string`, `bool`, `array`, `object`, `null`. Not the value.
    value_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: The canonical metric this path became. NULL is the interesting case: seen,
    #: understood well enough to name, and not stored.
    metric_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_sync_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "source_id", "field_path", name="uq_field_reports_tenant_source_path"
        ),
    )


class OidcProvider(Base):
    """A configurable OpenID Connect provider.

    Deliberately data rather than code: Google is just one row. The client secret
    is Fernet-encrypted at rest like any other credential, and is never returned
    by the API — the admin endpoints expose only a masked form.
    """
    __tablename__ = "oidc_providers"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # URL-safe key used in the callback path, e.g. "google".
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id: Mapped[str] = mapped_column(String(512), nullable=False)
    encrypted_client_secret: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    scopes: Mapped[str] = mapped_column(String(512), nullable=False, default="openid email profile")
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    # Which claim supplies which field, e.g. {"email": "email", "name": "name"}.
    claims_mapping: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Whether a first-time login may create an account, or only link an existing one.
    allow_signup: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Only trust the provider's email_verified claim if the provider is trustworthy.
    require_verified_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class OidcAuthRequest(Base):
    """One in-flight authorization request.

    Stored server-side rather than in a cookie so ``state``, ``nonce`` and the PKCE
    verifier cannot be read or replayed by the browser, and so the flow works across
    replicas. Rows are single-use and short-lived.
    """
    __tablename__ = "oidc_auth_requests"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    nonce: Mapped[str] = mapped_column(String(128), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(256), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    # Set when an already-signed-in user is linking a provider to their account.
    link_user_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class UserIdentity(Base):
    """A federated identity linked to a local user.

    The unique key is ``(provider_slug, subject)`` — the provider's stable subject
    identifier, not the email address. Emails change hands and can be re-registered;
    matching on them is how accounts get taken over.
    """
    __tablename__ = "user_identities"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    provider_slug: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("provider_slug", "subject", name="uq_user_identities_provider_subject"),
    )


class ExplorerView(Base):
    """SaaS Multi-tenant saved Explorer View query configuration model."""
    __tablename__ = "explorer_views"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tenants.id"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    query_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
