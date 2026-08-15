"""weather importer settings."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-importer-weather"
    NATS_URL: str = "nats://localhost:4222"
    CORE_SERVICE_URL: str = "http://127.0.0.1:8001"
    HEALTH_PORT: int = 8012
    API_BASE_URL: str = ""
    # Bearer credential presented to Core's internal API. Must match Core's
    # INTERNAL_SERVICE_SECRET; empty derives the shared dev default.
    INTERNAL_SERVICE_SECRET: str = ""

    # Whether the connector may fetch a URL that resolves to a private, loopback
    # or link-local address.
    #
    # Off by default. The connector fetches a URL the *tenant* supplies, from
    # inside the compose network, so with this on any signed-in member can make
    # the importer reach core-service, nats, the cloud metadata service, or scan
    # the internal network — and read the outcome back from the connector's own
    # error message. A public weather API needs none of that.
    #
    # A self-hoster running Open-Meteo on their own LAN turns it on deliberately,
    # which is the difference between a considered choice and an open door.
    ALLOW_PRIVATE_PROVIDER_HOSTS: bool = False

    model_config = SettingsConfigDict(extra="ignore")
settings = Settings()
