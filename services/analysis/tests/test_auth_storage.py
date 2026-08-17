"""Tests for encrypted persistence of the opaque Codex credential cache."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from analysis.auth_storage import persist_auth_blob, restore_auth_blob
from analysis.config import settings

#: `os.chmod` on Windows sets one bit — read-only — and NTFS expresses the rest
#: through ACLs, so `st_mode & 0o777` reads 0o666 whatever the code asked for. The
#: property is not weaker there, it is stated differently: `%LOCALAPPDATA%\\Temp`
#: is already scoped to the user by inherited ACLs. Asserting the POSIX encoding of
#: it made the whole suite permanently red on a Windows checkout, which is how a
#: red suite stops being read. The service itself only ever runs on Linux.
posix_modes_only = pytest.mark.skipif(
    os.name == "nt", reason="NTFS has no POSIX mode bits; the ACL is the equivalent"
)


def _configure_storage(monkeypatch, root: Path) -> tuple[Path, Path]:
    codex_home = root / "codex-home"
    blob_path = root / "private" / "codex-auth.enc"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(settings, "CHAT_AUTH_BLOB_PATH", str(blob_path))
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "test-analysis-encryption-key")
    codex_home.mkdir()
    return codex_home, blob_path


def test_auth_cache_is_encrypted_and_round_trips(monkeypatch, tmp_path: Path) -> None:
    """Verifies Fizzbee Invariant: SecretsAlwaysEncryptedAtRest."""
    codex_home, blob_path = _configure_storage(monkeypatch, tmp_path)
    auth_bytes = b'{"access_token":"opaque-test-token","account_id":"id"}'
    (codex_home / "auth.json").write_bytes(auth_bytes)

    assert persist_auth_blob() is True
    encrypted = blob_path.read_bytes()
    assert encrypted != auth_bytes
    assert b"opaque-test-token" not in encrypted

    (codex_home / "auth.json").unlink()
    assert restore_auth_blob() is True
    assert (codex_home / "auth.json").read_bytes() == auth_bytes


@posix_modes_only
def test_neither_the_blob_nor_the_restored_cache_is_readable_by_anybody_else(
    monkeypatch, tmp_path: Path
) -> None:
    """The second half of keeping a credential: encrypted *and* not world-readable.

    Split from the round-trip test rather than skipped with it. Encryption is the
    invariant and it holds everywhere; the file mode is defence in depth and can
    only be asserted where the filesystem has modes — so skipping one must not take
    the other with it.
    """
    codex_home, blob_path = _configure_storage(monkeypatch, tmp_path)
    (codex_home / "auth.json").write_bytes(b'{"access_token":"opaque-test-token"}')

    assert persist_auth_blob() is True
    assert (blob_path.stat().st_mode & 0o777) == 0o600

    (codex_home / "auth.json").unlink()
    assert restore_auth_blob() is True
    assert ((codex_home / "auth.json").stat().st_mode & 0o777) == 0o600


def test_invalid_auth_cache_fails_closed_without_creating_plaintext(
    monkeypatch, tmp_path: Path
) -> None:
    """Verifies Fizzbee Invariant: TamperedCredentialsAreRejected."""
    codex_home, blob_path = _configure_storage(monkeypatch, tmp_path)
    blob_path.parent.mkdir()
    blob_path.write_bytes(b"not-a-valid-fernet-token")

    assert restore_auth_blob() is False
    assert not (codex_home / "auth.json").exists()


def test_persistence_without_codex_auth_file_is_a_noop(monkeypatch, tmp_path: Path) -> None:
    """Missing persisted credentials never create a plaintext auth file."""
    codex_home, blob_path = _configure_storage(monkeypatch, tmp_path)

    assert persist_auth_blob() is False
    assert not blob_path.exists()
    assert os.path.isdir(codex_home)
