"""Apple Health Importer Configuration Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-importer-apple-health"
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    PORT: int = 8005
    SOURCE_TYPE: str = "apple_health"
    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""
    # NOTE: DEFAULT_TENANT_ID was removed deliberately. It let an unauthenticated
    # caller ingest into a well-known tenant whenever no header was supplied.

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
