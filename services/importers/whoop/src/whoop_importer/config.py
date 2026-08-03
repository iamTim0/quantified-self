"""Configuration settings for WHOOP Importer Service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    TENANT_ID: str = "56fe04c2-b103-40f1-b5f4-2326d1c52830"
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    WHOOP_API_BASE_URL: str = "https://api.prod.whoop.com/developer"
    POLL_INTERVAL_HOURS: int = 24
    POLL_LOOKBACK_DAYS: int = 30

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
