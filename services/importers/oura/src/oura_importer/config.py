from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    OURA_API_BASE_URL: str = "https://api.ouraring.com/v2/usercollection"
    OURA_ACCESS_TOKEN: str = ""
    TENANT_ID: str = "tenant_id_placeholder"
    SOURCE_ID: str = "oura_source_placeholder"
    POLL_INTERVAL_SECONDS: int = 3600

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
