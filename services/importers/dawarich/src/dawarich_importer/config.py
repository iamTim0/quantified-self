"""Dawarich Importer Configuration Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    TENANT_ID: str = "default_tenant"
    SOURCE_ID: str = "dawarich_importer"
    DAWARICH_API_BASE_URL: str = "http://localhost:3000"
    POLL_LOOKBACK_DAYS: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
