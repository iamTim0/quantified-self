import os
import secrets
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Root .env is 4 levels up from this file: services/api-gateway/src/gateway/config.py
_ROOT_ENV = Path(__file__).resolve().parents[4] / ".env"


def _default_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "dev-secret-key-quantified-self-2026")


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-api-gateway"
    ENVIRONMENT: str = "production"  # SECURITY: Default to production, not dev
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    ANALYSIS_SERVICE_URL: str = "http://127.0.0.1:8002"
    JWT_SECRET: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    ALLOWED_ORIGINS: str = "http://localhost:3000"  # Comma-separated CORS origins

    model_config = SettingsConfigDict(env_file=str(_ROOT_ENV), env_file_encoding="utf-8", extra="ignore")

settings = Settings()
