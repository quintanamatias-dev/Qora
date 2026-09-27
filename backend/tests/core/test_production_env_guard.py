"""QORA_ENV=production refuses insecure configurations (multi-tenant-readiness WU4)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings

_SECURE_PROD = dict(
    openai_api_key=SecretStr("sk-test-openai-placeholder-for-unit-tests"),
    elevenlabs_api_key=SecretStr("sk-el-test-placeholder-for-unit-tests"),
    qora_api_key=SecretStr("test-admin-key-for-unit-tests"),
    qora_env="production",
    qora_webhook_auth_enabled=True,
    qora_webhook_secret=SecretStr("a-strong-webhook-secret-for-tests"),
    qora_allowed_origins="https://app.qora.example",
    qora_docs_enabled=False,
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **{**_SECURE_PROD, **overrides})


def test_secure_production_config_starts():
    assert _settings().qora_env == "production"


def test_default_environment_is_development():
    s = Settings(
        _env_file=None,
        openai_api_key=SecretStr("sk-test-openai-placeholder-for-unit-tests"),
        elevenlabs_api_key=SecretStr("sk-el-test-placeholder-for-unit-tests"),
        qora_api_key=SecretStr("test-admin-key-for-unit-tests"),
    )
    assert s.qora_env == "development"


@pytest.mark.parametrize(
    ("override", "variable"),
    [
        ({"qora_webhook_auth_enabled": False}, "QORA_WEBHOOK_AUTH_ENABLED"),
        ({"qora_allowed_origins": "*"}, "QORA_ALLOWED_ORIGINS"),
        ({"qora_docs_enabled": True}, "QORA_DOCS_ENABLED"),
    ],
)
def test_production_rejects_insecure_setting(override, variable):
    with pytest.raises(ValidationError) as exc:
        _settings(**override)
    assert variable in str(exc.value)


def test_development_allows_open_defaults():
    s = _settings(qora_env="development", qora_webhook_auth_enabled=False, qora_allowed_origins="*", qora_docs_enabled=True)
    assert s.qora_env == "development"


def test_rejects_unknown_environment():
    with pytest.raises(ValidationError):
        _settings(qora_env="prod")
