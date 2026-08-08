import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_root_env() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".env").exists():
            return parent / ".env"
    return current.parents[min(4, len(current.parents) - 1)] / ".env"


_ROOT_ENV = _find_root_env()


def _default_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "dev-secret-key-quantified-self-2026")


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-api-gateway"
    ENVIRONMENT: str = "production"  # SECURITY: Default to production, not dev
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    ANALYSIS_SERVICE_URL: str = "http://127.0.0.1:8002"
    APPLE_HEALTH_IMPORTER_URL: str = "http://127.0.0.1:8005"
    STREAK_IMPORTER_URL: str = "http://127.0.0.1:8006"
    JWT_SECRET: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    ALLOWED_ORIGINS: str = "http://localhost:3000"  # Comma-separated CORS origins
    PUBLIC_BASE_URL: str = "http://127.0.0.1:8000"
    DASHBOARD_URL: str = "http://dashboard:3000"
    # Off by default: this is a personal analytics platform, and a public
    # deployment with open signup is a decision, not a default. Create the
    # first account with `python -m core.create_owner`; turn this on only
    # for a deployment that is meant to accept strangers.
    ALLOW_REGISTRATION: bool = False

    model_config = SettingsConfigDict(env_file=str(_ROOT_ENV), env_file_encoding="utf-8", extra="ignore")

settings = Settings()
