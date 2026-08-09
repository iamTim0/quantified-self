"""Make every service package importable for the end-to-end suite.

`task test:e2e` runs these tests with a single importer's virtualenv, but the
modules import transformers from all eight importers plus Core and the Gateway.
Without this the whole suite failed at collection with ModuleNotFoundError, so it
had never actually run.

Adding the source roots to sys.path keeps the tests runnable from any of the
per-service virtualenvs, as long as that venv has the third-party packages the
imported modules need (the transformers themselves are stdlib-only).
"""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_SOURCE_ROOTS = [
    REPO_ROOT / "services" / "core" / "src",
    REPO_ROOT / "services" / "api-gateway" / "src",
    REPO_ROOT / "packages" / "shared-schemas" / "src",
]
_SOURCE_ROOTS += sorted(
    path / "src"
    for path in (REPO_ROOT / "services" / "importers").iterdir()
    if (path / "src").is_dir()
)

for source_root in _SOURCE_ROOTS:
    entry = str(source_root)
    if entry not in sys.path:
        sys.path.insert(0, entry)


class E2EMockNATSClient:
    """Record task publications without requiring a broker in the API E2E suite."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []

    async def publish(self, subject: str, payload: bytes) -> None:
        """Capture the subject and payload that Core would send to an importer."""
        self.published.append((subject, payload))


@pytest.fixture(autouse=True)
def mock_nats_for_e2e() -> Iterator[None]:
    """Give each API test an isolated broker boundary and clear it afterward."""
    from core.main import app

    app.state.nats_client = E2EMockNATSClient()
    yield
    app.state.nats_client = None
