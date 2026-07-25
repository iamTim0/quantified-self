from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-api-gateway"
    CORE_SERVICE_URL: str = "http://core-service:8000"
    ANALYSIS_SERVICE_URL: str = "http://analysis-service:8000"
    JWT_SECRET: str = "super-secret-key"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
