"""Unit tests for n8n settings — Phase 1.1 RED.

Covers:
- N8N_ENABLED defaults to False
- N8N_ENABLED=True with required URL/secret passes validation
- auth contract is X-Internal-Api-Key (static key), NOT HMAC per-request signing
- 5-second timeout default
- Webhook HMAC signing uses N8N_WEBHOOK_SECRET (outbound)
"""

from __future__ import annotations

from pydantic import SecretStr


class TestN8nSettingsDefaults:
    """Settings are backward-compatible — n8n disabled by default."""

    def test_n8n_enabled_defaults_to_false(self, test_settings):
        """N8N_ENABLED must default to False so existing deploys are unaffected."""
        assert test_settings.n8n_enabled is False

    def test_n8n_webhook_url_defaults_to_empty(self, test_settings):
        """N8N_WEBHOOK_URL must default to empty string."""
        assert test_settings.n8n_webhook_url == ""

    def test_n8n_webhook_secret_defaults_to_empty(self, test_settings):
        """N8N_WEBHOOK_SECRET must default to empty (HMAC signing for outbound)."""
        secret_val = test_settings.n8n_webhook_secret.get_secret_value()
        assert secret_val == ""

    def test_n8n_internal_api_key_defaults_to_empty(self, test_settings):
        """N8N_INTERNAL_API_KEY must default to empty (static key for inbound)."""
        key_val = test_settings.n8n_internal_api_key.get_secret_value()
        assert key_val == ""

    def test_n8n_timeout_defaults_to_five_seconds(self, test_settings):
        """Outbound webhook timeout must default to 5 seconds per spec."""
        assert test_settings.n8n_timeout_seconds == 5


class TestN8nSettingsEnabled:
    """When N8N_ENABLED=True, all required fields must be accessible."""

    def test_n8n_settings_with_all_fields(self, tmp_path):
        """Settings with all n8n fields set should load without error."""
        from app.core.config import Settings

        s = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            n8n_enabled=True,
            n8n_webhook_url="http://n8n.local/webhook/abc",
            n8n_webhook_secret=SecretStr("my-webhook-secret"),
            n8n_internal_api_key=SecretStr("my-internal-key"),
        )
        assert s.n8n_enabled is True
        assert s.n8n_webhook_url == "http://n8n.local/webhook/abc"
        assert s.n8n_webhook_secret.get_secret_value() == "my-webhook-secret"
        assert s.n8n_internal_api_key.get_secret_value() == "my-internal-key"

    def test_n8n_timeout_can_be_overridden(self, tmp_path):
        """n8n_timeout_seconds must be configurable via env."""
        from app.core.config import Settings

        s = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            database_url=f"sqlite+aiosqlite:///{tmp_path}/test.db",
            n8n_timeout_seconds=10,
        )
        assert s.n8n_timeout_seconds == 10


class TestN8nAuthContractChoice:
    """Verify the chosen auth contract: static API key in X-Internal-Api-Key.

    Design decision: static API key (NOT HMAC per-request) for internal API.
    Outbound webhook uses HMAC in X-Webhook-Signature.
    These two secrets are SEPARATE fields.
    """

    def test_internal_api_key_field_exists_as_secret_str(self, test_settings):
        """n8n_internal_api_key must be a SecretStr (never exposed in logs)."""
        assert isinstance(test_settings.n8n_internal_api_key, SecretStr)

    def test_webhook_secret_field_exists_as_secret_str(self, test_settings):
        """n8n_webhook_secret (for HMAC signing outbound) must be SecretStr."""
        assert isinstance(test_settings.n8n_webhook_secret, SecretStr)

    def test_internal_api_key_and_webhook_secret_are_separate_fields(
        self, test_settings
    ):
        """The two auth secrets must be distinct — not a single shared field."""
        # Both exist independently — confirms the two-secret design
        assert hasattr(test_settings, "n8n_internal_api_key")
        assert hasattr(test_settings, "n8n_webhook_secret")
        # They are separate SecretStr instances
        assert (
            test_settings.n8n_internal_api_key is not test_settings.n8n_webhook_secret
        )
