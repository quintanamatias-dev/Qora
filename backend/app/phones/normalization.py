"""Pure, fail-closed normalization for supported Argentine phone numbers."""

from __future__ import annotations

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType

_ALLOWED_REGION = "AR"
_ALLOWED_COUNTRY_CODE = 54
_ALLOWED_TYPES = frozenset({PhoneNumberType.MOBILE, PhoneNumberType.FIXED_LINE})
_ALLOWED_REASONS = frozenset(
    {
        "region_required",
        "unsupported_region",
        "invalid_syntax",
        "ambiguous_or_incomplete",
        "invalid_number",
        "unsupported_country",
        "unsupported_type",
    }
)


class PhoneNormalizationError(ValueError):
    """A stable, non-PII rejection for phone normalization."""

    def __init__(self, reason: str) -> None:
        if reason not in _ALLOWED_REASONS:
            raise ValueError("Unsupported phone normalization reason")
        self.reason = reason
        super().__init__(f"Invalid phone: {reason}")


def normalize_phone(raw: str, *, region: str) -> str:
    """Return a canonical E.164 Argentine mobile or fixed-line destination."""
    _require_supported_region(region)
    compact = _compact_supported_syntax(raw)

    if compact.startswith("+"):
        return _normalize_international(compact)
    return _normalize_domestic_mobile(compact)


def _require_supported_region(region: str) -> None:
    if not isinstance(region, str) or not region.strip():
        raise PhoneNormalizationError("region_required")
    if region != _ALLOWED_REGION:
        raise PhoneNormalizationError("unsupported_region")


def _compact_supported_syntax(raw: str) -> str:
    if not isinstance(raw, str):
        raise PhoneNormalizationError("invalid_syntax")

    value = raw.strip(" ")
    if not value:
        raise PhoneNormalizationError("invalid_syntax")

    inside_parentheses = False
    parenthesis_digits = 0
    for index, character in enumerate(value):
        if character.isascii() and character.isdigit():
            parenthesis_digits += inside_parentheses
            continue
        if character == "+" and index == 0:
            continue
        if character == "-":
            if index == 0 or index == len(value) - 1:
                raise PhoneNormalizationError("invalid_syntax")
            previous, following = value[index - 1], value[index + 1]
            if not _is_digit_or_closing_group(previous) or not _is_digit_or_opening_group(following):
                raise PhoneNormalizationError("invalid_syntax")
            continue
        if character == " ":
            continue
        if character == "(":
            if inside_parentheses:
                raise PhoneNormalizationError("invalid_syntax")
            inside_parentheses = True
            parenthesis_digits = 0
            continue
        if character == ")":
            if not inside_parentheses or not parenthesis_digits:
                raise PhoneNormalizationError("invalid_syntax")
            inside_parentheses = False
            continue
        raise PhoneNormalizationError("invalid_syntax")

    if inside_parentheses:
        raise PhoneNormalizationError("invalid_syntax")

    compact = "".join(character for character in value if character not in " -()")
    if compact in {"", "+"}:
        raise PhoneNormalizationError("invalid_syntax")
    return compact


def _normalize_international(compact: str) -> str:
    number = _parse(compact)
    if number.country_code != _ALLOWED_COUNTRY_CODE:
        raise PhoneNormalizationError("unsupported_country")
    if not _is_valid_argentine(number):
        raise PhoneNormalizationError("invalid_number")

    number_type = phonenumbers.number_type(number)
    e164 = phonenumbers.format_number(number, PhoneNumberFormat.E164)
    if e164 != compact:
        raise PhoneNormalizationError("invalid_number")

    if compact.startswith("+549") and len(compact) == 14 and number_type == PhoneNumberType.MOBILE:
        return e164
    if compact.startswith("+54") and not compact.startswith("+549") and len(compact) == 13:
        if number_type == PhoneNumberType.FIXED_LINE:
            return e164
    if number_type not in _ALLOWED_TYPES:
        raise PhoneNormalizationError("unsupported_type")
    raise PhoneNormalizationError("invalid_number")


def _normalize_domestic_mobile(compact: str) -> str:
    number = _parse(compact)
    if number.country_code != _ALLOWED_COUNTRY_CODE:
        raise PhoneNormalizationError("unsupported_country")
    if not _is_valid_argentine(number):
        if len(compact) <= 10:
            raise PhoneNormalizationError("ambiguous_or_incomplete")
        raise PhoneNormalizationError("invalid_number")

    number_type = phonenumbers.number_type(number)
    if number_type == PhoneNumberType.FIXED_LINE:
        raise PhoneNormalizationError("ambiguous_or_incomplete")
    if number_type != PhoneNumberType.MOBILE:
        raise PhoneNormalizationError("unsupported_type")

    e164 = phonenumbers.format_number(number, PhoneNumberFormat.E164)
    if not e164.startswith("+549") or len(e164) != 14:
        raise PhoneNormalizationError("invalid_number")

    national = _strip_visual_separators(phonenumbers.format_number(number, PhoneNumberFormat.NATIONAL))
    without_trunk = national[1:] if national.startswith("0") else national
    if compact not in {national, without_trunk}:
        raise PhoneNormalizationError("ambiguous_or_incomplete")
    return e164


def _parse(compact: str) -> phonenumbers.PhoneNumber:
    try:
        return phonenumbers.parse(compact, _ALLOWED_REGION, keep_raw_input=False)
    except phonenumbers.NumberParseException:
        raise PhoneNormalizationError("invalid_number") from None


def _is_valid_argentine(number: phonenumbers.PhoneNumber) -> bool:
    return phonenumbers.is_valid_number(number) and phonenumbers.is_valid_number_for_region(
        number, _ALLOWED_REGION
    )


def _is_digit_or_closing_group(character: str) -> bool:
    return (character.isascii() and character.isdigit()) or character == ")"


def _is_digit_or_opening_group(character: str) -> bool:
    return (character.isascii() and character.isdigit()) or character == "("


def _strip_visual_separators(value: str) -> str:
    return "".join(character for character in value if character not in " -()")
