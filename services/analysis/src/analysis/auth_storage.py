"""Private encrypted persistence for Codex's opaque ``auth.json`` cache.

The official Codex file credential store writes a password-like token cache to
``CODEX_HOME/auth.json``. Analysis gives Codex a RAM-backed home in Compose and
persists only an encrypted byte-for-byte copy outside that tmpfs. This module
never parses, logs, or returns the credential contents.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from analysis.config import settings

logger = logging.getLogger(__name__)

DEFAULT_DEV_KEY = "dev-secret-shared-encryption-key-qs-2026"


def _fernet() -> Fernet:
    """Build the same deterministic Fernet key derivation used by Core."""
    key_string = settings.ENCRYPTION_KEY or DEFAULT_DEV_KEY
    if len(key_string) < 16:
        raise ValueError("ENCRYPTION_KEY must be at least 16 characters")
    digest = hashlib.sha256(key_string.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write a mode-0600 file and replace the destination atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def restore_auth_blob() -> bool:
    """Restore the encrypted cache into Codex's ephemeral home if available."""
    auth_path = settings.chat_codex_home / "auth.json"
    blob_path = settings.chat_auth_blob_path
    if auth_path.exists() or not blob_path.is_file():
        return False
    try:
        encrypted = blob_path.read_bytes()
        if not encrypted:
            return False
        plaintext = _fernet().decrypt(encrypted)
        if not plaintext:
            return False
        _atomic_write(auth_path, plaintext)
        return True
    except (InvalidToken, OSError, ValueError):
        # Do not expose token material, paths supplied by a deployment, or
        # cryptographic exception details in service logs.
        logger.warning("Codex auth cache could not be restored; device login may be required")
        return False


def persist_auth_blob() -> bool:
    """Encrypt and atomically replace the persistent cache after account auth."""
    auth_path = settings.chat_codex_home / "auth.json"
    try:
        plaintext = auth_path.read_bytes()
        if not plaintext:
            return False
        encrypted = _fernet().encrypt(plaintext)
        _atomic_write(settings.chat_auth_blob_path, encrypted)
        return True
    except (OSError, ValueError):
        # Persistence failure must not turn an already authenticated session
        # into an outage; the next restart can ask for device login again.
        logger.warning("Codex auth cache could not be persisted; device login may be required")
        return False
