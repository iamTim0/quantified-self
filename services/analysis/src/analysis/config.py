import hashlib
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_root_env() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".env").exists():
            return parent / ".env"
    return current.parents[min(4, len(current.parents) - 1)] / ".env"


_ROOT_ENV = _find_root_env()


class Settings(BaseSettings):
    SERVICE_NAME: str = "qs-analysis-service"
    # Loopback for a local checkout; Compose sets the container name, which is
    # `core`. The default named `core-service`, a host that exists in neither
    # place, so a locally started Analysis service could not reach Core at all.
    CORE_GRPC_URL: str = "127.0.0.1:50051"

    # There is deliberately no DATABASE_URL here. This service reads through
    # Core's gRPC API and owns no database connection (AGENTS.md rules 1 and 3).

    # Shared secret for the internal service credential this presents to Core.
    # Empty means "derive the same deterministic dev value Core derives", so a
    # local checkout works without configuration while a deployment sets both.
    INTERNAL_SERVICE_SECRET: str = ""
    JWT_SECRET: str = os.environ.get(
        "JWT_SECRET", "dev-secret-key-quantified-self-2026"
    )
    # The MCP endpoint is internal in v1. Explicit hosts keep DNS-rebinding
    # protection enabled without making a local checkout depend on Compose DNS.
    MCP_ALLOWED_HOSTS: str = (
        "127.0.0.1,127.0.0.1:*,localhost,localhost:*,[::1],[::1]:*,analysis,analysis:*"
    )
    MCP_ALLOWED_ORIGINS: str = ""

    # The chat uses the official Codex app server and therefore accepts a
    # ChatGPT subscription login instead of an OpenAI API key. Codex keeps that
    # credential in the operating-system keyring; the platform never reads,
    # logs, persists, or forwards it.
    CHAT_ENABLED: bool = True
    CHAT_CODEX_COMMAND: str = "codex"
    CHAT_CREDENTIALS_STORE: Literal["keyring", "file"] = "keyring"
    CHAT_MODEL: str = ""
    CHAT_ALLOWED_ROLES: str = "owner"
    CHAT_THREAD_TTL_MINUTES: int = 720
    CHAT_TURN_TIMEOUT_SECONDS: int = 300
    CHAT_MAX_MESSAGE_CHARS: int = 8_000

    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV), env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def internal_secret(self) -> str:
        """Must match core.security.tokens._internal_secret exactly.

        Same derivation on both sides, so a dev checkout needs no shared
        configuration and a deployment that sets INTERNAL_SERVICE_SECRET gets a
        real secret. If these two ever diverge, every gRPC call fails closed with
        UNAUTHENTICATED rather than succeeding unauthenticated.
        """
        if self.INTERNAL_SERVICE_SECRET:
            return self.INTERNAL_SERVICE_SECRET
        return hashlib.sha256(
            f"internal-service::{self.JWT_SECRET}".encode()
        ).hexdigest()

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        """Configured Host allowlist for the Streamable HTTP transport."""
        return [
            value.strip()
            for value in self.MCP_ALLOWED_HOSTS.split(",")
            if value.strip()
        ]

    @property
    def mcp_allowed_origins(self) -> list[str]:
        """Configured browser Origin allowlist; non-browser clients omit Origin."""
        return [
            value.strip()
            for value in self.MCP_ALLOWED_ORIGINS.split(",")
            if value.strip()
        ]

    @property
    def chat_allowed_roles(self) -> frozenset[str]:
        """Platform roles permitted to use the operator's subscription."""
        return frozenset(
            value.strip()
            for value in self.CHAT_ALLOWED_ROLES.split(",")
            if value.strip()
        )

    @property
    def chat_workdir(self) -> Path:
        """An empty service-local workspace that exposes no platform files."""
        return Path(tempfile.gettempdir()) / "quantified-self-chat"

    @property
    def chat_codex_home(self) -> Path:
        """Isolated Codex config home; Compose supplies a RAM-backed override."""
        configured = os.environ.get("CODEX_HOME")
        return (
            Path(configured)
            if configured
            else Path(tempfile.gettempdir()) / "quantified-self-codex"
        )


settings = Settings()
