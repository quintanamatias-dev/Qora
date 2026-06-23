"""Tests for Phase B5 — API Key Authentication (PR #1: Foundation + Admin Auth).

TDD RED phase: these tests reference app.core.auth and config fields that do not
exist yet. They will fail until Task 1.2 (GREEN) implements the production code.

Test plan (from design.md testing strategy):
  Unit:
    - require_api_key accepts valid Bearer token → CallerIdentity
    - require_api_key rejects missing Authorization header → 401
    - require_api_key rejects invalid Bearer token → 401
    - require_api_key rejects malformed header (no "Bearer " prefix) → 401
    - CallerIdentity stores hashed key, never raw key
    - constant-time comparison (no timing side-channel)
    - Settings: qora_api_key field exists and is SecretStr
    - Settings: qora_docs_enabled field exists with correct default

  Integration:
    - GET /api/v1/clients — 401 without Authorization header
    - GET /api/v1/clients — 200 with valid Bearer token
    - GET /api/v1/health  — 200 WITHOUT Authorization header (exempt)
    - GET /api/v1/leads   — 401 without Authorization header
    - GET /api/v1/calls/metrics — 401 without Authorization header
    - GET /api/v1/analytics/{client_id}/overview — 401 without header
    - GET /api/v1/scheduler/{client_id}/queue — 401 without header
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# Unit tests — require_api_key dependency
# ---------------------------------------------------------------------------


class TestRequireApiKey:
    """Unit tests for the require_api_key FastAPI dependency."""

    def _make_request(self, authorization: str | None) -> Request:
        """Build a minimal FastAPI Request with an optional Authorization header."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/clients",
            "headers": [],
            "query_string": b"",
        }
        if authorization is not None:
            scope["headers"] = [(b"authorization", authorization.encode())]
        return Request(scope)

    def _make_settings(self, api_key: str = "test-secret-key") -> object:
        """Return a minimal settings stub with qora_api_key."""
        settings = MagicMock()
        settings.qora_api_key = SecretStr(api_key)
        return settings

    def test_valid_bearer_token_returns_caller_identity(self):
        """Valid 'Authorization: Bearer <key>' returns a CallerIdentity."""
        from app.core.auth import require_api_key, CallerIdentity

        request = self._make_request("Bearer test-secret-key")
        settings = self._make_settings("test-secret-key")

        result = require_api_key(request, settings)

        assert isinstance(result, CallerIdentity)

    def test_caller_identity_does_not_store_raw_key(self):
        """CallerIdentity must NOT store the raw API key — only a hash."""
        from app.core.auth import require_api_key, CallerIdentity

        raw_key = "super-secret-api-key"
        request = self._make_request(f"Bearer {raw_key}")
        settings = self._make_settings(raw_key)

        result = require_api_key(request, settings)

        assert isinstance(result, CallerIdentity)
        # Raw key must NOT appear anywhere in the dataclass
        result_str = str(result.__dict__)
        assert raw_key not in result_str

    def test_missing_authorization_header_raises_401(self):
        """Missing Authorization header → HTTPException 401."""
        from app.core.auth import require_api_key
        from fastapi import HTTPException

        request = self._make_request(None)
        settings = self._make_settings("test-secret-key")

        with pytest.raises(HTTPException) as exc_info:
            require_api_key(request, settings)

        assert exc_info.value.status_code == 401

    def test_invalid_bearer_token_raises_401(self):
        """Wrong Bearer token → HTTPException 401."""
        from app.core.auth import require_api_key
        from fastapi import HTTPException

        request = self._make_request("Bearer wrong-key")
        settings = self._make_settings("correct-key")

        with pytest.raises(HTTPException) as exc_info:
            require_api_key(request, settings)

        assert exc_info.value.status_code == 401

    def test_malformed_header_no_bearer_prefix_raises_401(self):
        """Authorization header without 'Bearer ' prefix → HTTPException 401."""
        from app.core.auth import require_api_key
        from fastapi import HTTPException

        request = self._make_request("test-secret-key")  # missing "Bearer " prefix
        settings = self._make_settings("test-secret-key")

        with pytest.raises(HTTPException) as exc_info:
            require_api_key(request, settings)

        assert exc_info.value.status_code == 401

    def test_empty_bearer_token_raises_401(self):
        """'Authorization: Bearer ' with empty token → HTTPException 401."""
        from app.core.auth import require_api_key
        from fastapi import HTTPException

        request = self._make_request("Bearer ")
        settings = self._make_settings("test-secret-key")

        with pytest.raises(HTTPException) as exc_info:
            require_api_key(request, settings)

        assert exc_info.value.status_code == 401

    def test_different_valid_keys_both_accepted(self):
        """Triangulation: any correct key value is accepted, not just a hardcoded one."""
        from app.core.auth import require_api_key, CallerIdentity

        key_a = "alpha-key-12345"
        key_b = "beta-key-99999"

        request_a = self._make_request(f"Bearer {key_a}")
        settings_a = self._make_settings(key_a)
        result_a = require_api_key(request_a, settings_a)
        assert isinstance(result_a, CallerIdentity)

        request_b = self._make_request(f"Bearer {key_b}")
        settings_b = self._make_settings(key_b)
        result_b = require_api_key(request_b, settings_b)
        assert isinstance(result_b, CallerIdentity)

    def test_constant_time_comparison_used(self):
        """Verify secrets.compare_digest is used (not == operator) for constant-time compare."""
        import secrets
        from app.core import auth as auth_module

        # Confirm the module uses secrets.compare_digest somewhere in its source
        import inspect
        source = inspect.getsource(auth_module)
        assert "compare_digest" in source, (
            "require_api_key must use secrets.compare_digest for constant-time comparison"
        )


# ---------------------------------------------------------------------------
# Unit tests — Settings fields
# ---------------------------------------------------------------------------


class TestAuthSettings:
    """Unit tests for new auth-related Settings fields."""

    def test_settings_has_qora_api_key_field(self):
        """Settings must expose qora_api_key as SecretStr."""
        from app.core.config import Settings
        import inspect

        # The field must be declared on the class
        fields = Settings.model_fields
        assert "qora_api_key" in fields, "Settings is missing qora_api_key field"

    def test_settings_qora_api_key_is_secret_str(self):
        """qora_api_key field annotation must be SecretStr."""
        from app.core.config import Settings
        from pydantic import SecretStr

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_api_key=SecretStr("test-key"),
        )
        assert isinstance(settings.qora_api_key, SecretStr)

    def test_settings_qora_docs_enabled_default_true(self):
        """qora_docs_enabled must default to True (docs enabled by default in dev)."""
        from app.core.config import Settings
        from pydantic import SecretStr

        settings = Settings(
            openai_api_key=SecretStr("sk-test"),
            elevenlabs_api_key=SecretStr("el-test"),
            qora_api_key=SecretStr("test-key"),
        )
        assert settings.qora_docs_enabled is True


# ---------------------------------------------------------------------------
# Integration tests — admin routes return 401 without auth
# ---------------------------------------------------------------------------


@pytest.fixture
def test_app(tmp_path):
    """Create an isolated test app with a known API key."""
    from pydantic import SecretStr

    test_key = "integration-test-key-abc123"

    with patch("app.core.config.Settings") as MockSettings:
        instance = MockSettings.return_value
        instance.qora_api_key = SecretStr(test_key)
        instance.qora_docs_enabled = True
        instance.database_url = f"sqlite+aiosqlite:///{tmp_path}/test.db"
        instance.openai_api_key = SecretStr("sk-test")
        instance.elevenlabs_api_key = SecretStr("el-test")
        instance.log_level = "INFO"
        instance.host = "0.0.0.0"
        instance.port = 8000
        instance.debug = False
        instance.frontend_url = "http://localhost:5173"

        from app.main import app
        return app, test_key


# ---------------------------------------------------------------------------
# Unit tests — QORA_DOCS_ENABLED toggle
# ---------------------------------------------------------------------------


class TestDocsEnabledToggle:
    """Unit tests for QORA_DOCS_ENABLED docs/redoc toggle (Phase B5 — PR #1).

    Tests are isolated from the module-level ``app`` singleton by using the
    ``create_app()`` factory exported from ``app.main``.  Each test builds a
    fresh FastAPI instance so the toggle is exercised in isolation.
    """

    def test_docs_enabled_by_default(self):
        """When QORA_DOCS_ENABLED is not set, /docs returns 200."""
        from app.main import create_app

        test_app = create_app(docs_enabled=True)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs")
        assert response.status_code == 200

    def test_docs_disabled_returns_404(self):
        """When QORA_DOCS_ENABLED=false, /docs returns 404."""
        from app.main import create_app

        test_app = create_app(docs_enabled=False)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs")
        assert response.status_code == 404

    def test_redoc_enabled_by_default(self):
        """When QORA_DOCS_ENABLED is not set, /redoc returns 200."""
        from app.main import create_app

        test_app = create_app(docs_enabled=True)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/redoc")
        assert response.status_code == 200

    def test_redoc_disabled_returns_404(self):
        """When QORA_DOCS_ENABLED=false, /redoc returns 404."""
        from app.main import create_app

        test_app = create_app(docs_enabled=False)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/redoc")
        assert response.status_code == 404

    def test_docs_toggle_does_not_affect_health_check(self):
        """Disabling docs must not affect /api/v1/health availability."""
        from app.main import create_app

        test_app = create_app(docs_enabled=False)
        client = TestClient(test_app, raise_server_exceptions=False)
        # Health check must still be reachable even when docs are disabled
        response = client.get("/api/v1/health")
        assert response.status_code == 200


class TestDocsEnabledEnvContract:
    """Env-level tests: create_app(docs_enabled=None) reads QORA_DOCS_ENABLED.

    These tests exercise the production/default code path where create_app()
    is called without an explicit argument and must derive the docs toggle
    from the environment variable.  The factory-argument tests above (True/False)
    bypass this path entirely — these tests prove the actual deployment contract.
    """

    def test_env_false_disables_docs(self, monkeypatch):
        """QORA_DOCS_ENABLED=false → create_app(None) disables /docs (returns 404)."""
        import os
        from app.main import create_app

        monkeypatch.setenv("QORA_DOCS_ENABLED", "false")
        test_app = create_app(docs_enabled=None)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs")
        assert response.status_code == 404, (
            "QORA_DOCS_ENABLED=false must disable /docs; got "
            f"{response.status_code} instead of 404"
        )

    def test_env_false_disables_redoc(self, monkeypatch):
        """QORA_DOCS_ENABLED=false → create_app(None) disables /redoc (returns 404)."""
        monkeypatch.setenv("QORA_DOCS_ENABLED", "false")
        from app.main import create_app

        test_app = create_app(docs_enabled=None)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/redoc")
        assert response.status_code == 404, (
            "QORA_DOCS_ENABLED=false must disable /redoc; got "
            f"{response.status_code} instead of 404"
        )

    def test_env_true_enables_docs(self, monkeypatch):
        """QORA_DOCS_ENABLED=true → create_app(None) enables /docs (returns 200)."""
        monkeypatch.setenv("QORA_DOCS_ENABLED", "true")
        from app.main import create_app

        test_app = create_app(docs_enabled=None)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs")
        assert response.status_code == 200, (
            "QORA_DOCS_ENABLED=true must enable /docs; got "
            f"{response.status_code} instead of 200"
        )

    def test_env_absent_defaults_to_docs_enabled(self, monkeypatch):
        """No QORA_DOCS_ENABLED env var → create_app(None) enables /docs by default."""
        monkeypatch.delenv("QORA_DOCS_ENABLED", raising=False)
        from app.main import create_app

        test_app = create_app(docs_enabled=None)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/docs")
        assert response.status_code == 200, (
            "Without QORA_DOCS_ENABLED, /docs must be enabled (default true); "
            f"got {response.status_code} instead of 200"
        )

    def test_env_false_health_check_still_accessible(self, monkeypatch):
        """QORA_DOCS_ENABLED=false → /api/v1/health remains accessible."""
        monkeypatch.setenv("QORA_DOCS_ENABLED", "false")
        from app.main import create_app

        test_app = create_app(docs_enabled=None)
        client = TestClient(test_app, raise_server_exceptions=False)
        response = client.get("/api/v1/health")
        assert response.status_code == 200, (
            "Disabling docs via env must not affect health check availability"
        )


class TestAdminRoutesRequireAuth:
    """Integration tests: admin routes return 401 without auth, 200 with valid auth."""

    def test_health_check_is_public(self):
        """GET /api/v1/health returns 200 without any Authorization header."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/health")
        # Health check must always be public (Docker health check compatibility)
        assert response.status_code == 200

    def test_clients_list_returns_401_without_auth(self):
        """GET /api/v1/clients returns 401 without Authorization header."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/clients")
        assert response.status_code == 401

    def test_clients_list_returns_401_with_wrong_key(self):
        """GET /api/v1/clients returns 401 with a wrong Bearer token."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(
            "/api/v1/clients",
            headers={"Authorization": "Bearer totally-wrong-key"},
        )
        assert response.status_code == 401

    def test_leads_list_returns_401_without_auth(self):
        """GET /api/v1/leads returns 401 without Authorization header."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/leads?client_id=test")
        assert response.status_code == 401

    def test_calls_metrics_returns_401_without_auth(self):
        """GET /api/v1/calls/metrics returns 401 without Authorization header."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/calls/metrics?client_id=test")
        assert response.status_code == 401

    def test_analytics_returns_401_without_auth(self):
        """GET /api/v1/analytics/{client_id}/overview returns 401 without auth."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/analytics/test-client/overview")
        assert response.status_code == 401

    def test_scheduler_returns_401_without_auth(self):
        """GET /api/v1/scheduler/{client_id}/queue returns 401 without auth."""
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/scheduler/test-client/queue")
        assert response.status_code == 401
