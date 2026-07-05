"""Unit tests for E.164 phone number validator.

Spec: outbound-call-trigger — Requirement: Manual Trigger Endpoint
  GIVEN the lead's phone field is not valid E.164
  WHEN the trigger endpoint is called
  THEN HTTP 422 is returned with a descriptive error
  AND no CallSession is created
  AND the ElevenLabs API is not called

Design decision:
  Use phonenumbers library at trigger time; if unavailable fall back to strict
  E.164 regex: ^\\+[1-9]\\d{6,14}$
  Reject before charge — validate at trigger time, never at DB level.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# RED — validate_e164 does not exist yet
# ---------------------------------------------------------------------------


def test_valid_e164_international_us():
    """GIVEN a valid US E.164 number
    WHEN validate_e164 is called
    THEN it returns the number unchanged.
    """
    from app.outbound.phone import validate_e164

    result = validate_e164("+14155552671")
    assert result == "+14155552671"


def test_valid_e164_argentina():
    """GIVEN a valid Argentine mobile E.164 number
    WHEN validate_e164 is called
    THEN it returns the number unchanged.
    """
    from app.outbound.phone import validate_e164

    result = validate_e164("+5491123456789")
    assert result == "+5491123456789"


def test_invalid_e164_no_plus_prefix():
    """GIVEN a number without a leading '+' (not E.164)
    WHEN validate_e164 is called
    THEN it raises ValueError with a descriptive message.
    """
    from app.outbound.phone import validate_e164

    with pytest.raises(ValueError, match="E.164"):
        validate_e164("14155552671")


def test_invalid_e164_letters():
    """GIVEN a string containing letters
    WHEN validate_e164 is called
    THEN it raises ValueError.
    """
    from app.outbound.phone import validate_e164

    with pytest.raises(ValueError, match="E.164"):
        validate_e164("+1abc5552671")


def test_invalid_e164_too_short():
    """GIVEN a number that is too short to be a real phone number
    WHEN validate_e164 is called
    THEN it raises ValueError.
    """
    from app.outbound.phone import validate_e164

    with pytest.raises(ValueError, match="E.164"):
        validate_e164("+1")


def test_invalid_e164_empty_string():
    """GIVEN an empty string
    WHEN validate_e164 is called
    THEN it raises ValueError.
    """
    from app.outbound.phone import validate_e164

    with pytest.raises(ValueError, match="E.164"):
        validate_e164("")


def test_invalid_e164_local_format():
    """GIVEN a local-format number (no country code)
    WHEN validate_e164 is called
    THEN it raises ValueError.
    """
    from app.outbound.phone import validate_e164

    with pytest.raises(ValueError, match="E.164"):
        validate_e164("011-4455-6677")
