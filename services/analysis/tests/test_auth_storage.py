"""Tests for encrypted persistence of the opaque Codex credential cache."""

from __future__ import annotations

import os
from pathlib import Path

from analysis.auth_storage import persist_auth_blob, restore_auth_blob
from analysis.config import settings


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
    assert (blob_path.stat().st_mode & 0o777) == 0o600

    (codex_home / "auth.json").unlink()
    assert restore_auth_blob() is True
    assert (codex_home / "auth.json").read_bytes() == auth_bytes
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
