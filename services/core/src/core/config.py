from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-core-service"
    DATABASE_URL: str = "postgresql+asyncpg://qs_dev:qs_dev_password@127.0.0.1:5433/quantified_self"
    NATS_URL: str = "nats://127.0.0.1:4222"
    GRPC_PORT: int = 50051

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
