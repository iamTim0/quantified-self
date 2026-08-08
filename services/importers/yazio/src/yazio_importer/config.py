"""Yazio Importer Configuration Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://localhost:8001"
    # NOTE: TENANT_ID was removed deliberately. It defaulted to the workspace
    # UUID that infra/db/init.sql used to seed, so it named a tenant that no
    # longer exists and, worse, gave every code path a plausible-looking tenant
    # to fall back on. The tenant comes from the sync task on NATS, which is the
    # only place that knows it (AGENTS.md rule 2).
    SOURCE_ID: str = "yazio_importer"
    YAZIO_API_BASE_URL: str = "https://yzapi.yazio.com"
    POLL_LOOKBACK_DAYS: int = 30

    # Yazio's own mobile-app OAuth client, not a secret of ours: it is embedded in
    # a shipped app, is what every unofficial Yazio client uses, and we could not
    # rotate it if we wanted to. It was hardcoded in client.py, which read as a
    # leaked credential and made it impossible to substitute one.
    #
    # Configurable so a deployment that registers its own client with Yazio can
    # use it. The *user's* Yazio credentials are a different thing entirely: they
    # are configured in the dashboard and fetched from Core encrypted (rule 8).
    YAZIO_CLIENT_ID: str = "1_4hiybetvfksgw40o0sog4s884kwc840wwso8go4k8c04goo4c"
    YAZIO_CLIENT_SECRET: str = "6rok2m65xuskgkgogw40wkkk8sw0osg84s8cggsc4woos4s8o"

    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
