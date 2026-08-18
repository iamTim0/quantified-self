"""Test-suite defaults for the Analysis service.

``Settings.ENVIRONMENT`` defaults to ``production`` deliberately: a process
started with no configuration must refuse to verify real sessions against the
``JWT_SECRET`` this repository publishes -- see ``analysis.main.audit_secrets``.

CI checks the repository out without a ``.env``, so the suite would inherit that
default, and every test that starts the app through ``TestClient`` would fail on
the guard instead of on the behaviour it asserts. A laptop and CI have to keep
working, or a check like that gets deleted rather than fixed.

So the suite says once, here, what it is: a development environment. A test that
wants the production behaviour sets ``ENVIRONMENT`` itself, which runs after this
fixture and overrides it.
"""

from __future__ import annotations

import pytest
from analysis.config import settings


@pytest.fixture(autouse=True)
def _development_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "dev", raising=False)
