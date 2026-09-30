"""Unit tests for WorkOS auth Settings fields (design.md §2)."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def _base_kwargs(**overrides):
    kwargs = dict(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        qora_api_key=SecretStr("qora-test-key"),
    )
    kwargs.update(overrides)
    return kwargs


class TestAuthSettingsFields:
    def test_defaults(self):
        s = Settings(**_base_kwargs())
        assert s.workos_api_key is None
        assert s.workos_client_id is None
        assert s.qora_auth_redirect_uri is None
        assert s.qora_superadmin_emails == ""
        assert s.qora_auth_session_ttl_hours == 12

    def test_session_ttl_must_be_positive(self):
        with pytest.raises(ValidationError):
            Settings(**_base_kwargs(qora_auth_session_ttl_hours=0))


class TestLoginEnabled:
    def test_false_when_unset(self):
        assert Settings(**_base_kwargs()).login_enabled is False

    def test_false_when_partially_set(self):
        s = Settings(**_base_kwargs(workos_api_key=SecretStr("sk_x"), workos_client_id="client_x"))
        assert s.login_enabled is False

    def test_true_when_fully_set(self):
        s = Settings(
            **_base_kwargs(
                workos_api_key=SecretStr("sk_x"),
                workos_client_id="client_x",
                qora_auth_redirect_uri="http://localhost:5173/api/v1/auth/callback",
            )
        )
        assert s.login_enabled is True


class TestAuthCookieSecure:
    def test_false_in_dev_with_http_redirect(self):
        s = Settings(
            **_base_kwargs(
                qora_env="development",
                qora_auth_redirect_uri="http://localhost:5173/api/v1/auth/callback",
            )
        )
        assert s.auth_cookie_secure is False

    def test_true_in_dev_with_https_redirect(self):
        s = Settings(
            **_base_kwargs(
                qora_env="development",
                qora_auth_redirect_uri="https://app.example.com/api/v1/auth/callback",
            )
        )
        assert s.auth_cookie_secure is True

    def test_true_in_production(self):
        s = Settings(
            **_base_kwargs(
                qora_env="production",
                workos_api_key=SecretStr("sk_x"),
                workos_client_id="client_x",
                qora_auth_redirect_uri="https://app.example.com/api/v1/auth/callback",
                qora_webhook_auth_enabled=True,
                qora_webhook_secret=SecretStr("wh-secret"),
                qora_allowed_origins="https://app.example.com",
                qora_docs_enabled=False,
            )
        )
        assert s.auth_cookie_secure is True


class TestProductionHardeningRequiresWorkos:
    def _prod_kwargs(self, **overrides):
        base = _base_kwargs(
            qora_env="production",
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("wh-secret"),
            qora_allowed_origins="https://app.example.com",
            qora_docs_enabled=False,
            workos_api_key=SecretStr("sk_x"),
            workos_client_id="client_x",
            qora_auth_redirect_uri="https://app.example.com/api/v1/auth/callback",
        )
        base.update(overrides)
        return base

    def test_production_with_full_workos_config_boots(self):
        Settings(**self._prod_kwargs())

    def test_production_without_workos_api_key_fails(self):
        with pytest.raises(ValidationError, match="WORKOS_API_KEY"):
            Settings(**self._prod_kwargs(workos_api_key=None))

    def test_production_without_workos_client_id_fails(self):
        with pytest.raises(ValidationError, match="WORKOS_CLIENT_ID"):
            Settings(**self._prod_kwargs(workos_client_id=None))

    def test_production_without_redirect_uri_fails(self):
        with pytest.raises(ValidationError, match="QORA_AUTH_REDIRECT_URI must be set"):
            Settings(**self._prod_kwargs(qora_auth_redirect_uri=None))

    def test_production_with_http_redirect_uri_fails(self):
        with pytest.raises(ValidationError, match="https://"):
            Settings(**self._prod_kwargs(qora_auth_redirect_uri="http://app.example.com/api/v1/auth/callback"))
