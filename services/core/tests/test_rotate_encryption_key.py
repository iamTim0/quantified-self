"""Re-encrypting stored credentials from one ENCRYPTION_KEY to another.

This is the tool that makes roadmap item 23 actionable for the one key that could
not simply be changed. Getting it wrong is expensive in a specific way: a
half-completed rotation leaves rows split across two keys with no record of which
is which, and the credentials are not recoverable from anywhere else.

**There is deliberately no test that runs a committing rotation.** The tool
rewrites every encrypted value in whatever database it is pointed at — by design,
since the key is global — and pointed at a developer's local database that is
their real connector credentials. A test that damages the thing it is run against
before failing is worse than the bug it would catch. The traversal, the JSON
handling and the abort are therefore exercised through dry runs, which roll back,
and the translation decision is tested directly as a pure function. What that
leaves uncovered is the single `await session.commit()` line.

Maps to Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
"""

import uuid

import pytest
from core.config import settings
from core.db.models import DataSource
from core.db.session import async_session_maker
from core.rotate_encryption_key import Report, _translate, fernet_for, rotate
from sqlalchemy import select

from tests.db_helpers import cleanup_test_tenant, create_test_tenant

OLD_KEY = "old-key-for-rotation-tests-0123456789"
NEW_KEY = "new-key-for-rotation-tests-9876543210"
THIRD_KEY = "a-third-key-nobody-configured-12345"

OLD = fernet_for(OLD_KEY)
NEW = fernet_for(NEW_KEY)
THIRD = fernet_for(THIRD_KEY)


def enc(fernet, plaintext: str) -> str:
    return fernet.encrypt(plaintext.encode()).decode()


# ─── the translation decision, as a pure function ────────────


def test_a_value_on_the_old_key_is_re_encrypted():
    report = Report()
    result = _translate(enc(OLD, "secret"), OLD, NEW, "label", report)

    assert NEW.decrypt(result.encode()) == b"secret"
    assert report.reencrypted == 1
    assert report.failures == []


def test_a_value_already_on_the_new_key_is_left_exactly_as_it_was():
    """What makes a re-run after a partial failure safe rather than destructive."""
    report = Report()
    already = enc(NEW, "secret")

    assert _translate(already, OLD, NEW, "label", report) == already
    assert report.already_new == 1
    assert report.reencrypted == 0
    assert report.failures == []


def test_a_value_on_neither_key_is_reported_rather_than_skipped():
    """The expensive mistake, and the reason for the single transaction.

    Skipping the unreadable rows and committing the rest would leave the database
    split across two keys with nothing recording which row is on which.
    """
    report = Report()
    orphan = enc(THIRD, "secret")

    assert _translate(orphan, OLD, NEW, "sources[x].encrypted_token", report) == orphan
    assert report.failures == ["sources[x].encrypted_token"]


def test_an_empty_value_is_counted_and_untouched():
    report = Report()
    assert _translate("", OLD, NEW, "label", report) == ""
    assert report.empty == 1


def test_a_short_key_is_refused():
    with pytest.raises(ValueError):
        fernet_for("too-short")


def test_the_derivation_matches_the_one_core_uses():
    """If it did not, the tool would encrypt into something Core cannot read —
    which looks exactly like a successful rotation until the next sync."""
    from core.security.crypto import _get_fernet_instance

    original = settings.ENCRYPTION_KEY
    try:
        settings.ENCRYPTION_KEY = OLD_KEY
        ciphertext = _get_fernet_instance().encrypt(b"probe")
    finally:
        settings.ENCRYPTION_KEY = original

    assert fernet_for(OLD_KEY).decrypt(ciphertext) == b"probe"


# ─── the database traversal, dry-run only ────────────────────


async def make_source(tenant_id: str, config: dict) -> str:
    source_id = str(uuid.uuid4())
    async with async_session_maker() as session:
        session.add(
            DataSource(
                id=source_id,
                tenant_id=tenant_id,
                source_type="oura",
                display_name="Oura",
                config=config,
            )
        )
        await session.commit()
    return source_id


async def read_config(source_id: str) -> dict:
    async with async_session_maker() as session:
        config = (
            await session.execute(
                select(DataSource.config).where(DataSource.id == source_id)
            )
        ).scalar_one()
    return dict(config or {})


@pytest.mark.asyncio
async def test_a_dry_run_finds_the_stored_secrets_and_writes_nothing():
    """Encrypts its fixture with the configured key, because that is what the
    tool will be asked to read.

    It asserts only about its own row and never that the whole run is clean: this
    runs against whatever database it is pointed at, and the first thing the tool
    found on the developer's was three values on one key, one on another and one
    on neither. That is the tool working, not the test failing.
    """
    tenant_id = await create_test_tenant()
    from core.security.crypto import encrypt_secret

    original = encrypt_secret("access-token-value")
    source_id = await make_source(
        tenant_id, {"encrypted_token": original, "poll_interval_hours": 6}
    )
    try:
        report = await rotate(
            old_key=settings.ENCRYPTION_KEY, new_key=NEW_KEY, dry_run=True
        )

        assert not any(source_id in failure for failure in report.failures)
        assert report.reencrypted >= 1

        config = await read_config(source_id)
        assert config["encrypted_token"] == original
        assert config["poll_interval_hours"] == 6
    finally:
        await cleanup_test_tenant(tenant_id)


@pytest.mark.asyncio
async def test_a_row_on_an_unknown_key_aborts_the_whole_run():
    tenant_id = await create_test_tenant()
    orphan = enc(THIRD, "orphaned-token")
    source_id = await make_source(tenant_id, {"encrypted_token": orphan})
    try:
        report = await rotate(
            old_key=settings.ENCRYPTION_KEY, new_key=NEW_KEY, dry_run=False
        )

        assert any(source_id in failure for failure in report.failures)
        # Not a dry run, and still nothing written: the abort happens before the
        # commit precisely so a wrong --old cannot half-rotate a database.
        assert (await read_config(source_id))["encrypted_token"] == orphan
    finally:
        await cleanup_test_tenant(tenant_id)
