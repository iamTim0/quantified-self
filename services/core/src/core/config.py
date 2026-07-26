import os
import secrets

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", f"INSECURE-EPHEMERAL-{secrets.token_urlsafe(32)}")

class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-core-service"
    DATABASE_URL: str = "postgresql+asyncpg://qs_dev:qs_dev_password@127.0.0.1:5433/quantified_self"
    NATS_URL: str = "nats://127.0.0.1:4222"
    GRPC_PORT: int = 50051
    JWT_SECRET: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
