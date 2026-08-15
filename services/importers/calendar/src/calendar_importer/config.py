"""calendar importer settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-importer-calendar"
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    HEALTH_PORT: int = 8013
    API_BASE_URL: str = ""
    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""

    model_config = SettingsConfigDict(extra="ignore")
settings = Settings()
