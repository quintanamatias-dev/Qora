"""Phase 3 (client-integrations-secrets) — Task 1.1-1.3: crypto module + settings.

Covers:
- cryptography is installed and importable
- Settings.qora_secrets_master_key loads from the environment
- SecretCrypto encrypt/decrypt round-trip, key rotation, and the
  master-key-absent get_secret_crypto() contract (P3-D2).
"""

from __future__ import annotations


def test_cryptography_is_importable():
    """The cryptography dependency is installed (task 1.1)."""
    from cryptography.fernet import Fernet, MultiFernet  # noqa: F401


def test_settings_accepts_master_key_env_var(monkeypatch):
    """QORA_SECRETS_MASTER_KEY populates Settings.qora_secrets_master_key; unset -> None."""
    from cryptography.fernet import Fernet

    from app.core.config import Settings

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("QORA_SECRETS_MASTER_KEY", key)
    settings = Settings(
        openai_api_key="sk-test", elevenlabs_api_key="el-test"
    )
    assert settings.qora_secrets_master_key is not None
    assert settings.qora_secrets_master_key.get_secret_value() == key

    monkeypatch.delenv("QORA_SECRETS_MASTER_KEY")
    settings_unset = Settings(
        openai_api_key="sk-test", elevenlabs_api_key="el-test"
    )
    assert settings_unset.qora_secrets_master_key is None


def test_secret_crypto_round_trip():
    """Encrypt -> decrypt returns the original plaintext; ciphertext differs from plaintext."""
    from cryptography.fernet import Fernet

    from app.core.crypto import SecretCrypto

    key = Fernet.generate_key().decode()
    crypto = SecretCrypto([key])

    ciphertext, key_id = crypto.encrypt("super-secret-value")
    assert ciphertext != b"super-secret-value"
    assert isinstance(key_id, str) and key_id

    plaintext = crypto.decrypt(ciphertext)
    assert plaintext == "super-secret-value"


def test_secret_crypto_rotation_decrypts_old_key():
    """A value encrypted with an old key still decrypts once that key is kept in the list."""
    from cryptography.fernet import Fernet

    from app.core.crypto import SecretCrypto

    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    crypto_a = SecretCrypto([key_a])
    ciphertext, _ = crypto_a.encrypt("rotated-secret")

    # key B is now first (encrypts new values); key A retained second (decrypts old ones).
    crypto_rotated = SecretCrypto([key_b, key_a])
    assert crypto_rotated.decrypt(ciphertext) == "rotated-secret"

    new_ciphertext, new_key_id = crypto_rotated.encrypt("new-secret")
    old_key_id = crypto_a.encrypt("anything")[1]
    assert new_key_id != old_key_id
    assert crypto_rotated.decrypt(new_ciphertext) == "new-secret"


def test_get_secret_crypto_returns_none_without_master_key(monkeypatch):
    """get_secret_crypto() returns None, never raises, when no master key is configured."""
    monkeypatch.delenv("QORA_SECRETS_MASTER_KEY", raising=False)

    from app.core.crypto import get_secret_crypto

    assert get_secret_crypto() is None
