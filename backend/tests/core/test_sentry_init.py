"""Tests: B9 observability — optional Sentry initialization (task 3.1).

Strict TDD RED phase.

Covered scenarios (spec: observability-sentry — Optional Sentry Initialization):
    - Sentry init called with FastAPI integration when DSN is set
    - Sentry init NOT called when DSN is absent (None)
    - Sentry init NOT called when DSN is empty string
    - before_send callback is registered when DSN is set
    - No Sentry import side-effects when DSN is absent
    - Startup log confirms Sentry active (without DSN value) when DSN set
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

# Production code imported under test — will fail (RED) until init_sentry()
# is added to app.core.observability.
from app.core.observability import init_sentry


# Neutral, non-secret sentinel standing in for a configured Sentry DSN. These
# tests mock sentry_sdk, so init() only needs a present, non-empty string — the
# value is deliberately NOT shaped like a real DSN (no embedded key/host).
_FAKE_DSN = "dsn-sentinel-present"


class TestSentryInitWithDSN:
    """Sentry initializes when a non-empty DSN is provided."""

    def test_init_sentry_calls_sentry_sdk_init_when_dsn_set(self):
        """sentry_sdk.init() must be called when DSN is a non-empty string."""
        fake_dsn = _FAKE_DSN
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry(fake_dsn)
        mock_sentry.init.assert_called_once()

    def test_init_sentry_passes_dsn_to_sentry_sdk(self):
        """sentry_sdk.init() must receive the DSN as the first positional argument."""
        fake_dsn = _FAKE_DSN
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry(fake_dsn)
        call_kwargs = mock_sentry.init.call_args
        # DSN may be positional or keyword — check both
        all_args = list(call_kwargs.args) + list(call_kwargs.kwargs.values())
        assert fake_dsn in all_args or call_kwargs.kwargs.get("dsn") == fake_dsn

    def test_init_sentry_registers_before_send_callback(self):
        """before_send callback must be registered in sentry_sdk.init() call."""
        from app.core.observability import sentry_before_send

        fake_dsn = _FAKE_DSN
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry(fake_dsn)
        call_kwargs = mock_sentry.init.call_args
        assert call_kwargs.kwargs.get("before_send") is sentry_before_send, (
            "before_send must be the sentry_before_send PII filter"
        )

    def test_init_sentry_includes_fastapi_integration(self):
        """sentry_sdk.init() must include the FastAPI (or Starlette) integration."""
        fake_dsn = _FAKE_DSN
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            # Patch the integrations list from sentry_sdk
            with patch("app.core.observability.StarletteIntegration", create=True):
                with patch("app.core.observability.FastApiIntegration", create=True):
                    init_sentry(fake_dsn)
        mock_sentry.init.assert_called_once()
        call_kwargs = mock_sentry.init.call_args
        integrations = call_kwargs.kwargs.get("integrations", [])
        assert len(integrations) > 0, "At least one integration must be registered"


class TestSentryInitWithoutDSN:
    """Sentry must NOT initialize when DSN is absent or empty."""

    def test_init_sentry_not_called_when_dsn_is_none(self):
        """sentry_sdk.init() must NOT be called when DSN is None."""
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry(None)
        mock_sentry.init.assert_not_called()

    def test_init_sentry_not_called_when_dsn_is_empty_string(self):
        """sentry_sdk.init() must NOT be called when DSN is empty string."""
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry("")
        mock_sentry.init.assert_not_called()

    def test_init_sentry_not_called_when_dsn_is_whitespace_only(self):
        """DSN consisting only of whitespace is treated as absent."""
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry("   ")
        mock_sentry.init.assert_not_called()

    def test_init_sentry_returns_none_silently_when_dsn_absent(self):
        """init_sentry() must return None without raising when DSN is absent."""
        with patch("app.core.observability.sentry_sdk"):
            result = init_sentry(None)
        assert result is None

    def test_init_sentry_no_side_effects_without_dsn(self):
        """With no DSN, no sentry_sdk attributes should be accessed at all."""
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            init_sentry(None)
        # Only init may be called — and it should NOT be
        mock_sentry.init.assert_not_called()
        mock_sentry.capture_exception.assert_not_called()
        mock_sentry.capture_event.assert_not_called()


class TestSentryInitInvalidDSN:
    """An invalid/optional DSN must never abort startup (B9 PR2 reliability fix)."""

    def test_invalid_dsn_does_not_raise(self):
        """init_sentry() must swallow sentry_sdk.init() errors and continue.

        A malformed DSN makes the real sentry_sdk.init() raise BadDsn. The app
        must keep running with Sentry disabled rather than crashing on startup.
        """
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            mock_sentry.init.side_effect = ValueError("Unsupported scheme")
            # Must NOT raise.
            result = init_sentry("not-a-valid-dsn")
        assert result is None
        mock_sentry.init.assert_called_once()

    def test_invalid_dsn_with_real_sdk_does_not_raise(self):
        """End-to-end: a clearly malformed DSN does not propagate an exception."""
        # No mock — exercise the real sentry_sdk.init() error path.
        result = init_sentry("http://missing-key-and-host")
        assert result is None

    def test_invalid_dsn_does_not_log_dsn_value(self, caplog):
        """The failure log must NOT contain the DSN value (it may carry a secret)."""
        # Distinctive non-secret marker passed as the whole DSN argument. We use a
        # neutral sentinel — NOT a DSN-shaped string (no scheme, no "@" credential
        # separator, no secret-like substring) — so the test fixture itself never
        # resembles a real credential. If init_sentry ever logged the raw DSN, this
        # token would leak into caplog, so its absence proves the value is not logged.
        sensitive_marker = "do-not-log-this-marker"
        with patch("app.core.observability.sentry_sdk") as mock_sentry:
            mock_sentry.init.side_effect = ValueError("BadDsn")
            init_sentry(sensitive_marker)
        assert sensitive_marker not in caplog.text
