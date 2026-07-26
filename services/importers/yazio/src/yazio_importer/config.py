"""Yazio Importer Configuration Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8000"
    TENANT_ID: str = "default_tenant"
    SOURCE_ID: str = "yazio_importer"
    YAZIO_API_BASE_URL: str = "https://yzapi.yazio.com"
    POLL_LOOKBACK_DAYS: int = 7

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
