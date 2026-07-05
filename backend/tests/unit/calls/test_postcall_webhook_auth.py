"""Unit tests for require_elevenlabs_webhook_signature dependency.

Covers:
- Valid HMAC signature → passes (200 from endpoint)
- Invalid HMAC signature → 401
- Missing ElevenLabs-Signature falls back to X-Webhook-Secret (plain-text)
- Missing all auth headers → 401
- Auth disabled → no-op (passes without any header)
- Misconfigured (auth enabled, no secret) → 401

The ElevenLabs-Signature header format: "v0=<hmac-sha256-hex>,t=<timestamp>"
HMAC is computed over "{timestamp}.{raw_body}" with QORA_WEBHOOK_SECRET as key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compute_signature(secret: str, raw_body: bytes, timestamp: str) -> str:
    """Compute the ElevenLabs HMAC-SHA256 signature string."""
    message = f"{timestamp}.".encode() + raw_body
    digest = hmac.new(secret.encode(), message, digestmod=hashlib.sha256).hexdigest()
    return f"v0={digest},t={timestamp}"


def _make_app(webhook_auth_enabled: bool = True, secret: str | None = "test-webhook-secret"):
    """Build a minimal FastAPI app with the postcall auth dependency on a test route."""
    from app.core.auth import require_elevenlabs_webhook_signature
    from fastapi import Depends

    app = FastAPI()

    from app.core.config import Settings
    from pydantic import SecretStr as _SecretStr

    settings = Settings(
        openai_api_key=_SecretStr("sk-test-openai"),
        elevenlabs_api_key=_SecretStr("el-test-key"),
        qora_api_key=_SecretStr("test-admin-key"),
        qora_webhook_auth_enabled=webhook_auth_enabled,
        qora_webhook_secret=_SecretStr(secret) if secret is not None else None,
    )

    @app.post("/test-postcall", dependencies=[Depends(require_elevenlabs_webhook_signature)])
    async def _endpoint(request: Request):
        body = await request.body()
        return {"ok": True, "body_len": len(body)}

    # Inject settings into app state so the dependency can read them.
    app.state.settings = settings
    return app


# ---------------------------------------------------------------------------
# Tests: auth disabled
# ---------------------------------------------------------------------------


class TestPostcallAuthDisabled:
    """When QORA_WEBHOOK_AUTH_ENABLED=false, all requests pass through."""

    def test_no_headers_passes_when_auth_disabled(self):
        """GIVEN auth disabled
        WHEN POST with no auth header
        THEN 200 — no-op.
        """
        app = _make_app(webhook_auth_enabled=False, secret=None)
        client = TestClient(app)
        response = client.post("/test-postcall", json={"conversation_id": "c-123"})
        assert response.status_code == 200

    def test_any_header_passes_when_auth_disabled(self):
        """GIVEN auth disabled
        WHEN POST with a random header
        THEN 200 — headers are ignored.
        """
        app = _make_app(webhook_auth_enabled=False, secret=None)
        client = TestClient(app)
        response = client.post(
            "/test-postcall",
            json={"conversation_id": "c-123"},
            headers={"ElevenLabs-Signature": "garbage"},
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: valid HMAC signature
# ---------------------------------------------------------------------------


class TestPostcallHmacValid:
    """Valid ElevenLabs-Signature HMAC passes the dependency."""

    def test_valid_hmac_passes(self):
        """GIVEN a correctly computed ElevenLabs-Signature header
        WHEN POST to the endpoint
        THEN 200.
        """
        secret = "test-webhook-secret"
        app = _make_app(webhook_auth_enabled=True, secret=secret)
        client = TestClient(app)

        raw_body = json.dumps({"conversation_id": "conv-abc"}).encode()
        timestamp = str(int(time.time()))
        sig_header = _compute_signature(secret, raw_body, timestamp)

        response = client.post(
            "/test-postcall",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "ElevenLabs-Signature": sig_header,
            },
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_valid_hmac_lowercase_header_name_passes(self):
        """GIVEN the header is sent as 'elevenlabs-signature' (lowercase)
        WHEN POST to the endpoint
        THEN 200 — HTTP headers are case-insensitive.
        """
        secret = "test-webhook-secret"
        app = _make_app(webhook_auth_enabled=True, secret=secret)
        client = TestClient(app)

        raw_body = json.dumps({"conversation_id": "conv-lower"}).encode()
        timestamp = str(int(time.time()))
        sig_header = _compute_signature(secret, raw_body, timestamp)

        response = client.post(
            "/test-postcall",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "elevenlabs-signature": sig_header,
            },
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: invalid HMAC signature
# ---------------------------------------------------------------------------


class TestPostcallHmacInvalid:
    """Invalid or tampered HMAC signature is rejected with 401."""

    def test_wrong_hmac_value_returns_401(self):
        """GIVEN a syntactically valid but wrong HMAC hash
        WHEN POST to the endpoint
        THEN 401.
        """
        app = _make_app(webhook_auth_enabled=True, secret="test-webhook-secret")
        client = TestClient(app)

        timestamp = str(int(time.time()))
        sig_header = f"v0=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,t={timestamp}"

        response = client.post(
            "/test-postcall",
            json={"conversation_id": "conv-bad"},
            headers={"ElevenLabs-Signature": sig_header},
        )
        assert response.status_code == 401

    def test_wrong_secret_returns_401(self):
        """GIVEN the HMAC was signed with a different secret than QORA_WEBHOOK_SECRET
        WHEN POST to the endpoint
        THEN 401.
        """
        app = _make_app(webhook_auth_enabled=True, secret="correct-secret")
        client = TestClient(app)

        raw_body = json.dumps({"conversation_id": "conv-wrongsec"}).encode()
        timestamp = str(int(time.time()))
        # Sign with the wrong secret
        sig_header = _compute_signature("wrong-secret", raw_body, timestamp)

        response = client.post(
            "/test-postcall",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "ElevenLabs-Signature": sig_header,
            },
        )
        assert response.status_code == 401

    def test_tampered_body_returns_401(self):
        """GIVEN the HMAC was computed over the original body but the body was tampered
        WHEN POST to the endpoint
        THEN 401 — HMAC no longer matches.
        """
        secret = "test-webhook-secret"
        app = _make_app(webhook_auth_enabled=True, secret=secret)
        client = TestClient(app)

        original_body = json.dumps({"conversation_id": "conv-original"}).encode()
        timestamp = str(int(time.time()))
        sig_header = _compute_signature(secret, original_body, timestamp)

        # Send a different (tampered) body with the original signature
        tampered_body = json.dumps({"conversation_id": "conv-tampered"}).encode()
        response = client.post(
            "/test-postcall",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                "ElevenLabs-Signature": sig_header,
            },
        )
        assert response.status_code == 401

    def test_malformed_signature_header_returns_401(self):
        """GIVEN a syntactically malformed ElevenLabs-Signature header (no v0= or t=)
        WHEN POST to the endpoint
        THEN 401.
        """
        app = _make_app(webhook_auth_enabled=True, secret="test-webhook-secret")
        client = TestClient(app)

        response = client.post(
            "/test-postcall",
            json={"conversation_id": "conv-malformed"},
            headers={"ElevenLabs-Signature": "not-a-valid-signature"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests: fallback to X-Webhook-Secret when ElevenLabs-Signature absent
# ---------------------------------------------------------------------------


class TestPostcallFallbackToPlainSecret:
    """When ElevenLabs-Signature is absent, fallback to X-Webhook-Secret plain-text."""

    def test_valid_x_webhook_secret_passes_when_no_hmac_header(self):
        """GIVEN no ElevenLabs-Signature header but a correct X-Webhook-Secret
        WHEN POST to the endpoint
        THEN 200 — backward compatibility.
        """
        secret = "test-webhook-secret"
        app = _make_app(webhook_auth_enabled=True, secret=secret)
        client = TestClient(app)

        response = client.post(
            "/test-postcall",
            json={"conversation_id": "conv-fallback"},
            headers={"X-Webhook-Secret": secret},
        )
        assert response.status_code == 200

    def test_wrong_x_webhook_secret_returns_401(self):
        """GIVEN no ElevenLabs-Signature and an incorrect X-Webhook-Secret
        WHEN POST to the endpoint
        THEN 401.
        """
        app = _make_app(webhook_auth_enabled=True, secret="correct-secret")
        client = TestClient(app)

        response = client.post(
            "/test-postcall",
            json={"conversation_id": "conv-wrong-plain"},
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert response.status_code == 401

    def test_missing_all_auth_headers_returns_401(self):
        """GIVEN auth enabled and no auth headers at all
        WHEN POST to the endpoint
        THEN 401.
        """
        app = _make_app(webhook_auth_enabled=True, secret="test-webhook-secret")
        client = TestClient(app)

        response = client.post(
            "/test-postcall",
            json={"conversation_id": "conv-no-auth"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests: misconfigured (auth enabled but no secret)
# ---------------------------------------------------------------------------


class TestPostcallMisconfigured:
    """Auth enabled but QORA_WEBHOOK_SECRET not set → fail-closed."""

    def test_auth_enabled_no_secret_returns_401(self):
        """GIVEN QORA_WEBHOOK_AUTH_ENABLED=true but QORA_WEBHOOK_SECRET not set
        WHEN POST to the endpoint
        THEN 401 — fail-closed.

        We build valid settings then manually patch qora_webhook_secret to None
        to simulate a misconfigured runtime state (the dependency check, not the
        validator) without triggering the startup validator.
        """
        from unittest.mock import MagicMock

        from app.core.auth import require_elevenlabs_webhook_signature
        from fastapi import Depends, FastAPI

        app = FastAPI()

        # Build a minimal mock settings object that mimics the relevant fields
        # without going through the Settings validator (which would refuse
        # webhook_auth_enabled=True + no secret at construction time).
        settings = MagicMock()
        settings.qora_webhook_auth_enabled = True
        settings.qora_webhook_secret = None  # simulates missing secret

        @app.post("/test-misconfigured", dependencies=[Depends(require_elevenlabs_webhook_signature)])
        async def _ep():
            return {"ok": True}

        app.state.settings = settings
        client = TestClient(app)
        response = client.post("/test-misconfigured", json={"x": 1})
        assert response.status_code == 401
        assert "misconfigured" in response.json()["detail"]["error"]
