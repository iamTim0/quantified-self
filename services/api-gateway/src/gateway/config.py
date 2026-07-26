import os
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_jwt_secret() -> str:
    """Generate a random JWT secret if none is configured.

    SECURITY: This ensures the service never silently uses a predictable secret.
    The random secret changes on every restart, which forces operators to set a
    proper JWT_SECRET env var for any persistent deployment.
    """
    return os.environ.get("JWT_SECRET", f"INSECURE-EPHEMERAL-{secrets.token_urlsafe(32)}")


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-api-gateway"
    ENVIRONMENT: str = "production"  # SECURITY: Default to production, not dev
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    ANALYSIS_SERVICE_URL: str = "http://127.0.0.1:8002"
    JWT_SECRET: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    ALLOWED_ORIGINS: str = "http://localhost:3000"  # Comma-separated CORS origins

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
