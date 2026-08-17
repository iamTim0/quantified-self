"""github importer settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-importer-github"
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    HEALTH_PORT: int = 8014
    #: GitHub's own API. Overridable for GitHub Enterprise Server, whose REST root
    #: is `https://<host>/api/v3`. Loopback and a real port in the default (rule 18)
    #: does not apply to a third-party API: there is no local GitHub to name.
    GITHUB_API_BASE_URL: str = "https://api.github.com"
    GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"
    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""

    model_config = SettingsConfigDict(extra="ignore")


settings = Settings()
