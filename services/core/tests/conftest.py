import asyncio
import sys

import pytest
import pytest_asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest_asyncio.fixture(autouse=True)
async def dispose_pooled_connections():
    """Return every pooled connection at the end of each test.

    The engine is now pooled rather than `NullPool` — a connection per data point
    was the dominant cost of a large import. Pooling is right for the two
    long-running processes that hold the engine, but pytest-asyncio gives each
    test its own event loop, and an asyncpg connection belongs to the loop that
    opened it. Without this, the second test to run would borrow a connection
    created in a loop that no longer exists and fail somewhere unrelated to what
    it was testing.
    """
    yield
    from core.db.session import engine

    await engine.dispose()


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
