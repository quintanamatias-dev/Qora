"""QORA Outbound — E.164 phone number validation.

Validates phone numbers at outbound trigger time (before any ElevenLabs API
call) to prevent charges for unreachable numbers.

Design decision (design.md):
  Use `phonenumbers` library when available — validates at carrier level,
  handles country rules (e.g. Argentina 15-digit mobile prefixes).
  Fallback: strict E.164 regex: ^\\+[1-9]\\d{6,14}$

  Tradeoff document:
    - phonenumbers: catches invalid country codes and unreachable prefixes.
      Adds a ~4MB dependency with no native extensions (pure Python).
    - Regex fallback: catches structural format errors only; cannot validate
      carrier-level validity. Sufficient for basic E.164 structural checks.

  phonenumbers is not in pyproject.toml as of C2. If added in a future slice,
  this module will prefer it automatically via the try/import guard.

  Spec: outbound-call-trigger — "Phone number E.164 validation at trigger time
  (reject if invalid)"
"""

from __future__ import annotations

import re

# E.164 structural format: + followed by country code (1-3 digits, not starting
# with 0) and subscriber number, total 7-15 digits including country code.
# Pattern: ^\\+[1-9]\\d{6,14}$ (leading + required; 7-15 digits after +)
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def validate_e164(phone: str) -> str:
    """Validate a phone number string is E.164 format.

    Attempts to use the `phonenumbers` library for carrier-level validation
    when available. Falls back to strict structural regex otherwise.

    Args:
        phone: Raw phone number string from lead record.

    Returns:
        The phone string unchanged when valid.

    Raises:
        ValueError: When the phone is not valid E.164. The error message
            includes "E.164" so API consumers can map it to a 422 response.

    Spec: outbound-call-trigger — "reject if invalid" (before any charge).
    """
    # Attempt phonenumbers library validation (preferred — carrier-level checks).
    try:
        import phonenumbers  # type: ignore[import-untyped]

        try:
            parsed = phonenumbers.parse(phone, None)
        except phonenumbers.NumberParseException as exc:
            raise ValueError(
                f"Phone number is not valid E.164: {phone!r}. "
                f"Supply a full international number with country code, e.g. +14155552671. "
                f"Parser error: {exc}"
            ) from exc

        if not phonenumbers.is_valid_number(parsed):
            raise ValueError(
                f"Phone number is not valid E.164: {phone!r}. "
                "The number is structurally well-formed but not a valid dialable number. "
                "Supply a full international number including country code."
            )

        return phone

    except ImportError:
        # phonenumbers not installed — fall back to structural regex.
        pass

    # Structural E.164 regex fallback.
    if not phone or not _E164_RE.match(phone):
        raise ValueError(
            f"Phone number is not valid E.164: {phone!r}. "
            "Expected format: +[country_code][subscriber_number], e.g. +14155552671. "
            "The number must start with '+', followed by 7 to 15 digits with no spaces "
            "or dashes. Install the 'phonenumbers' package for carrier-level validation."
        )

    return phone
