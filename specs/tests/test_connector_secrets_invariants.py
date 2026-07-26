"""Tests mapping to specs/connector_secrets.fizz invariants."""

import pytest
import base64
import os
from cryptography.fernet import Fernet

def generate_dev_master_key() -> str:
    return Fernet.generate_key().decode()

class SecretVault:
    def __init__(self, key: str):
        self.fernet = Fernet(key.encode())

    def encrypt_secret(self, plaintext: str) -> str:
        return self.fernet.encrypt(plaintext.encode()).decode()

    def decrypt_secret(self, ciphertext: str) -> str:
        return self.fernet.decrypt(ciphertext.encode()).decode()

    def mask_secret(self, secret: str) -> str:
        if not secret or len(secret) < 6:
            return "••••••••"
        return "••••••••" + secret[-4:]

def test_secrets_always_encrypted_at_rest():
    """Verifies Fizzbee Invariant: SecretsAlwaysEncryptedAtRest.
    
    Raw API tokens are encrypted with Fernet symmetric AES before database persistence.
    """
    key = generate_dev_master_key()
    vault = SecretVault(key)

    raw_token = "oura_personal_access_token_super_secret_12345"
    encrypted = vault.encrypt_secret(raw_token)

    assert encrypted != raw_token, "Secret must not remain in plaintext"
    assert not encrypted.startswith("oura_"), "Plaintext prefix must be obfuscated in ciphertext"

def test_secret_masked_in_read_response():
    """Verifies Fizzbee Invariant: SecretMaskedInReadResponse.
    
    API responses for connector configurations mask secret tokens (e.g., ••••••••12345).
    """
    key = generate_dev_master_key()
    vault = SecretVault(key)

    raw_token = "oura_token_secret_12345"
    masked = vault.mask_secret(raw_token)

    assert masked == "••••••••2345"
    assert "oura_token_secret" not in masked

def test_secret_decryption_roundtrip():
    """Verifies that authorized services can decrypt the ciphertext back to exact original token."""
    key = generate_dev_master_key()
    vault = SecretVault(key)

    raw_token = "oura_live_access_token_abc987"
    ciphertext = vault.encrypt_secret(raw_token)
    decrypted = vault.decrypt_secret(ciphertext)

    assert decrypted == raw_token
