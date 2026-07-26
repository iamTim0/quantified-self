"""Cryptographic module for encrypting connector credentials at rest.

Uses Fernet symmetric AES-128-CBC encryption.
Ensures compliance with Fizzbee Invariants:
- SecretsAlwaysEncryptedAtRest
- SecretMaskedInReadResponse
"""

import base64
import hashlib
import logging
import os

from core.config import settings
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# Master key fallback for local development
DEV_MASTER_KEY = b'u3vF81M5q9x0L1k7j5H3n9B2v7C1m6N4p8Q0w2E4r6T='

def _get_fernet_instance() -> Fernet:
    key_str = getattr(settings, "ENCRYPTION_KEY", None) or os.environ.get("ENCRYPTION_KEY")
    if not key_str:
        key_bytes = DEV_MASTER_KEY
    else:
        # Derives a deterministic 32-byte key using SHA-256 and base64 encodes for Fernet
        hashed = hashlib.sha256(key_str.encode("utf-8")).digest()
        key_bytes = base64.urlsafe_b64encode(hashed)
    return Fernet(key_bytes)

def encrypt_secret(plaintext: str) -> str:
    """Encrypt plaintext string using Fernet symmetric encryption."""
    if not plaintext:
        return ""
    f = _get_fernet_instance()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")

def decrypt_secret(ciphertext: str) -> str:
    """Decrypt ciphertext string back to original plaintext."""
    if not ciphertext:
        return ""
    f = _get_fernet_instance()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to decrypt secret: {e}")
        return ""

def mask_secret(secret: str) -> str:
    """Mask secret for safe API and UI presentation (never expose raw token)."""
    if not secret:
        return ""
    if len(secret) <= 6:
        return "••••••••"
    return "••••••••" + secret[-4:]
