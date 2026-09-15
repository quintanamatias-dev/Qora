"""QORA Outbound — E.164 phone number validation.

Validates phone numbers at outbound trigger time (before any ElevenLabs API
call) to prevent charges for unreachable numbers.

Design decision (design.md):
  Require an exact stored E.164 representation before validating it through the
  shared explicit-AR normalizer. The guard never repairs domestic notation,
  accepts foreign destinations, or falls back to structural-only validation.

  Spec: outbound-call-trigger — "Phone number E.164 validation at trigger time
  (reject if invalid)"
"""

from __future__ import annotations

import re

from app.phones.normalization import PhoneNormalizationError, normalize_phone

# Exact ASCII E.164 representation required for stored outbound destinations.
_E164_RE = re.compile(r"^\+[1-9][0-9]{6,14}$")


def validate_e164(phone: str) -> str:
    """Validate an already-canonical Argentine E.164 destination.

    This is a strict pre-dial guard: it does not normalize or repair storage.

    Args:
        phone: Raw phone number string from lead record.

    Returns:
        The phone string unchanged when valid.

    Raises:
        ValueError: When the phone is not valid E.164. The error message
            includes "E.164" so API consumers can map it to a 422 response.

    Spec: outbound-call-trigger — "reject if invalid" (before any charge).
    """
    if not isinstance(phone, str) or not _E164_RE.fullmatch(phone):
        raise ValueError("Phone number is not valid E.164: noncanonical_phone")

    try:
        normalized = normalize_phone(phone, region="AR")
    except PhoneNormalizationError as exc:
        raise ValueError(f"Phone number is not valid E.164: {exc.reason}") from None

    if normalized != phone:
        raise ValueError("Phone number is not valid E.164: noncanonical_phone")

    return phone
