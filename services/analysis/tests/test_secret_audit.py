"""Analysis must not verify real sessions against a secret this repository prints.

The Analysis service re-validates the user's Bearer token itself rather than
trusting the Gateway hop, so it holds the same ``JWT_SECRET`` as Core and the
Gateway -- and inherited the same gap. Both of those call an ``audit_secrets()``
of their own at startup; this service read the published default and called
nothing, which is precisely the hole ``core.security.secret_audit`` documents:
the compose ``${VAR:?}`` guard covers ``docker compose up`` and nothing else.
"""

from __future__ import annotations

import logging

import pytest
from analysis import main as analysis_main
from analysis.config import settings

PUBLISHED = "dev-secret-key-quantified-self-2026"


def test_analysis_refuses_to_start_in_production_with_a_published_secret(monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", PUBLISHED, raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        analysis_main.audit_secrets()


@pytest.mark.parametrize("environment", ["production", "prod", "staging"])
def test_every_production_like_environment_refuses(monkeypatch, environment):
    """Staging holds real sessions too, so it is not a development environment."""
    monkeypatch.setattr(settings, "JWT_SECRET", PUBLISHED, raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment, raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        analysis_main.audit_secrets()


def test_a_development_analysis_warns_instead(monkeypatch, caplog):
    """A laptop and CI must keep working, or the check gets deleted."""
    monkeypatch.setattr(settings, "JWT_SECRET", PUBLISHED, raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "dev", raising=False)

    with caplog.at_level(logging.WARNING):
        analysis_main.audit_secrets()

    assert any("JWT_SECRET" in record.getMessage() for record in caplog.records)


def test_a_configured_secret_passes_silently(monkeypatch, caplog):
    monkeypatch.setattr(settings, "JWT_SECRET", "a-real-secret-nobody-published", raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)

    with caplog.at_level(logging.WARNING):
        analysis_main.audit_secrets()

    assert not caplog.records


def test_the_shared_encryption_defaults_count_as_published(monkeypatch):
    """Whatever variable it arrives in, a value printed here is public knowledge."""
    monkeypatch.setattr(
        settings, "JWT_SECRET", "dev-secret-shared-encryption-key-qs-2026", raising=False
    )
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        analysis_main.audit_secrets()
