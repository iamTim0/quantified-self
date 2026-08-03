"""Streak Importer Configuration Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-importer-streak"
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    PORT: int = 8006
    SOURCE_TYPE: str = "streak"
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
