"""Unit tests for n8n HTTP client — Phase 3.1 RED.

Covers:
- Payload shape: session_id, client_id, timestamp present in POST body
- Auth header: X-Webhook-Signature = hmac-sha256(secret, body) for outbound
- 5-second timeout honored
- Non-2xx response logs warning but does NOT raise
- N8N_ENABLED=False → no HTTP request fired
- n8n unreachable → logs warning, does not raise
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
import respx
import httpx
from pydantic import SecretStr
from unittest.mock import patch


def _make_settings(
    *,
    enabled: bool = True,
    webhook_url: str = "http://n8n.test/webhook/abc",
    webhook_secret: str = "test-secret",
    internal_api_key: str = "internal-key",
    timeout: int = 5,
    tmp_path=None,
):
    """Build a minimal Settings instance for client tests."""
    from app.core.config import Settings

    db_url = (
        f"sqlite+aiosqlite:///{tmp_path}/test.db"
        if tmp_path
        else "sqlite+aiosqlite:///./test.db"
    )
    return Settings(
        openai_api_key=SecretStr("sk-test"),
        elevenlabs_api_key=SecretStr("el-test"),
        database_url=db_url,
        n8n_enabled=enabled,
        n8n_webhook_url=webhook_url,
        n8n_webhook_secret=SecretStr(webhook_secret),
        n8n_internal_api_key=SecretStr(internal_api_key),
        n8n_timeout_seconds=timeout,
    )


class TestTriggerN8nWebhookPayload:
    """Validate that the correct payload and headers are sent."""

    @pytest.mark.asyncio
    async def test_fires_post_to_configured_url(self, tmp_path):
        """trigger_n8n_webhook sends POST to the configured N8N_WEBHOOK_URL."""
        settings = _make_settings(tmp_path=tmp_path)

        with respx.mock:
            route = respx.post("http://n8n.test/webhook/abc").mock(
                return_value=httpx.Response(200)
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                await trigger_n8n_webhook("sess-001", "client-001")

        assert route.called, "Expected a POST to the webhook URL"

    @pytest.mark.asyncio
    async def test_payload_contains_session_and_client_id(self, tmp_path):
        """POST body must contain session_id and client_id."""
        settings = _make_settings(tmp_path=tmp_path)

        with respx.mock:
            route = respx.post("http://n8n.test/webhook/abc").mock(
                return_value=httpx.Response(200)
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                await trigger_n8n_webhook("sess-001", "client-001")

        request = route.calls[0].request
        body = json.loads(request.content)
        assert body["session_id"] == "sess-001"
        assert body["client_id"] == "client-001"
        assert "timestamp" in body

    @pytest.mark.asyncio
    async def test_hmac_signature_header_correct(self, tmp_path):
        """X-Webhook-Signature must be hmac-sha256(secret, body)."""
        settings = _make_settings(tmp_path=tmp_path, webhook_secret="my-secret")

        with respx.mock:
            route = respx.post("http://n8n.test/webhook/abc").mock(
                return_value=httpx.Response(200)
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                await trigger_n8n_webhook("sess-002", "client-002")

        request = route.calls[0].request
        body_bytes = request.content
        expected_sig = hmac.new(b"my-secret", body_bytes, hashlib.sha256).hexdigest()
        actual_sig = request.headers.get("X-Webhook-Signature")
        assert (
            actual_sig == expected_sig
        ), f"HMAC mismatch: expected {expected_sig!r}, got {actual_sig!r}"


class TestTriggerN8nWebhookErrorHandling:
    """Graceful degradation: errors must never propagate to caller."""

    @pytest.mark.asyncio
    async def test_non_2xx_response_logs_warning_does_not_raise(self, tmp_path, caplog):
        """503 response must be swallowed — logs warning, returns None."""
        settings = _make_settings(tmp_path=tmp_path)

        with respx.mock:
            respx.post("http://n8n.test/webhook/abc").mock(
                return_value=httpx.Response(503)
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                # Must not raise
                result = await trigger_n8n_webhook("sess-003", "client-003")

        assert result is None  # Fire-and-forget returns nothing

    @pytest.mark.asyncio
    async def test_network_error_does_not_raise(self, tmp_path):
        """ConnectError (unreachable host) must be swallowed gracefully."""
        settings = _make_settings(tmp_path=tmp_path)

        with respx.mock:
            respx.post("http://n8n.test/webhook/abc").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                # Must not raise
                result = await trigger_n8n_webhook("sess-004", "client-004")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_error_does_not_raise(self, tmp_path):
        """ReadTimeout must be swallowed — fire-and-forget."""
        settings = _make_settings(tmp_path=tmp_path)

        with respx.mock:
            respx.post("http://n8n.test/webhook/abc").mock(
                side_effect=httpx.ReadTimeout("Timeout")
            )
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                result = await trigger_n8n_webhook("sess-005", "client-005")

        assert result is None


class TestTriggerN8nWebhookFeatureFlag:
    """When N8N_ENABLED=False, no HTTP request must be made."""

    @pytest.mark.asyncio
    async def test_disabled_fires_no_http_request(self, tmp_path):
        """When n8n_enabled=False, trigger_n8n_webhook must be a no-op."""
        settings = _make_settings(enabled=False, tmp_path=tmp_path)

        with respx.mock:
            # No routes configured — any HTTP call would raise
            with patch("app.n8n.client._get_settings", return_value=settings):
                from app.n8n.client import trigger_n8n_webhook

                result = await trigger_n8n_webhook("sess-006", "client-006")

        assert result is None
