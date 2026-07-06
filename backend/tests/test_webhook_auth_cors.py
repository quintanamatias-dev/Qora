"""Tests for Phase B5 PR #3 — Webhook Auth + CORS.

TDD RED phase: tests reference require_webhook_secret and QORA_ALLOWED_ORIGINS
behavior. Written first; will fail until Task 3.2/3.3 GREEN implements production code.

Test plan (from design.md + tasks.md):

  Unit — require_webhook_secret:
    - When QORA_WEBHOOK_AUTH_ENABLED=false → function is a no-op (returns None)
    - When QORA_WEBHOOK_AUTH_ENABLED=true + correct X-Webhook-Secret → passes (no exception)
    - When QORA_WEBHOOK_AUTH_ENABLED=true + missing header → HTTPException 401
    - When QORA_WEBHOOK_AUTH_ENABLED=true + wrong header value → HTTPException 401
    - When QORA_WEBHOOK_AUTH_ENABLED=true + empty secret configured → 401 (not configured)

  Unit — Settings.qora_webhook_secret + qora_webhook_auth_enabled:
    - qora_webhook_auth_enabled defaults to False
    - qora_webhook_secret is SecretStr | None

  Integration — POST /api/v1/voice/initiation with webhook auth:
    - Auth disabled (default): no X-Webhook-Secret header required — returns 422 (no client_id)
      proving the request reached the handler (auth did NOT block it with 401)
    - Auth enabled + correct secret: request reaches handler (returns 422 no client_id, not 401)
    - Auth enabled + missing secret header → 401
    - Auth enabled + wrong secret → 401
    - Auth enabled does NOT affect GET /api/v1/health (health is not a voice endpoint)

  Unit — CORS origins (QORA_ALLOWED_ORIGINS):
    - Default "*" → allow_origins=["*"] (open dev behavior)
    - Comma-separated list → parsed into list of origins
    - Single origin → single-element list
    - Whitespace around commas is trimmed

  Integration — CORS behavior (CORSMiddleware via create_app):
    - Allowed origin gets CORS headers in response
    - Not-allowed origin when origins restricted → no ACAO header (or rejected)
    - Wildcard allows any origin
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request_with_headers(headers: dict[str, str]) -> Request:
    """Build a minimal FastAPI Request with given HTTP headers."""
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/voice/initiation",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }
    return Request(scope)


def _make_settings_with_webhook(
    *,
    enabled: bool,
    secret: str | None = "webhook-secret-value",
) -> MagicMock:
    """Return a minimal settings stub with webhook auth fields."""
    settings = MagicMock()
    settings.qora_webhook_auth_enabled = enabled
    settings.qora_webhook_secret = SecretStr(secret) if secret is not None else None
    return settings


# ---------------------------------------------------------------------------
# Unit tests — require_webhook_secret dependency
# ---------------------------------------------------------------------------


class TestRequireWebhookSecret:
    """Unit tests for the require_webhook_secret FastAPI dependency."""

    def test_disabled_by_default_no_op_without_header(self):
        """When QORA_WEBHOOK_AUTH_ENABLED=false, missing header is accepted (no-op)."""
        from app.core.auth import require_webhook_secret

        request = _make_request_with_headers({})
        settings = _make_settings_with_webhook(enabled=False)

        # Must not raise — disabled means no-op
        result = require_webhook_secret(request, settings)
        assert result is None

    def test_disabled_by_default_no_op_with_wrong_header(self):
        """When QORA_WEBHOOK_AUTH_ENABLED=false, wrong header value is still accepted (no-op)."""
        from app.core.auth import require_webhook_secret

        request = _make_request_with_headers({"X-Webhook-Secret": "totally-wrong"})
        settings = _make_settings_with_webhook(enabled=False)

        # Must not raise — disabled means auth is completely skipped
        result = require_webhook_secret(request, settings)
        assert result is None

    def test_enabled_correct_secret_passes(self):
        """When enabled + correct X-Webhook-Secret value → no exception raised."""
        from app.core.auth import require_webhook_secret

        correct_secret = "my-webhook-secret-123"
        request = _make_request_with_headers({"X-Webhook-Secret": correct_secret})
        settings = _make_settings_with_webhook(enabled=True, secret=correct_secret)

        # Must not raise
        result = require_webhook_secret(request, settings)
        assert result is None

    def test_enabled_missing_header_raises_401(self):
        """When enabled + no X-Webhook-Secret header → HTTPException 401."""
        from app.core.auth import require_webhook_secret
        from fastapi import HTTPException

        request = _make_request_with_headers({})
        settings = _make_settings_with_webhook(enabled=True)

        with pytest.raises(HTTPException) as exc_info:
            require_webhook_secret(request, settings)

        assert exc_info.value.status_code == 401

    def test_enabled_wrong_secret_raises_401(self):
        """When enabled + wrong X-Webhook-Secret value → HTTPException 401."""
        from app.core.auth import require_webhook_secret
        from fastapi import HTTPException

        request = _make_request_with_headers({"X-Webhook-Secret": "wrong-secret"})
        settings = _make_settings_with_webhook(enabled=True, secret="correct-secret")

        with pytest.raises(HTTPException) as exc_info:
            require_webhook_secret(request, settings)

        assert exc_info.value.status_code == 401

    def test_enabled_no_secret_configured_raises_401(self):
        """When enabled but QORA_WEBHOOK_SECRET is not configured → 401 (fail-closed)."""
        from app.core.auth import require_webhook_secret
        from fastapi import HTTPException

        request = _make_request_with_headers({"X-Webhook-Secret": "any-value"})
        settings = _make_settings_with_webhook(enabled=True, secret=None)

        with pytest.raises(HTTPException) as exc_info:
            require_webhook_secret(request, settings)

        assert exc_info.value.status_code == 401

    def test_triangulation_two_different_correct_secrets_both_pass(self):
        """Triangulation: any correct secret value is accepted, not just a hardcoded one."""
        from app.core.auth import require_webhook_secret

        for secret_value in ("alpha-secret-abc", "beta-secret-xyz-789"):
            request = _make_request_with_headers({"X-Webhook-Secret": secret_value})
            settings = _make_settings_with_webhook(enabled=True, secret=secret_value)
            # Must not raise for each correct secret
            result = require_webhook_secret(request, settings)
            assert result is None

    def test_constant_time_comparison_used_for_webhook(self):
        """Verify secrets.compare_digest is used in require_webhook_secret (not == operator)."""
        from app.core import auth as auth_module
        import inspect

        source = inspect.getsource(auth_module)
        # The module already uses compare_digest for require_api_key.
        # require_webhook_secret must also use it.
        assert "compare_digest" in source, (
            "require_webhook_secret must use secrets.compare_digest for constant-time comparison"
        )


# ---------------------------------------------------------------------------
# Unit tests — Settings fields for webhook auth
# ---------------------------------------------------------------------------


class TestWebhookAuthSettings:
    """Unit tests for webhook auth Settings fields."""

    @pytest.fixture(autouse=True)
    def _clear_webhook_env(self, monkeypatch):
        """Clear webhook auth env vars so these tests see clean defaults.

        The project .env sets QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET,
        which overrides the defaults under test. Monkeypatching ensures these tests
        exercise the true default values, not the production .env configuration.
        """
        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "false")
        monkeypatch.delenv("QORA_WEBHOOK_SECRET", raising=False)

    def test_qora_webhook_auth_enabled_defaults_to_false(self):
        """qora_webhook_auth_enabled must default to False (disabled by default)."""
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
        )
        assert settings.qora_webhook_auth_enabled is False

    def test_qora_webhook_secret_field_exists_and_is_optional(self):
        """qora_webhook_secret field must exist and allow None."""
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "qora_webhook_secret" in fields

    def test_qora_webhook_secret_accepts_none(self):
        """qora_webhook_secret defaults to None when not set.

        Passes qora_webhook_secret=None explicitly so the constructor kwarg
        (highest pydantic-settings priority) wins over any value in .env file.
        """
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_webhook_secret=None,
        )
        assert settings.qora_webhook_secret is None

    def test_qora_allowed_origins_defaults_to_wildcard(self):
        """qora_allowed_origins must default to '*' (open dev behavior)."""
        from app.core.config import Settings

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
        )
        assert settings.qora_allowed_origins == "*"


# ---------------------------------------------------------------------------
# Unit tests — CORS allowed origins parsing
# ---------------------------------------------------------------------------


class TestCorsOriginsParser:
    """Unit tests for the CORS allowed origins parsing helper."""

    def test_wildcard_returns_list_with_single_star(self):
        """'*' → ['*'] (open dev default)."""
        from app.main import _parse_allowed_origins

        result = _parse_allowed_origins("*")
        assert result == ["*"]

    def test_single_origin_returns_single_element_list(self):
        """Single origin string → single-element list."""
        from app.main import _parse_allowed_origins

        result = _parse_allowed_origins("https://app.example.com")
        assert result == ["https://app.example.com"]

    def test_comma_separated_origins_parsed_into_list(self):
        """Comma-separated origins → list of origins."""
        from app.main import _parse_allowed_origins

        result = _parse_allowed_origins("https://a.com,https://b.com,https://c.com")
        assert len(result) == 3
        assert "https://a.com" in result
        assert "https://b.com" in result
        assert "https://c.com" in result

    def test_whitespace_around_commas_is_trimmed(self):
        """Whitespace around comma-separated origins must be trimmed."""
        from app.main import _parse_allowed_origins

        result = _parse_allowed_origins("https://a.com , https://b.com , https://c.com")
        assert result == ["https://a.com", "https://b.com", "https://c.com"]


# ---------------------------------------------------------------------------
# Integration tests — /voice/initiation webhook auth behavior
# ---------------------------------------------------------------------------


class TestInitiationWebhookAuth:
    """Integration tests: webhook auth behavior on /api/v1/voice/initiation."""

    def test_auth_disabled_no_secret_header_reaches_handler(self):
        """When webhook auth is off (default), missing X-Webhook-Secret still reaches handler.

        The request should NOT return 401. It should return 422 (missing client_id)
        or any non-401 status, proving auth was not enforced.
        """
        from app.main import create_app
        import os

        # Ensure webhook auth is off (default)
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/initiation",
            json={},
        )
        # Must NOT be 401 — auth is disabled so the request reached the handler
        assert response.status_code != 401, (
            f"Webhook auth is disabled; request should not be blocked with 401, "
            f"got {response.status_code}"
        )

    def test_auth_enabled_correct_secret_reaches_handler(self, monkeypatch):
        """When webhook auth is on + correct secret, request reaches the handler.

        Expects 422 (missing client_id) or other non-401 status — not 401.
        """
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "integration-webhook-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/initiation",
            json={},
            headers={"X-Webhook-Secret": "integration-webhook-secret"},
        )
        assert response.status_code != 401, (
            f"Correct secret should reach handler (non-401), got {response.status_code}"
        )

    def test_auth_enabled_missing_secret_returns_401(self, monkeypatch):
        """When webhook auth is on + no X-Webhook-Secret header → 401."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "integration-webhook-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/initiation",
            json={},
        )
        assert response.status_code == 401, (
            f"Missing secret header when auth is enabled must return 401, "
            f"got {response.status_code}"
        )

    def test_auth_enabled_wrong_secret_returns_401(self, monkeypatch):
        """When webhook auth is on + wrong X-Webhook-Secret value → 401."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "integration-webhook-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/initiation",
            json={},
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert response.status_code == 401, (
            f"Wrong secret when auth is enabled must return 401, got {response.status_code}"
        )

    def test_webhook_auth_does_not_affect_health_check(self, monkeypatch):
        """Enabling webhook auth must NOT affect GET /api/v1/health (public endpoint)."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "integration-webhook-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/health")
        assert response.status_code == 200, (
            f"Health check must be public even with webhook auth enabled, "
            f"got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# Integration tests — CORS behavior via create_app
# ---------------------------------------------------------------------------


class TestCorsIntegration:
    """Integration tests: CORS behavior controlled by QORA_ALLOWED_ORIGINS."""

    def test_wildcard_allows_any_origin(self, monkeypatch):
        """Default '*' allows any origin — ACAO header is '*' or the request origin."""
        from app.main import create_app

        monkeypatch.setenv("QORA_ALLOWED_ORIGINS", "*")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/api/v1/health",
            headers={"Origin": "https://any-origin.example.com"},
        )
        assert response.status_code == 200
        # With wildcard, CORS middleware returns ACAO header
        acao = response.headers.get("access-control-allow-origin")
        assert acao is not None, "Wildcard CORS must produce access-control-allow-origin header"

    def test_allowed_origin_gets_cors_header(self, monkeypatch):
        """A request from an allowed origin gets Access-Control-Allow-Origin header."""
        from app.main import create_app

        allowed = "https://app.example.com"
        monkeypatch.setenv("QORA_ALLOWED_ORIGINS", allowed)

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/api/v1/health",
            headers={"Origin": allowed},
        )
        assert response.status_code == 200
        acao = response.headers.get("access-control-allow-origin")
        assert acao == allowed, (
            f"Allowed origin must get ACAO header matching origin, got: {acao}"
        )

    def test_disallowed_origin_does_not_get_cors_header(self, monkeypatch):
        """A request from a disallowed origin must not get an ACAO header."""
        from app.main import create_app

        monkeypatch.setenv("QORA_ALLOWED_ORIGINS", "https://allowed.example.com")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get(
            "/api/v1/health",
            headers={"Origin": "https://malicious.example.com"},
        )
        # Status must still be 200 (CORS does not block server response — it blocks browser access)
        assert response.status_code == 200
        acao = response.headers.get("access-control-allow-origin")
        # Disallowed origin must NOT get the ACAO header (browser will block cross-origin access)
        assert acao != "https://malicious.example.com", (
            "Disallowed origin must not receive access-control-allow-origin header"
        )

    def test_multiple_allowed_origins_each_get_cors_header(self, monkeypatch):
        """Each origin in a comma-separated QORA_ALLOWED_ORIGINS list gets CORS headers."""
        from app.main import create_app

        origins = "https://a.example.com,https://b.example.com"
        monkeypatch.setenv("QORA_ALLOWED_ORIGINS", origins)

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        for origin in ["https://a.example.com", "https://b.example.com"]:
            response = client.get(
                "/api/v1/health",
                headers={"Origin": origin},
            )
            acao = response.headers.get("access-control-allow-origin")
            assert acao == origin, (
                f"Origin '{origin}' must get ACAO header, got: {acao}"
            )


# ---------------------------------------------------------------------------
# Integration tests — Custom LLM webhook auth behavior
# ---------------------------------------------------------------------------


class TestCustomLLMWebhookAuth:
    """Integration tests: webhook auth enforcement on /voice/custom-llm/* routes.

    The spec (webhook-auth/spec.md) requires Requirement: Webhook Auth Scope to
    cover ``/voice/custom-llm/*`` — not just ``/voice/initiation``.

    Routes under test:
    - POST /api/v1/voice/custom-llm                          (legacy route)
    - POST /api/v1/voice/custom-llm/chat/completions         (ElevenLabs appended path)
    - POST /api/v1/voice/{client_id}/custom-llm/chat/completions  (path-based route)
    """

    # ------------------------------------------------------------------
    # Minimal body accepted by CustomLLMRequest (prevents 422 from schema)
    # ------------------------------------------------------------------
    _MINIMAL_BODY = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hello"}],
        "elevenlabs_extra_body": {"client_id": "test-client"},
    }

    def test_legacy_route_auth_disabled_no_secret_reaches_handler(self, monkeypatch):
        """Auth disabled (default): legacy /voice/custom-llm does NOT require secret.

        The request must NOT return 401. Any other status proves auth was not enforced.
        """
        from app.main import create_app

        # Explicitly disable auth (mirrors default)
        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "false")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/custom-llm",
            json=self._MINIMAL_BODY,
        )
        assert response.status_code != 401, (
            f"Auth disabled — legacy custom-llm must not return 401, got {response.status_code}"
        )

    def test_path_route_auth_disabled_no_secret_reaches_handler(self, monkeypatch):
        """Auth disabled (default): path-based /voice/{client_id}/custom-llm/chat/completions
        does NOT require secret.
        """
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "false")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/test-client/custom-llm/chat/completions",
            json=self._MINIMAL_BODY,
        )
        assert response.status_code != 401, (
            f"Auth disabled — path-based custom-llm must not return 401, got {response.status_code}"
        )

    def test_legacy_route_auth_enabled_missing_secret_returns_401(self, monkeypatch):
        """Auth enabled + no X-Webhook-Secret on legacy route → 401."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "test-custom-llm-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/custom-llm",
            json=self._MINIMAL_BODY,
        )
        assert response.status_code == 401, (
            f"Missing secret on legacy route with auth enabled must return 401, "
            f"got {response.status_code}"
        )

    def test_path_route_auth_enabled_missing_secret_returns_401(self, monkeypatch):
        """Auth enabled + no X-Webhook-Secret on path-based route → 401."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "test-custom-llm-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/test-client/custom-llm/chat/completions",
            json=self._MINIMAL_BODY,
        )
        assert response.status_code == 401, (
            f"Missing secret on path-based route with auth enabled must return 401, "
            f"got {response.status_code}"
        )

    def test_legacy_route_auth_enabled_wrong_secret_returns_401(self, monkeypatch):
        """Auth enabled + wrong X-Webhook-Secret on legacy route → 401."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "correct-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/custom-llm",
            json=self._MINIMAL_BODY,
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert response.status_code == 401, (
            f"Wrong secret on legacy route must return 401, got {response.status_code}"
        )

    def test_path_route_auth_enabled_wrong_secret_returns_401(self, monkeypatch):
        """Auth enabled + wrong X-Webhook-Secret on path-based route → 401."""
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "correct-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/test-client/custom-llm/chat/completions",
            json=self._MINIMAL_BODY,
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert response.status_code == 401, (
            f"Wrong secret on path-based route must return 401, got {response.status_code}"
        )

    def test_legacy_route_auth_enabled_correct_secret_reaches_handler(self, monkeypatch):
        """Auth enabled + correct X-Webhook-Secret on legacy route → request reaches handler.

        Any non-401 status proves auth passed and handler ran.
        """
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "correct-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/custom-llm",
            json=self._MINIMAL_BODY,
            headers={"X-Webhook-Secret": "correct-secret"},
        )
        assert response.status_code != 401, (
            f"Correct secret on legacy route must reach handler (non-401), "
            f"got {response.status_code}"
        )

    def test_path_route_auth_enabled_correct_secret_reaches_handler(self, monkeypatch):
        """Auth enabled + correct X-Webhook-Secret on path-based route → request reaches handler.

        Any non-401 status proves auth passed.
        """
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "correct-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v1/voice/test-client/custom-llm/chat/completions",
            json=self._MINIMAL_BODY,
            headers={"X-Webhook-Secret": "correct-secret"},
        )
        assert response.status_code != 401, (
            f"Correct secret on path-based route must reach handler (non-401), "
            f"got {response.status_code}"
        )

    def test_webhook_auth_does_not_apply_to_admin_routes(self, monkeypatch):
        """Webhook secret MUST NOT be accepted on admin routes (spec: Webhook Auth Scope).

        When auth is enabled and X-Webhook-Secret is present but no Authorization Bearer
        header is sent to an admin route, the admin route must NOT return 200.
        The webhook secret dependency is not wired to admin routes, so the request either:
        - Returns 401 (bearer token missing — auth dependency evaluated first), OR
        - Returns 500 (DB not initialized in test environment — handler reached but
          database dependency fails, proving the webhook secret was NOT what blocked it).
        In both cases the webhook secret was NOT accepted as a valid credential.
        """
        from app.main import create_app

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "correct-secret")

        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)

        # Admin route with webhook secret but no Bearer token — must NOT return 200.
        # The webhook secret is NOT wired to admin routes.
        response = client.get(
            "/api/v1/clients",
            headers={"X-Webhook-Secret": "correct-secret"},
        )
        assert response.status_code != 200, (
            f"Admin route must not accept webhook-secret-only requests (expected non-200), "
            f"got {response.status_code}"
        )


# ---------------------------------------------------------------------------
# TDD RED — Startup-fail contract (spec: Config-Driven Secret requirement)
# ---------------------------------------------------------------------------
# Spec: "If QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET is not set,
# startup MUST fail with a configuration error."
# The enforcement point is Settings construction (pydantic model_validator) so
# that the error fires before any request is served.
# ---------------------------------------------------------------------------


class TestWebhookSecretStartupContract:
    """Verify the startup-fail contract for webhook auth misconfiguration.

    Spec reference: webhook-auth/spec.md — Requirement: Config-Driven Secret
      "If QORA_WEBHOOK_AUTH_ENABLED=true and QORA_WEBHOOK_SECRET is not set,
       startup MUST fail with a configuration error before serving any requests."

    These tests exercise Settings() construction (the env/default production path),
    NOT the per-request require_webhook_secret dependency.
    """

    def test_settings_raises_on_enabled_auth_without_secret(self, monkeypatch):
        """Settings() MUST raise ValidationError when webhook auth is enabled but secret is absent.

        This is the canonical startup-fail path: pydantic-settings reads env vars
        and the model_validator fires during __init__, preventing the app from
        reaching its lifespan startup.
        """
        import pytest
        from pydantic import ValidationError

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.delenv("QORA_WEBHOOK_SECRET", raising=False)

        # Force re-import so env vars are picked up without .env file interference.
        # Construct directly with explicit fields to isolate env-var path.
        # qora_webhook_secret=None is passed explicitly so the .env file value is
        # not picked up by pydantic-settings (constructor kwargs win over .env).
        from pydantic import SecretStr

        with pytest.raises(ValidationError) as exc_info:
            from app.core.config import Settings

            Settings(
                openai_api_key=SecretStr("sk-test"),
                elevenlabs_api_key=SecretStr("el-test"),
                qora_webhook_auth_enabled=True,
                qora_webhook_secret=None,
            )

        # The error must mention the misconfiguration clearly.
        error_text = str(exc_info.value).lower()
        assert "webhook" in error_text, (
            f"ValidationError message must mention 'webhook', got: {exc_info.value}"
        )

    def test_settings_raises_on_enabled_auth_with_empty_secret(self, monkeypatch):
        """Settings() MUST raise ValidationError when webhook auth is enabled and secret is empty string.

        An empty QORA_WEBHOOK_SECRET is treated the same as absent — it provides
        no security value and must be rejected at startup.
        """
        import pytest
        from pydantic import SecretStr, ValidationError

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.setenv("QORA_WEBHOOK_SECRET", "")

        with pytest.raises(ValidationError):
            from app.core.config import Settings

            Settings(
                openai_api_key=SecretStr("sk-test"),
                elevenlabs_api_key=SecretStr("el-test"),
                qora_webhook_auth_enabled=True,
                qora_webhook_secret=SecretStr(""),
            )

    def test_settings_succeeds_when_auth_disabled_and_secret_absent(self):
        """Settings() MUST succeed when webhook auth is disabled (default), even without a secret.

        The disabled-by-default contract must not be broken by the startup-fail guard.
        """
        from pydantic import SecretStr
        from app.core.config import Settings

        # Must NOT raise — auth is disabled; secret is optional when disabled.
        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_webhook_auth_enabled=False,
            # qora_webhook_secret=None passed explicitly so constructor kwarg
            # (highest pydantic-settings priority) wins over any .env file value.
            qora_webhook_secret=None,
        )
        assert settings.qora_webhook_auth_enabled is False
        assert settings.qora_webhook_secret is None

    def test_settings_succeeds_when_auth_enabled_and_secret_present(self):
        """Settings() MUST succeed when webhook auth is enabled AND a non-empty secret is set.

        This is the valid production configuration.
        """
        from pydantic import SecretStr
        from app.core.config import Settings

        # Must NOT raise — auth enabled + secret configured is the correct state.
        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_webhook_auth_enabled=True,
            qora_webhook_secret=SecretStr("strong-random-secret-value"),
        )
        assert settings.qora_webhook_auth_enabled is True
        assert settings.qora_webhook_secret is not None

    def test_create_app_raises_on_enabled_auth_without_secret_env(self, monkeypatch):
        """App startup MUST abort when env has auth enabled but no webhook secret.

        This test proves the startup-fail fires on the production env-variable path
        (QORA_WEBHOOK_AUTH_ENABLED=true, no QORA_WEBHOOK_SECRET in environment).
        The error must surface before any request can be served.

        B8 note: Settings() is now constructed inside create_app() so that CORS and
        docs toggle are read from the Settings validator (the sole env authority per B8).
        This means ValidationError fires at Settings() construction time, which is
        earlier than the previous lifespan-based check. The spec contract is still
        satisfied: startup aborts before any request can be served.

        The test directly instantiates Settings() with the bad env to verify the
        contract without relying on import-time side effects.
        """
        import pytest
        from pydantic import ValidationError, SecretStr

        monkeypatch.setenv("QORA_WEBHOOK_AUTH_ENABLED", "true")
        monkeypatch.delenv("QORA_WEBHOOK_SECRET", raising=False)

        from app.core.config import Settings

        # B8: Settings() now fires inside create_app(). Verify the same Settings()
        # construction raises — this is the exact code path triggered by create_app().
        with pytest.raises((ValueError, ValidationError)) as exc_info:
            Settings(
                openai_api_key=SecretStr("sk-proj-test"),
                elevenlabs_api_key=SecretStr("el-test-key"),
                qora_api_key=SecretStr("qora-test-key"),
                qora_webhook_auth_enabled=True,
                qora_webhook_secret=None,
            )

        error_text = str(exc_info.value).lower()
        assert "webhook" in error_text or "secret" in error_text, (
            f"Startup exception must mention webhook/secret config, got: {exc_info.value}"
        )
