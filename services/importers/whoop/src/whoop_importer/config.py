"""Configuration settings for WHOOP Importer Service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # NOTE: TENANT_ID was removed deliberately. It defaulted to the workspace
    # UUID that infra/db/init.sql used to seed, so it named a tenant that no
    # longer exists and, worse, gave every code path a plausible-looking tenant
    # to fall back on. The tenant comes from the sync task on NATS, which is the
    # only place that knows it (AGENTS.md rule 2).
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    WHOOP_API_BASE_URL: str = "https://api.prod.whoop.com/developer"
    POLL_INTERVAL_HOURS: int = 24
    POLL_LOOKBACK_DAYS: int = 30

    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
