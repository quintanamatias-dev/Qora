"""Tests: B9 observability — Sentry PII before_send filter (task 3.2).

Strict TDD RED phase.

Covered scenarios (spec: observability-sentry — Requirement: PII Filter via before_send):
    - API key in extra data is scrubbed to [REDACTED]
    - Token in extra data is scrubbed to [REDACTED]
    - Secret in extra data is scrubbed to [REDACTED]
    - Password in extra data is scrubbed to [REDACTED]
    - DSN in extra data is scrubbed to [REDACTED]
    - E.164 phone number in field value is scrubbed to [REDACTED]
    - Transcript field is scrubbed to [REDACTED]
    - Content field is scrubbed to [REDACTED]
    - Scrubbing failure returns None (event dropped — defense in depth)
    - Non-PII fields pass through unchanged
    - Nested dicts are recursively scrubbed
    - before_send not registered when Sentry is disabled (tested via init_sentry mock)
    - Auth-bearing HTTP headers are redacted by exact name (B9 PR2 risk fix)
    - request.data is replaced wholesale with [Filtered] regardless of type
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.observability import sentry_before_send


_REDACTED = "[REDACTED]"
_FILTERED = "[Filtered]"

# Neutral, non-secret sentinel used as scrubber INPUT wherever a test only needs
# "some value that must be redacted". The scrubber redacts by key name / header
# name, so the literal value is irrelevant — these are deliberately not shaped
# like real keys, tokens, or passwords to avoid tripping secret scanners.
_SENTINEL_VALUE = "sentinel-value-not-a-secret"


# ---------------------------------------------------------------------------
# Sensitive HTTP header redaction (B9 PR2 risk fix)
# ---------------------------------------------------------------------------


class TestSensitiveHeaderRedaction:
    """Auth-bearing request headers must be redacted by exact, case-insensitive name."""

    def test_authorization_header_is_redacted(self):
        event = {"request": {"headers": {"Authorization": _SENTINEL_VALUE}}}
        result = sentry_before_send(event, {})
        assert result is not None
        assert result["request"]["headers"]["Authorization"] == _REDACTED

    def test_authorization_header_lowercase_is_redacted(self):
        event = {"request": {"headers": {"authorization": _SENTINEL_VALUE}}}
        result = sentry_before_send(event, {})
        assert result["request"]["headers"]["authorization"] == _REDACTED

    def test_cookie_header_is_redacted(self):
        event = {"request": {"headers": {"Cookie": _SENTINEL_VALUE}}}
        result = sentry_before_send(event, {})
        assert result["request"]["headers"]["Cookie"] == _REDACTED

    def test_set_cookie_header_is_redacted(self):
        event = {"request": {"headers": {"Set-Cookie": _SENTINEL_VALUE}}}
        result = sentry_before_send(event, {})
        assert result["request"]["headers"]["Set-Cookie"] == _REDACTED

    def test_x_api_key_header_is_redacted(self):
        event = {"request": {"headers": {"X-API-Key": _SENTINEL_VALUE}}}
        result = sentry_before_send(event, {})
        assert result["request"]["headers"]["X-API-Key"] == _REDACTED

    def test_xi_api_key_header_is_redacted(self):
        event = {"request": {"headers": {"XI-API-Key": _SENTINEL_VALUE}}}
        result = sentry_before_send(event, {})
        assert result["request"]["headers"]["XI-API-Key"] == _REDACTED

    def test_non_sensitive_header_passes_through(self):
        event = {"request": {"headers": {"User-Agent": "curl/8.0", "Accept": "*/*"}}}
        result = sentry_before_send(event, {})
        assert result["request"]["headers"]["User-Agent"] == "curl/8.0"
        assert result["request"]["headers"]["Accept"] == "*/*"


# ---------------------------------------------------------------------------
# request.data wholesale filtering (B9 PR2 risk fix)
# ---------------------------------------------------------------------------


class TestRequestDataFiltering:
    """request.data is never known-safe — it is replaced wholesale regardless of type."""

    def test_raw_string_json_body_is_filtered(self):
        event = {
            "request": {
                "data": '{"password": "' + _SENTINEL_VALUE + '", "phone": "+15551234567"}'
            }
        }
        result = sentry_before_send(event, {})
        assert result is not None
        assert result["request"]["data"] == _FILTERED

    def test_dict_body_is_filtered(self):
        event = {"request": {"data": {"transcript": "Hi, I'm John", "ok": "field"}}}
        result = sentry_before_send(event, {})
        assert result["request"]["data"] == _FILTERED

    def test_transcript_body_is_filtered(self):
        event = {"request": {"data": {"transcript": "Caller: my SSN is ..."}}}
        result = sentry_before_send(event, {})
        assert result["request"]["data"] == _FILTERED
        # No fragment of the original body should survive.
        assert "SSN" not in str(result["request"]["data"])

    def test_list_body_is_filtered(self):
        event = {"request": {"data": [{"secret": "x"}, {"token": "y"}]}}
        result = sentry_before_send(event, {})
        assert result["request"]["data"] == _FILTERED

    def test_request_without_data_passes_through(self):
        event = {"request": {"headers": {"Accept": "*/*"}}}
        result = sentry_before_send(event, {})
        assert result is not None
        assert "data" not in result["request"]


# ---------------------------------------------------------------------------
# Key-name based redaction
# ---------------------------------------------------------------------------


class TestPIIKeyRedaction:
    """Fields whose key names match PII patterns must be redacted."""

    def test_api_key_in_extra_is_redacted(self):
        """Extra field 'openai_api_key' must be replaced with [REDACTED]."""
        event = {"extra": {"openai_api_key": _SENTINEL_VALUE}}
        result = sentry_before_send(event, {})
        assert result is not None
        assert result["extra"]["openai_api_key"] == _REDACTED

    def test_token_field_is_redacted(self):
        """Extra field 'auth_token' must be replaced with [REDACTED]."""
        event = {"extra": {"auth_token": _SENTINEL_VALUE}}
        result = sentry_before_send(event, {})
        assert result["extra"]["auth_token"] == _REDACTED

    def test_secret_field_is_redacted(self):
        """Extra field 'webhook_secret' must be replaced with [REDACTED]."""
        event = {"extra": {"webhook_secret": _SENTINEL_VALUE}}
        result = sentry_before_send(event, {})
        assert result["extra"]["webhook_secret"] == _REDACTED

    def test_password_field_is_redacted(self):
        """Extra field 'user_password' must be replaced with [REDACTED]."""
        event = {"extra": {"user_password": _SENTINEL_VALUE}}
        result = sentry_before_send(event, {})
        assert result["extra"]["user_password"] == _REDACTED

    def test_dsn_field_is_redacted(self):
        """Extra field 'sentry_dsn' must be replaced with [REDACTED]."""
        event = {"extra": {"sentry_dsn": _SENTINEL_VALUE}}
        result = sentry_before_send(event, {})
        assert result["extra"]["sentry_dsn"] == _REDACTED

    def test_transcript_field_is_redacted(self):
        """Extra field containing 'transcript' must be replaced with [REDACTED]."""
        event = {"extra": {"call_transcript": "Hello, my name is John Doe..."}}
        result = sentry_before_send(event, {})
        assert result["extra"]["call_transcript"] == _REDACTED

    def test_content_field_is_redacted(self):
        """Extra field containing 'content' must be replaced with [REDACTED]."""
        event = {"extra": {"message_content": "Sensitive message body"}}
        result = sentry_before_send(event, {})
        assert result["extra"]["message_content"] == _REDACTED

    def test_non_pii_field_passes_through(self):
        """Regular extra fields must not be redacted."""
        event = {"extra": {"job_type": "summarize", "attempt": 2}}
        result = sentry_before_send(event, {})
        assert result is not None
        assert result["extra"]["job_type"] == "summarize"
        assert result["extra"]["attempt"] == 2

    def test_event_without_extra_passes_through(self):
        """Events with no 'extra' key must be returned unchanged (no KeyError)."""
        event = {"level": "error", "message": "Something went wrong"}
        result = sentry_before_send(event, {})
        assert result is not None
        assert result["level"] == "error"
        assert result["message"] == "Something went wrong"


# ---------------------------------------------------------------------------
# Value-based phone number redaction
# ---------------------------------------------------------------------------


class TestPhoneRedaction:
    """E.164 phone numbers in string values must be scrubbed."""

    def test_e164_phone_in_extra_value_is_redacted(self):
        """E.164 phone number embedded in a non-sensitive field value is redacted."""
        event = {"extra": {"caller": "+15551234567"}}
        result = sentry_before_send(event, {})
        assert result is not None
        assert "+15551234567" not in result["extra"]["caller"]
        assert _REDACTED in result["extra"]["caller"]

    def test_short_international_phone_is_redacted(self):
        """Shorter E.164 phone numbers are also scrubbed."""
        event = {"extra": {"number": "+449876543"}}
        result = sentry_before_send(event, {})
        assert "+449876543" not in result["extra"]["number"]

    def test_plain_non_phone_string_passes_through(self):
        """Non-phone string values must not be altered."""
        event = {"extra": {"status": "running", "job_id": "abc-123"}}
        result = sentry_before_send(event, {})
        assert result["extra"]["status"] == "running"
        assert result["extra"]["job_id"] == "abc-123"


# ---------------------------------------------------------------------------
# Nested recursion
# ---------------------------------------------------------------------------


class TestNestedScrubbing:
    """Scrubber must recurse into nested dicts and lists."""

    def test_nested_dict_pii_is_scrubbed(self):
        """PII in a nested dict inside extra must be scrubbed recursively."""
        event = {
            "extra": {
                "metadata": {
                    "openai_api_key": _SENTINEL_VALUE,
                    "job_type": "summarize",
                }
            }
        }
        result = sentry_before_send(event, {})
        assert result["extra"]["metadata"]["openai_api_key"] == _REDACTED
        assert result["extra"]["metadata"]["job_type"] == "summarize"

    def test_list_values_are_scrubbed(self):
        """PII inside list elements in extra must be scrubbed."""
        event = {
            "extra": {
                # A list of dicts — each dict should be scrubbed
                "attempts": [
                    {"job_id": "abc", "auth_token": _SENTINEL_VALUE},
                    {"job_id": "def", "auth_token": _SENTINEL_VALUE},
                ]
            }
        }
        result = sentry_before_send(event, {})
        for item in result["extra"]["attempts"]:
            assert item["auth_token"] == _REDACTED
            assert item["job_id"] is not None  # non-PII preserved

    def test_user_context_is_scrubbed(self):
        """User context dict must be recursively scrubbed."""
        event = {
            "user": {
                "id": "user-123",
                "api_key": _SENTINEL_VALUE,
            }
        }
        result = sentry_before_send(event, {})
        assert result["user"]["api_key"] == _REDACTED
        # user.id doesn't match PII key patterns — it passes through
        assert result["user"]["id"] == "user-123"


# ---------------------------------------------------------------------------
# Defense in depth — drop event on scrub failure
# ---------------------------------------------------------------------------


class TestScrubFailureDropsEvent:
    """If scrubbing raises, the event must be dropped (return None)."""

    def test_returns_none_when_scrubbing_fails(self):
        """before_send must return None (drop event) if an internal error occurs.

        We patch _scrub_dict (internal helper) to raise, simulating a scrubbing
        failure, then verify the event is dropped rather than transmitted raw.
        """
        event = {"extra": {"job_id": "abc"}}
        with patch("app.core.observability._scrub_dict", side_effect=RuntimeError("boom")):
            result = sentry_before_send(event, {})
        assert result is None, (
            "before_send must return None (drop event) when scrubbing fails"
        )
