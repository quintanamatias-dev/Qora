"""Fail-closed security tests: outbound calls require webhook auth.

Security (HIGH + compounding MEDIUM):
    When ENABLE_OUTBOUND_CALLS=true and QORA_WEBHOOK_AUTH_ENABLED=false,
    the /calls/elevenlabs-postcall endpoint is unauthenticated. Any actor
    who knows the URL can close outbound sessions, corrupt billing counters,
    and inject transcript turns — without placing a real call.

    The Settings model_validator validate_outbound_requires_webhook_auth
    must refuse to construct when this dangerous combination is present,
    aborting startup before any router is registered or request is served.

Scenarios:
    1. outbound=True + webhook_auth=False → ValueError raised (fail-closed)
    2. outbound=True + webhook_auth=True + secret set → Settings constructs (allowed)
    3. outbound=False + webhook_auth=False → Settings constructs (unaffected)
    4. outbound=False + webhook_auth=True + secret set → Settings constructs (unaffected)

No live calls are made. No network I/O. Pure pydantic model construction tests.
"""

from __future__ import annotations

import os

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_ENV = {
    "OPENAI_API_KEY": "sk-test-openai-placeholder-for-unit-tests",
    "ELEVENLABS_API_KEY": "sk-el-test-placeholder-for-unit-tests",
    "QORA_API_KEY": "test-admin-key-for-unit-tests",
}


def _build_settings(extra_env: dict[str, str]):
    """Construct a Settings instance with required secrets patched via env.

    Uses monkeypatching of os.environ so Settings() reads the injected values
    through its standard pydantic-settings env_file / env var resolution path.

    Args:
        extra_env: Additional env vars to inject (e.g. ENABLE_OUTBOUND_CALLS).

    Returns:
        A Settings instance (or raises ValueError on invalid config).
    """
    from app.core.config import Settings

    combined = {**_REQUIRED_ENV, **extra_env}
    # Temporarily patch os.environ so pydantic-settings sees our values.
    original = {k: os.environ.get(k) for k in combined}
    try:
        for k, v in combined.items():
            os.environ[k] = v
        return Settings()
    finally:
        for k, orig_v in original.items():
            if orig_v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = orig_v


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOutboundWebhookAuthFailClosed:
    """Settings construction must fail-closed when outbound+no-webhook-auth."""

    def test_outbound_true_webhook_auth_false_raises(self):
        """GIVEN ENABLE_OUTBOUND_CALLS=true AND QORA_WEBHOOK_AUTH_ENABLED=false
        WHEN Settings() is constructed
        THEN ValueError is raised — startup is aborted.

        This is the core fail-closed guarantee. The app must never start in
        a configuration that leaves webhook endpoints unauthenticated while
        outbound calls are enabled.
        """
        with pytest.raises(ValueError, match="ENABLE_OUTBOUND_CALLS=true requires QORA_WEBHOOK_AUTH_ENABLED=true"):
            _build_settings({
                "ENABLE_OUTBOUND_CALLS": "true",
                "QORA_WEBHOOK_AUTH_ENABLED": "false",
            })

    def test_outbound_true_webhook_auth_true_with_secret_succeeds(self):
        """GIVEN ENABLE_OUTBOUND_CALLS=true AND QORA_WEBHOOK_AUTH_ENABLED=true AND secret set
        WHEN Settings() is constructed
        THEN Settings constructs successfully — this is the secure production config.
        """
        settings = _build_settings({
            "ENABLE_OUTBOUND_CALLS": "true",
            "QORA_WEBHOOK_AUTH_ENABLED": "true",
            "QORA_WEBHOOK_SECRET": "strong-random-secret-for-test-purposes-only",
        })
        assert settings.enable_outbound_calls is True
        assert settings.qora_webhook_auth_enabled is True

    def test_outbound_false_webhook_auth_false_succeeds(self):
        """GIVEN ENABLE_OUTBOUND_CALLS=false AND QORA_WEBHOOK_AUTH_ENABLED=false
        WHEN Settings() is constructed
        THEN Settings constructs successfully — outbound disabled is always safe.

        The fail-closed guard must not affect deployments that have not enabled
        outbound calls (the default/safe configuration).
        """
        settings = _build_settings({
            "ENABLE_OUTBOUND_CALLS": "false",
            "QORA_WEBHOOK_AUTH_ENABLED": "false",
        })
        assert settings.enable_outbound_calls is False
        assert settings.qora_webhook_auth_enabled is False

    def test_outbound_default_false_webhook_auth_false_succeeds(self):
        """GIVEN neither ENABLE_OUTBOUND_CALLS nor QORA_WEBHOOK_AUTH_ENABLED is set
        WHEN Settings() is constructed
        THEN Settings constructs successfully — defaults are safe (both False).

        Verifies that the default configuration (outbound disabled) is unaffected
        by the new validator.
        """
        settings = _build_settings({})
        assert settings.enable_outbound_calls is False
        assert settings.qora_webhook_auth_enabled is False

    def test_outbound_false_webhook_auth_true_with_secret_succeeds(self):
        """GIVEN ENABLE_OUTBOUND_CALLS=false AND QORA_WEBHOOK_AUTH_ENABLED=true AND secret set
        WHEN Settings() is constructed
        THEN Settings constructs successfully — webhook auth can be enabled independently.
        """
        settings = _build_settings({
            "ENABLE_OUTBOUND_CALLS": "false",
            "QORA_WEBHOOK_AUTH_ENABLED": "true",
            "QORA_WEBHOOK_SECRET": "strong-random-secret-for-test-purposes-only",
        })
        assert settings.enable_outbound_calls is False
        assert settings.qora_webhook_auth_enabled is True

    def test_error_message_names_both_variables(self):
        """GIVEN the dangerous combination is present
        WHEN Settings() raises ValueError
        THEN the error message names both ENABLE_OUTBOUND_CALLS and QORA_WEBHOOK_AUTH_ENABLED.

        Operators must be able to identify the exact variables to fix from the
        error message alone — without reading source code.
        """
        with pytest.raises(ValueError) as exc_info:
            _build_settings({
                "ENABLE_OUTBOUND_CALLS": "true",
                "QORA_WEBHOOK_AUTH_ENABLED": "false",
            })

        error_text = str(exc_info.value)
        assert "ENABLE_OUTBOUND_CALLS" in error_text, (
            "Error message must name ENABLE_OUTBOUND_CALLS"
        )
        assert "QORA_WEBHOOK_AUTH_ENABLED" in error_text, (
            "Error message must name QORA_WEBHOOK_AUTH_ENABLED"
        )
        assert "QORA_WEBHOOK_SECRET" in error_text, (
            "Error message must tell the operator to set QORA_WEBHOOK_SECRET"
        )

    def test_outbound_without_webhook_auth_warning_property_still_works(self):
        """GIVEN a safe config (outbound=False)
        WHEN outbound_without_webhook_auth_warning is checked
        THEN it returns False — the property continues to work for observability consumers.

        The property is still used as a derived signal; it must not be broken
        by the new validator.
        """
        settings = _build_settings({
            "ENABLE_OUTBOUND_CALLS": "false",
            "QORA_WEBHOOK_AUTH_ENABLED": "false",
        })
        assert settings.outbound_without_webhook_auth_warning is False

    def test_outbound_enabled_webhook_auth_true_warning_property_false(self):
        """GIVEN outbound=True AND webhook_auth=True
        WHEN outbound_without_webhook_auth_warning is checked
        THEN it returns False — secure config does not trigger the warning property.
        """
        settings = _build_settings({
            "ENABLE_OUTBOUND_CALLS": "true",
            "QORA_WEBHOOK_AUTH_ENABLED": "true",
            "QORA_WEBHOOK_SECRET": "strong-random-secret-for-test-purposes-only",
        })
        assert settings.outbound_without_webhook_auth_warning is False
