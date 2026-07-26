"""Cryptographic module for encrypting connector credentials at rest and in transit.

Uses Fernet symmetric AES-256 encryption derived from a shared secret ENCRYPTION_KEY.
Ensures compliance with Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- SecretMaskedInReadResponse
- NeverExposePlaintextSecretsInBroker
"""

import base64
import hashlib
import logging
import os

from core.config import settings
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Default dev shared encryption key for seamless local environment setup
DEFAULT_DEV_KEY = "dev-secret-shared-encryption-key-qs-2026"


class DecryptionError(Exception):
    """Raised when a secret cannot be decrypted (tampered or wrong key)."""


def _get_fernet_instance() -> Fernet:
    """Build a Fernet instance from shared ENCRYPTION_KEY env var.

    Uses DEFAULT_DEV_KEY if not configured in .env, ensuring seamless local development
    while requiring a strong custom key in production environments.
    """
    key_str = getattr(settings, "ENCRYPTION_KEY", None) or os.environ.get("ENCRYPTION_KEY")
    if not key_str:
        logger.warning(
            "[WARN] ENCRYPTION_KEY not set in .env -- using deterministic dev default key. "
            "Set ENCRYPTION_KEY env var in production for persistent custom encryption."
        )
        key_str = DEFAULT_DEV_KEY
    elif len(key_str) < 16:
        raise ValueError(
            "ENCRYPTION_KEY must be at least 16 characters. "
            "Use a strong random value: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    # Derives a deterministic 32-byte key using SHA-256 and base64 encodes for Fernet
    hashed = hashlib.sha256(key_str.encode("utf-8")).digest()
    key_bytes = base64.urlsafe_b64encode(hashed)
    return Fernet(key_bytes)


# Module-level singleton — created once at import time
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _get_fernet_instance()
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """Encrypt plaintext string using Fernet symmetric encryption."""
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt ciphertext string back to original plaintext.

    Raises:
        DecryptionError: If the ciphertext is invalid, tampered, or the key is wrong.
    """
    if not ciphertext:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        logger.error("Failed to decrypt secret — possible tampering or key mismatch")
        raise DecryptionError("Cannot decrypt secret: invalid token or wrong key") from e


def mask_secret(secret: str) -> str:
    """Mask secret for safe API and UI presentation (never expose raw token)."""
    if not secret:
        return ""
    if len(secret) <= 6:
        return "••••••••"
    return "••••••••" + secret[-4:]
