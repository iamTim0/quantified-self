"""The imprint and the privacy policy, as text an operator owns.

Both documents once shipped as TSX components full of ``[placeholder]`` markers, so
publishing a real legal notice meant editing source and rebuilding an image. A
deployment whose owner does not do that served a public imprint naming nobody,
which is the condition § 5 DDG exists to prevent. The templates are gone: what a
deployment publishes is what its operator wrote here, and nothing else.

What these tests hold down is not the storage — that is a row — but the four
rules around it that are easy to regress and expensive to notice:

* the public read needs no session, because an imprint behind a login publishes
  nothing;
* the write needs the owner or admin role;
* the German half governs, so English text without German text is refused;
* clearing the German half unpublishes the document, reported as ``source ==
  "default"``, rather than publishing an empty page where a notice belongs.

Maps to Fizzbee Invariants:
- NoUnauthorizedAccess
"""

import pytest
import pytest_asyncio
from core.config import settings
from core.db.models import LegalDocument
from core.db.session import async_session_maker
from core.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from tests.db_helpers import (
    as_platform_tenant,
    auth_headers,
    cleanup_test_tenant,
    create_test_tenant,
)

app.state.testing = True


@pytest_asyncio.fixture(autouse=True)
async def _no_stored_documents():
    """Start and end with an empty table.

    ``legal_documents`` is deployment-wide by design — an imprint identifies the
    operator, not a workspace — so it is one of the few tables a test cannot
    isolate with a tenant of its own. Rule 10 still applies: the fixtures are
    created here and removed here, and nothing is assumed about what ran before.
    """
    async def _clear() -> None:
        async with async_session_maker() as session:
            await session.execute(delete(LegalDocument))
            await session.commit()

    await _clear()
    yield
    await _clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://testserver")


@pytest.mark.asyncio
async def test_public_read_needs_no_session_and_reports_the_default():
    """An imprint only a signed-in reader can see does not discharge the duty to publish one."""
    async with _client() as ac:
        res = await ac.get("/api/v1/legal/documents/imprint")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "default"
    assert body["body_de"] is None
    assert body["body_en"] is None


@pytest.mark.asyncio
async def test_unknown_slug_is_not_found_rather_than_an_empty_document():
    """The set is closed. A slug nothing renders must not read as a blank notice."""
    async with _client() as ac:
        res = await ac.get("/api/v1/legal/documents/terms")

    assert res.status_code == 404


@pytest.mark.asyncio
async def test_saving_publishes_both_halves_on_the_public_route(monkeypatch: pytest.MonkeyPatch):
    tenant_id = await create_test_tenant()
    as_platform_tenant(monkeypatch, tenant_id)
    try:
        async with _client() as ac:
            saved = await ac.put(
                "/api/v1/data/legal/documents/privacy",
                headers=auth_headers(tenant_id),
                json={
                    "body_de": "# Datenschutz\n\nVerantwortlich ist die Beispiel GmbH.",
                    "body_en": "# Privacy\n\nThe controller is Example Ltd.",
                },
            )
            public = await ac.get("/api/v1/legal/documents/privacy")

        assert saved.status_code == 200, saved.text
        assert saved.json()["source"] == "custom"

        assert public.status_code == 200
        body = public.json()
        assert body["source"] == "custom"
        assert body["body_de"].startswith("# Datenschutz")
        assert body["body_en"].startswith("# Privacy")
        assert body["updated_at"] is not None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_english_without_german_is_refused(monkeypatch: pytest.MonkeyPatch):
    """The German half is the binding one (rule 16), so it cannot be the missing one."""
    tenant_id = await create_test_tenant()
    as_platform_tenant(monkeypatch, tenant_id)
    try:
        async with _client() as ac:
            res = await ac.put(
                "/api/v1/data/legal/documents/imprint",
                headers=auth_headers(tenant_id),
                json={"body_de": "  ", "body_en": "# Legal notice"},
            )
            public = await ac.get("/api/v1/legal/documents/imprint")

        assert res.status_code == 422, res.text
        # Nothing was written: a refused save must not half-publish.
        assert public.json()["source"] == "default"
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_clearing_the_german_text_unpublishes_the_document(monkeypatch: pytest.MonkeyPatch):
    """Emptying the field withdraws the document, rather than publishing a blank page."""
    tenant_id = await create_test_tenant()
    as_platform_tenant(monkeypatch, tenant_id)
    try:
        async with _client() as ac:
            await ac.put(
                "/api/v1/data/legal/documents/imprint",
                headers=auth_headers(tenant_id),
                json={"body_de": "# Impressum\n\nBeispiel GmbH", "body_en": None},
            )
            cleared = await ac.put(
                "/api/v1/data/legal/documents/imprint",
                headers=auth_headers(tenant_id),
                json={"body_de": "", "body_en": ""},
            )
            public = await ac.get("/api/v1/legal/documents/imprint")

        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["source"] == "default"
        assert public.json()["source"] == "default"
        assert public.json()["body_de"] is None
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_member_may_not_read_or_write_the_documents(monkeypatch: pytest.MonkeyPatch):
    """Verifies Fizzbee Invariant: NoUnauthorizedAccess"""
    tenant_id = await create_test_tenant()
    try:
        # Made the platform workspace on purpose: without it this test would pass
        # for the wrong reason -- a 403 about the *workspace* rather than about the
        # role, and it would keep passing if the role check were deleted.
        as_platform_tenant(monkeypatch, tenant_id)
        headers = auth_headers(tenant_id, role="member")
        async with _client() as ac:
            listed = await ac.get("/api/v1/data/legal/documents", headers=headers)
            written = await ac.put(
                "/api/v1/data/legal/documents/imprint",
                headers=headers,
                json={"body_de": "# Impressum"},
            )

        assert listed.status_code == 403
        assert written.status_code == 403
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_the_editor_sees_every_document_even_before_one_is_written(monkeypatch: pytest.MonkeyPatch):
    """A document nobody has written is a state, not a gap in the list."""
    tenant_id = await create_test_tenant()
    as_platform_tenant(monkeypatch, tenant_id)
    try:
        async with _client() as ac:
            res = await ac.get(
                "/api/v1/data/legal/documents", headers=auth_headers(tenant_id)
            )

        assert res.status_code == 200, res.text
        slugs = [doc["slug"] for doc in res.json()["documents"]]
        assert slugs == ["imprint", "privacy"]
        assert all(doc["source"] == "default" for doc in res.json()["documents"])
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_an_owner_of_another_workspace_may_not_touch_the_documents(
    monkeypatch: pytest.MonkeyPatch,
):
    """Verifies Fizzbee Invariant: NoUnauthorizedAccess

    The reason ``require_role("owner")`` was not enough. Every account-creation
    path mints an owner -- ``/auth/signup`` and OIDC sign-up each create a fresh
    tenant with the new user as its owner -- so on a deployment with registration
    enabled, "owner" was a role anybody could obtain by signing up. These
    documents have no tenant and are served to every visitor, so that role would
    have let a stranger rewrite the deployment's imprint and privacy policy.
    """
    platform_tenant = await create_test_tenant()
    other_tenant = await create_test_tenant()
    try:
        as_platform_tenant(monkeypatch, platform_tenant)
        async with _client() as ac:
            listed = await ac.get(
                "/api/v1/data/legal/documents", headers=auth_headers(other_tenant)
            )
            written = await ac.put(
                "/api/v1/data/legal/documents/imprint",
                headers=auth_headers(other_tenant),
                json={"body_de": "# Impressum\n\nAttacker GmbH"},
            )
            public = await ac.get("/api/v1/legal/documents/imprint")

        assert listed.status_code == 403
        assert written.status_code == 403
        # And nothing was published: the refusal has to happen before the write.
        assert public.json()["source"] == "default"
    finally:
        await cleanup_test_tenant(other_tenant)
        await cleanup_test_tenant(platform_tenant)


@pytest.mark.asyncio
async def test_the_oldest_workspace_administers_a_deployment_that_configured_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    """The fallback is what makes this a fix rather than a setting to discover.

    Almost every deployment of this platform has exactly one workspace, created by
    whoever installed it. Requiring `PLATFORM_TENANT_ID` before the check did
    anything would have left those deployments exactly as exposed as before, and
    protected only the operators who read the release notes.
    """
    from core.db.session import async_session_maker
    from core.security.auth import platform_tenant_id

    monkeypatch.setattr(settings, "PLATFORM_TENANT_ID", "")
    first = await create_test_tenant()
    second = await create_test_tenant()
    try:
        async with async_session_maker() as session:
            resolved = await platform_tenant_id(session)

        # Not `first`: this database has older tenants from other tests and from a
        # developer's own use. What is asserted is the rule, not a fixture -- the
        # answer is the oldest row, and it is never simply the caller.
        assert resolved is not None
        assert resolved != second
    finally:
        await cleanup_test_tenant(second)
        await cleanup_test_tenant(first)
