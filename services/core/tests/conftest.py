import asyncio
import sys

import pytest

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(autouse=True)
def registration_open(monkeypatch):
    """Pin ALLOW_REGISTRATION for the whole suite.

    It now defaults to False, and a developer's `.env` may set anything. Either
    way, a test that creates its fixtures by calling `/auth/signup` would then
    pass or fail depending on the machine it runs on, which AGENTS.md rule 10
    forbids — and the failure would arrive in CI, where there is no `.env`, long
    after the change that caused it.

    Tests that are *about* registration being closed override this themselves;
    a monkeypatch inside the test wins over an autouse fixture.
    """
    from core.config import settings

    monkeypatch.setattr(settings, "ALLOW_REGISTRATION", True, raising=False)
