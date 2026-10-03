"""Encryption for per-client secrets (client-integrations-secrets, P3-D2).

MultiFernet wraps Settings.qora_secrets_master_key (comma-separated Fernet
keys): the first key encrypts new values, every key is tried on decrypt,
giving standard key-rotation support with no flag-day re-encryption.

A malformed key string only fails when SecretCrypto is actually constructed
(get_secret_crypto(), called at use time by resolve_client_secret/the secret
write endpoint) — never at Settings/app import time. No secret value or
ciphertext is ever logged by this module.
"""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet  # noqa: F401

from app.core.config import Settings


def _fingerprint(key: str) -> str:
    """Short, non-reversible identifier for a Fernet key (for key_id tracking)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


class SecretCrypto:
    """MultiFernet-backed encrypt/decrypt, keyed from QORA_SECRETS_MASTER_KEY."""

    def __init__(self, master_keys: list[str]) -> None:
        self._fernets = [Fernet(key.encode("utf-8")) for key in master_keys]
        self._multi = MultiFernet(self._fernets)
        self._primary_key_id = _fingerprint(master_keys[0])

    def encrypt(self, plaintext: str) -> tuple[bytes, str]:
        """Returns (ciphertext, key_id). key_id identifies the active (first) key."""
        ciphertext = self._multi.encrypt(plaintext.encode("utf-8"))
        return ciphertext, self._primary_key_id

    def decrypt(self, ciphertext: bytes) -> str:
        """Raises InvalidToken if no configured key can decrypt it."""
        return self._multi.decrypt(ciphertext).decode("utf-8")


def get_secret_crypto() -> SecretCrypto | None:
    """Returns None if QORA_SECRETS_MASTER_KEY is not configured.

    Callers MUST handle None by falling back to env resolution (P3-D3),
    never by raising.
    """
    master_key = Settings().qora_secrets_master_key
    if master_key is None:
        return None

    raw = master_key.get_secret_value().strip()
    if not raw:
        return None

    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        return None

    return SecretCrypto(keys)
