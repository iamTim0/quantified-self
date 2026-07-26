from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    NATS_URL: str = "nats://127.0.0.1:4222"
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    OURA_API_BASE_URL: str = "https://api.ouraring.com"
    TENANT_ID: str = "00000000-0000-0000-0000-000000000001"
    SOURCE_ID: str = "00000000-0000-0000-0000-000000000002"
    POLL_INTERVAL_SECONDS: int = 3600
    POLL_LOOKBACK_DAYS: int = 7

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
