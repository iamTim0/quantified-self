"""Dawarich Importer Configuration Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    # NOTE: TENANT_ID was removed deliberately. It defaulted to the workspace
    # UUID that infra/db/init.sql used to seed, so it named a tenant that no
    # longer exists and, worse, gave every code path a plausible-looking tenant
    # to fall back on. The tenant comes from the sync task on NATS, which is the
    # only place that knows it (AGENTS.md rule 2).
    SOURCE_ID: str = "dawarich_importer"
    DAWARICH_API_BASE_URL: str = "http://localhost:3000"
    POLL_LOOKBACK_DAYS: int = 30

    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
