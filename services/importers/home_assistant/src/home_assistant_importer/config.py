"""home_assistant importer settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    API_BASE_URL: str = ""
    model_config = SettingsConfigDict(extra="ignore")
settings = Settings()
