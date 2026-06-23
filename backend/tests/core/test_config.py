"""Tests for Phase B8 — Secrets Management: Settings startup validation.

TDD RED phase (task 1.1): These tests define the expected behavior for the
startup model_validator that must be added to Settings in task 1.2 (GREEN).

Spec reference: openspec/changes/phase-b-secrets-management/specs/secrets-validation/spec.md

Covered scenarios:
- Critical Secret Fail-Fast: OPENAI_API_KEY missing → ValueError
- Critical Secret Fail-Fast: ELEVENLABS_API_KEY missing → ValueError
- Platform API Key Required: QORA_API_KEY missing → ValueError (all envs)
- Placeholder Value Rejection: CRITICAL secret set to known placeholder → ValueError
- Placeholder Value Rejection: HIGH secret (QORA_API_KEY) set to placeholder → ValueError
- Valid secrets accepted without error
- Conditional webhook secret validation (already in B5; confirmed still works)
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**kwargs):
    """Instantiate Settings with the minimum required fields plus overrides.

    Provides real non-placeholder defaults for all REQUIRED fields so individual
    test cases can selectively omit or override one field to exercise validation.
    """
    from app.core.config import Settings

    defaults = dict(
        openai_api_key=SecretStr("sk-real-openai-key"),
        elevenlabs_api_key=SecretStr("el-real-key"),
        qora_api_key=SecretStr("qora-real-admin-key"),
    )
    defaults.update(kwargs)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# Task 1.1 — RED: Critical secret fail-fast
# ---------------------------------------------------------------------------


class TestCriticalSecretValidation:
    """Settings must hard-fail at construction when CRITICAL secrets are absent."""

    def test_valid_critical_secrets_allow_startup(self):
        """All CRITICAL secrets present → Settings constructs without error."""
        settings = _make_settings()
        # Assert specific fields, not just existence
        assert settings.openai_api_key.get_secret_value() == "sk-real-openai-key"
        assert settings.elevenlabs_api_key.get_secret_value() == "el-real-key"

    def test_missing_openai_api_key_raises_value_error(self):
        """OPENAI_API_KEY absent → startup aborts with error naming the variable."""
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            from app.core.config import Settings
            Settings(
                openai_api_key=None,  # type: ignore[arg-type]
                elevenlabs_api_key=SecretStr("el-real-key"),
                qora_api_key=SecretStr("qora-real-admin-key"),
            )
        error_text = str(exc_info.value).upper()
        assert "OPENAI_API_KEY" in error_text or "OPENAI" in error_text

    def test_missing_elevenlabs_api_key_raises_value_error(self):
        """ELEVENLABS_API_KEY absent → startup aborts with error naming the variable."""
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            from app.core.config import Settings
            Settings(
                openai_api_key=SecretStr("sk-real-openai-key"),
                elevenlabs_api_key=None,  # type: ignore[arg-type]
                qora_api_key=SecretStr("qora-real-admin-key"),
            )
        error_text = str(exc_info.value).upper()
        assert "ELEVENLABS_API_KEY" in error_text or "ELEVENLABS" in error_text

    def test_empty_openai_api_key_raises_value_error(self, monkeypatch):
        """OPENAI_API_KEY empty string → treated as missing → startup aborts."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(openai_api_key=SecretStr(""))

    def test_empty_elevenlabs_api_key_raises_value_error(self, monkeypatch):
        """ELEVENLABS_API_KEY empty string → treated as missing → startup aborts."""
        monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(elevenlabs_api_key=SecretStr(""))


# ---------------------------------------------------------------------------
# Task 1.1 — RED: Platform API key required in all environments
# ---------------------------------------------------------------------------


class TestPlatformApiKeyRequired:
    """QORA_API_KEY must be required with hard fail in all environments."""

    def test_qora_api_key_set_allows_startup(self):
        """QORA_API_KEY set to any non-empty non-placeholder value → startup succeeds."""
        settings = _make_settings(qora_api_key=SecretStr("local-dev-key"))
        assert settings.qora_api_key is not None
        assert settings.qora_api_key.get_secret_value() == "local-dev-key"

    def test_missing_qora_api_key_raises_value_error(self):
        """QORA_API_KEY absent → startup aborts with error naming the variable."""
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            from app.core.config import Settings
            Settings(
                openai_api_key=SecretStr("sk-real-openai-key"),
                elevenlabs_api_key=SecretStr("el-real-key"),
                qora_api_key=None,  # type: ignore[arg-type]
            )
        error_text = str(exc_info.value).upper()
        assert "QORA_API_KEY" in error_text

    def test_empty_qora_api_key_raises_value_error(self):
        """QORA_API_KEY set to empty string → treated as missing → startup aborts."""
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(qora_api_key=SecretStr(""))


# ---------------------------------------------------------------------------
# Task 1.1 — RED: Placeholder value rejection for CRITICAL and HIGH secrets
# ---------------------------------------------------------------------------


class TestPlaceholderRejection:
    """Known weak placeholder values must be rejected for CRITICAL and HIGH secrets."""

    @pytest.mark.parametrize("placeholder", [
        "change-me-before-production",
        "your-key-here",
        "TODO",
        "REPLACE_ME",
        "xxx",
        "test",
        "changeme",
    ])
    def test_placeholder_in_openai_api_key_raises(self, placeholder):
        """Any known placeholder in OPENAI_API_KEY → startup aborts."""
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            _make_settings(openai_api_key=SecretStr(placeholder))
        error_text = str(exc_info.value).upper()
        # Must name the variable
        assert "OPENAI_API_KEY" in error_text or "PLACEHOLDER" in error_text or "WEAK" in error_text

    @pytest.mark.parametrize("placeholder", [
        "change-me-before-production",
        "your-key-here",
        "TODO",
        "REPLACE_ME",
        "xxx",
        "changeme",
    ])
    def test_placeholder_in_elevenlabs_api_key_raises(self, placeholder):
        """Any known placeholder in ELEVENLABS_API_KEY → startup aborts."""
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(elevenlabs_api_key=SecretStr(placeholder))

    @pytest.mark.parametrize("placeholder", [
        "change-me-before-production",
        "your-key-here",
        "TODO",
        "REPLACE_ME",
        "changeme",
    ])
    def test_placeholder_in_qora_api_key_raises(self, placeholder):
        """Any known placeholder in QORA_API_KEY → startup aborts."""
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(qora_api_key=SecretStr(placeholder))

    def test_real_value_not_rejected_as_placeholder(self):
        """A non-placeholder value must not be rejected based on content."""
        settings = _make_settings(
            openai_api_key=SecretStr("sk-proj-abcdefghijklmnop"),
            elevenlabs_api_key=SecretStr("el-prod-key-abc123"),
            qora_api_key=SecretStr("qora-admin-strong-key"),
        )
        assert settings.openai_api_key.get_secret_value() == "sk-proj-abcdefghijklmnop"

    def test_local_dev_non_placeholder_accepted_for_qora_api_key(self):
        """Simple local placeholder-like strings that are NOT in the list are accepted."""
        # "local-dev-key" is not a known placeholder — must be accepted
        settings = _make_settings(qora_api_key=SecretStr("local-dev-key"))
        assert settings.qora_api_key is not None


# ---------------------------------------------------------------------------
# Task 1.1 — RED: Webhook secret remains conditional (B5 behaviour preserved)
# ---------------------------------------------------------------------------


class TestConditionalWebhookSecret:
    """Webhook secret validation is conditional on QORA_WEBHOOK_AUTH_ENABLED."""

    def test_webhook_auth_disabled_missing_secret_ok(self):
        """When webhook auth is disabled, missing webhook secret does not abort startup."""
        settings = _make_settings(
            qora_webhook_auth_enabled=False,
            qora_webhook_secret=None,
        )
        assert settings.qora_webhook_auth_enabled is False
        assert settings.qora_webhook_secret is None

    def test_webhook_auth_enabled_missing_secret_raises(self):
        """When webhook auth is enabled, missing webhook secret aborts startup."""
        with pytest.raises((ValueError, ValidationError)):
            _make_settings(
                qora_webhook_auth_enabled=True,
                qora_webhook_secret=None,
            )
