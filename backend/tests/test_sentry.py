"""Tests for Sentry integration — B9 Observability PR2.

Spec: sdd/b9-observability/spec — capability: sentry-integration

TDD RED phase: these tests MUST fail before implementation exists.
TDD GREEN phase: all pass after backend/app/core/sentry.py is created.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Task 5.1 — init_sentry() conditional initialization
# ---------------------------------------------------------------------------


def test_init_sentry_no_op_when_dsn_absent():
    """Scenario: App starts without SENTRY_DSN — Sentry is NOT initialized."""
    from app.core.sentry import init_sentry

    mock_settings = MagicMock()
    mock_settings.sentry_dsn = None

    with patch("app.core.sentry.sentry_sdk") as mock_sdk:
        init_sentry(mock_settings)

    mock_sdk.init.assert_not_called()


def test_init_sentry_initializes_when_dsn_present():
    """Scenario: App starts with SENTRY_DSN — Sentry SDK is initialized."""
    from app.core.sentry import init_sentry

    mock_settings = MagicMock()
    mock_settings.sentry_dsn = "https://key@sentry.io/123"
    mock_settings.sentry_environment = "production"
    mock_settings.app_version = "0.1.0"

    with patch("app.core.sentry.sentry_sdk") as mock_sdk:
        init_sentry(mock_settings)

    mock_sdk.init.assert_called_once()
    call_kwargs = mock_sdk.init.call_args.kwargs
    assert call_kwargs["dsn"] == "https://key@sentry.io/123"
    assert call_kwargs["environment"] == "production"


def test_init_sentry_configures_before_send_hook():
    """Scenario: before_send hook is always configured when DSN is set."""
    from app.core.sentry import init_sentry

    mock_settings = MagicMock()
    mock_settings.sentry_dsn = "https://key@sentry.io/456"
    mock_settings.sentry_environment = "staging"
    mock_settings.app_version = "0.1.0"

    with patch("app.core.sentry.sentry_sdk") as mock_sdk:
        init_sentry(mock_settings)

    call_kwargs = mock_sdk.init.call_args.kwargs
    assert "before_send" in call_kwargs
    assert callable(call_kwargs["before_send"])


# ---------------------------------------------------------------------------
# Task 5.1 — PII before_send scrubber (phone numbers and API keys)
# ---------------------------------------------------------------------------


def test_pii_scrubber_redacts_e164_phone_number():
    """Scenario: Phone number in event data is replaced with [REDACTED_PHONE]."""
    from app.core.sentry import scrub_pii

    event = {
        "message": "Contact: +14155552671",
        "extra": {"detail": "called +14155552671 twice"},
    }
    result = scrub_pii(event, {})

    assert result is not None
    # Phone must be redacted in message
    assert "[REDACTED_PHONE]" in result["message"]
    assert "+14155552671" not in result["message"]


def test_pii_scrubber_redacts_sk_prefixed_api_key():
    """Scenario: sk- prefixed API key in exception message is redacted."""
    from app.core.sentry import scrub_pii

    # 32+ char sk- key
    api_key = "sk-" + "a" * 48
    event = {
        "message": f"Authorization failed for {api_key}",
        "extra": {},
    }
    result = scrub_pii(event, {})

    assert result is not None
    assert "[REDACTED_KEY]" in result["message"]
    assert api_key not in result["message"]


def test_pii_scrubber_redacts_pk_prefixed_api_key():
    """Scenario: pk- prefixed API key in event data is redacted."""
    from app.core.sentry import scrub_pii

    api_key = "pk-" + "b" * 48
    event = {
        "message": f"Token mismatch: {api_key}",
        "extra": {},
    }
    result = scrub_pii(event, {})

    assert result is not None
    assert "[REDACTED_KEY]" in result["message"]
    assert api_key not in result["message"]


def test_pii_scrubber_redacts_hex_api_key():
    """Scenario: 32+ hex char API key in event data is redacted."""
    from app.core.sentry import scrub_pii

    # Exactly 32 hex chars
    hex_key = "a" * 32
    event = {
        "message": f"Key used: {hex_key}",
        "extra": {},
    }
    result = scrub_pii(event, {})

    assert result is not None
    assert "[REDACTED_KEY]" in result["message"]
    assert hex_key not in result["message"]


def test_pii_scrubber_clean_event_passes_through_unchanged():
    """Scenario: Clean event with no PII is returned unmodified."""
    from app.core.sentry import scrub_pii

    event = {
        "message": "User clicked submit button",
        "extra": {"page": "checkout"},
    }
    result = scrub_pii(event, {})

    assert result is not None
    assert result["message"] == "User clicked submit button"
    assert result["extra"]["page"] == "checkout"


def test_pii_scrubber_event_still_sent_after_redaction():
    """Scenario: After redaction the event is still returned (not dropped)."""
    from app.core.sentry import scrub_pii

    event = {
        "message": "Contact +14155552671",
        "extra": {},
    }
    result = scrub_pii(event, {})

    # Must return the event (not None / not drop it)
    assert result is not None
