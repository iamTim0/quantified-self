"""Non-secret runtime configuration for the WHOOP importer."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    WHOOP_API_BASE_URL: str = "https://api.prod.whoop.com/developer"
    HEALTH_HOST: str = "0.0.0.0"
    HEALTH_PORT: int = 8013

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
