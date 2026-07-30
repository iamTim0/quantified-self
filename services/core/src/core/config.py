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
    SERVICE_NAME: str = "qs-core-service"
    DATABASE_URL: str = "postgresql+asyncpg://qs_dev:qs_dev_password@127.0.0.1:5433/quantified_self"
    NATS_URL: str = "nats://127.0.0.1:4222"
    GRPC_PORT: int = 50051
    JWT_SECRET: str = _default_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    ENCRYPTION_KEY: str = "dev-secret-shared-encryption-key-qs-2026"

    model_config = SettingsConfigDict(env_file=str(_ROOT_ENV), env_file_encoding="utf-8", extra="ignore")

settings = Settings()
