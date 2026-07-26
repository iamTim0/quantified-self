from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-api-gateway"
    ENVIRONMENT: str = "dev"
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    ANALYSIS_SERVICE_URL: str = "http://127.0.0.1:8002"
    JWT_SECRET: str = "dev-secret-key-quantified-self-2026"
    JWT_ALGORITHM: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
