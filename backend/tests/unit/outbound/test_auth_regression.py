"""Auth regression tests for the outbound call trigger endpoint.

Review blocker WARNING-8:
  The existing router tests bypass auth via dependency_overrides
  (app.dependency_overrides[require_api_key] = lambda: None).
  This means no test exercises the actual auth middleware on this endpoint.

  A regression test must prove that:
  1. Missing Authorization header → 401
  2. Wrong Bearer token → 401
  3. Valid Bearer token → endpoint proceeds (auth does not block valid calls)

  These tests use the real require_api_key dependency WITHOUT the bypass,
  by NOT overriding require_api_key in dependency_overrides. Instead, they
  set up app.state.settings with a real qora_api_key.

  This proves the endpoint is not accidentally public: if require_api_key
  were removed from the router, these tests would start passing with wrong
  credentials — alerting developers to a security regression.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app_with_real_auth(api_key: str = "test-admin-key-xyz"):
    """Build test app that uses the REAL require_api_key (no override).

    app.state.settings is set with a known api_key so tests can present it.
    The _TESTING_BYPASS flag must NOT be True for these tests to be meaningful.
    """
    from app.outbound.router import router as outbound_router, get_db_session, get_settings

    app = FastAPI()
    app.include_router(outbound_router)

    # Configure app.state.settings with a real api_key
    from pydantic import SecretStr as PS
    settings = MagicMock()
    settings.qora_api_key = PS(api_key)
    settings.enable_outbound_calls = False  # Flag off — we only care about auth for these tests
    settings.outbound_call_cooldown_seconds = 0  # No cooldown for auth tests
    app.state.settings = settings

    # Override DB and settings deps — but NOT require_api_key
    mock_db = AsyncMock()

    async def _fake_db():
        yield mock_db

    async def _fake_settings():
        return settings

    app.dependency_overrides[get_db_session] = _fake_db
    app.dependency_overrides[get_settings] = _fake_settings
    # DO NOT override require_api_key — we want to test the real auth

    return app, settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOutboundCallEndpointAuth:
    """Auth regression tests — endpoint must enforce require_api_key."""

    def test_missing_auth_header_returns_401(self):
        """GIVEN no Authorization header is sent
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 401 is returned with authentication_required error.

        This proves the endpoint is not accidentally public.
        """
        import app.core.auth as auth_module
        original_bypass = auth_module._TESTING_BYPASS
        auth_module._TESTING_BYPASS = False  # disable test bypass for this test

        try:
            app, _ = _build_app_with_real_auth()
            client = TestClient(app, raise_server_exceptions=False)

            response = client.post("/clients/client-a/leads/lead-001/call")

            assert response.status_code == 401, (
                f"Missing auth header must return 401. Got {response.status_code}: "
                f"{response.json()}"
            )
            body = response.json()
            # Accept both FastAPI validation error format and our custom format
            detail = body.get("detail", "")
            if isinstance(detail, dict):
                assert detail.get("error") == "authentication_required", (
                    f"Expected authentication_required error, got: {detail}"
                )
            else:
                assert "auth" in str(detail).lower() or "401" in str(response.status_code), (
                    f"Expected auth error in detail, got: {detail}"
                )
        finally:
            auth_module._TESTING_BYPASS = original_bypass

    def test_wrong_bearer_token_returns_401(self):
        """GIVEN a wrong Bearer token is sent
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 401 is returned.

        This proves the key validation logic is enforced on this endpoint.
        """
        import app.core.auth as auth_module
        original_bypass = auth_module._TESTING_BYPASS
        auth_module._TESTING_BYPASS = False

        try:
            app, _ = _build_app_with_real_auth(api_key="correct-key-abc")
            client = TestClient(app, raise_server_exceptions=False)

            response = client.post(
                "/clients/client-a/leads/lead-001/call",
                headers={"Authorization": "Bearer wrong-key-xyz"},
            )

            assert response.status_code == 401, (
                f"Wrong Bearer token must return 401. Got {response.status_code}: "
                f"{response.json()}"
            )
        finally:
            auth_module._TESTING_BYPASS = original_bypass

    def test_malformed_auth_scheme_returns_401(self):
        """GIVEN an Authorization header with wrong scheme (not Bearer)
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN HTTP 401 is returned.

        Protects against Basic/Digest auth accidentally being accepted.
        """
        import app.core.auth as auth_module
        original_bypass = auth_module._TESTING_BYPASS
        auth_module._TESTING_BYPASS = False

        try:
            app, _ = _build_app_with_real_auth()
            client = TestClient(app, raise_server_exceptions=False)

            response = client.post(
                "/clients/client-a/leads/lead-001/call",
                headers={"Authorization": "Basic dGVzdDp0ZXN0"},
            )

            assert response.status_code == 401, (
                f"Non-Bearer scheme must return 401. Got {response.status_code}: "
                f"{response.json()}"
            )
        finally:
            auth_module._TESTING_BYPASS = original_bypass

    def test_valid_bearer_token_passes_auth_to_next_guard(self):
        """GIVEN the correct Bearer token is presented
        WHEN POST /clients/{client_id}/leads/{lead_id}/call is called
        THEN auth passes (returns 403 from feature flag guard, NOT 401).

        This proves valid auth proceeds to the next guard (feature flag off → 403).
        403 from feature flag confirms auth was accepted.
        """
        import app.core.auth as auth_module
        original_bypass = auth_module._TESTING_BYPASS
        auth_module._TESTING_BYPASS = False

        try:
            api_key = "valid-test-key-for-auth-regression"
            app, _ = _build_app_with_real_auth(api_key=api_key)
            client = TestClient(app, raise_server_exceptions=False)

            response = client.post(
                "/clients/client-a/leads/lead-001/call",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            # Auth passed — next guard is feature flag (which is off → 403)
            assert response.status_code == 403, (
                f"Valid auth must pass (feature flag guard returns 403, not 401). "
                f"Got {response.status_code}: {response.json()}"
            )
            # Must not be a 401 (which would mean auth still failing)
            assert response.status_code != 401, (
                "Valid Bearer token must not return 401 — auth must pass"
            )
        finally:
            auth_module._TESTING_BYPASS = original_bypass
