import json
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_root_env() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".env").exists():
            return parent / ".env"
    return current.parents[min(4, len(current.parents) - 1)] / ".env"


_ROOT_ENV = _find_root_env()


def _default_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "dev-secret-key-quantified-self-2026")

class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-core-service"
    # Runtime role lets the same Core image scale API, ingestion and scheduling
    # independently. `all` preserves the local-development single-process mode.
    CORE_ROLE: str = "all"  # all | api | ingest | scheduler
    # Matches the Gateway's convention. "dev" (or anything not in
    # core.security.secret_audit.PRODUCTION_ENVIRONMENTS) means published default
    # secrets are a loud warning; production means Core refuses to start on them.
    #
    # Defaults to development rather than production so that a laptop, the test
    # suite and CI all work with no configuration. The deployment does not rely on
    # anyone remembering to change this: docker-compose.prod.yml sets
    # ENVIRONMENT=production and uses ${VAR:?...} so an unset secret stops the
    # deploy outright.
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "postgresql+asyncpg://qs_dev:qs_dev_password@127.0.0.1:5433/quantified_self"
    # Connection pooling. Two processes hold this engine — the API and the ingest
    # consumer — so the defaults are sized for a handful of concurrent statements
    # each rather than for a crowd. Recycling below any sensible idle timeout keeps
    # a long-lived connection from being closed under us by the server or a NAT.
    DATABASE_POOL_SIZE: int = 10
    DATABASE_POOL_MAX_OVERFLOW: int = 10
    DATABASE_POOL_RECYCLE_SECONDS: int = 1800
    NATS_URL: str = "nats://127.0.0.1:4222"
    GRPC_PORT: int = 50051
    JWT_SECRET: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    # Access tokens are short-lived because they cannot be revoked mid-flight
    # except through the denylist; refresh tokens carry the long session.
    ACCESS_TOKEN_TTL_MINUTES: int = 720  # 12 hours
    REFRESH_TOKEN_TTL_DAYS: int = 30
    # Signing key for internal service credentials. Deliberately separate from
    # JWT_SECRET so a compromised importer cannot mint user tokens. Empty means
    # "derive a deterministic dev value" — see core.security.tokens.
    INTERNAL_SERVICE_SECRET: str = ""
    # Optional JSON object mapping service names to distinct bearer secrets. The
    # legacy single secret remains a development/rollout fallback.
    INTERNAL_SERVICE_SECRETS: str = ""
    ENCRYPTION_KEY: str = "dev-secret-shared-encryption-key-qs-2026"
    # Off by default: this is a personal analytics platform, and a public
    # deployment with open signup is a decision, not a default. Create the
    # first account with `python -m core.create_owner`; turn this on only
    # for a deployment that is meant to accept strangers.
    ALLOW_REGISTRATION: bool = False
    # Which workspace administers the deployment itself.
    #
    # "owner" is a role inside a tenant, and every account-creation path mints
    # one: `/auth/signup` and OIDC sign-up both create a fresh tenant with the new
    # user as its owner. So "owner" answers "may this person manage their own
    # workspace", and nothing answered "may this person manage the deployment" --
    # which is what changing the public imprint, the login providers or the
    # ingestion stream actually is. With registration enabled, anyone who signed
    # up could do all three.
    #
    # Empty means **the oldest tenant**, which is the one whoever installed this
    # created with `python -m core.create_owner`. That is right without
    # configuration for the single-tenant case, and it is what makes this a fix
    # rather than a setting somebody has to discover. Name a tenant id here when
    # the deployment is administered from a workspace that is not the first one.
    PLATFORM_TENANT_ID: str = ""

    # Periodic sync scheduling. On by default: `poll_interval_hours` was
    # configurable, displayed, and read by nothing that started a sync, so every
    # import had to be triggered by hand. Set false to run Core purely on-demand
    # (a second Core process used only for its HTTP API, say).
    SCHEDULER_ENABLED: bool = True

    # ── Session cookies ──────────────────────────────────────────────────────
    # Browser sessions are carried in httpOnly cookies so that a cross-site
    # scripting flaw cannot read the credential. Defaults are the secure ones:
    # override only for a deployment that genuinely cannot serve HTTPS.
    #
    # Secure=True is safe for local development: browsers treat http://localhost
    # and http://127.0.0.1 as trustworthy origins and accept Secure cookies there.
    COOKIE_SECURE: bool = True
    # "lax" lets the cookie ride top-level navigations (needed for the OIDC
    # redirect back from the provider) while blocking cross-site form posts.
    COOKIE_SAMESITE: str = "lax"
    # Leave unset so the cookie is host-only. Set it only when the dashboard and
    # API are on different subdomains of one registrable domain.
    COOKIE_DOMAIN: str | None = None

    # Yazio's mobile-app OAuth client, used when a user configures the Yazio
    # connector with an email and password: Core exchanges them for a token so
    # the password itself is never stored. Public by construction — it ships
    # inside Yazio's app and is not ours to rotate. Configuration rather than a
    # literal so a deployment with its own registered client can substitute it,
    # and so the value exists in exactly one place. See services/importers/yazio.
    YAZIO_CLIENT_ID: str = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
    YAZIO_CLIENT_SECRET: str = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"

    # Where an identity provider sends the browser after RP-initiated logout.
    # Must be registered with the provider; an unregistered value is usually
    # rejected outright, which is the safe failure.
    POST_LOGOUT_REDIRECT_URI: str = "http://127.0.0.1:8000/"

    model_config = SettingsConfigDict(env_file=str(_ROOT_ENV), env_file_encoding="utf-8", extra="ignore")

    @property
    def internal_service_secrets(self) -> dict[str, str]:
        """Parse per-service credentials without exposing their values in logs."""
        if not self.INTERNAL_SERVICE_SECRETS:
            return {}
        try:
            value = json.loads(self.INTERNAL_SERVICE_SECRETS)
        except (TypeError, ValueError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            str(name): secret
            for name, secret in value.items()
            if isinstance(name, str) and isinstance(secret, str) and secret
        }

settings = Settings()
