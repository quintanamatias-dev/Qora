import re

import phonenumbers
import pytest
from phonenumbers import PhoneNumberFormat

from app.phones.normalization import PhoneNormalizationError, normalize_phone


_VISUAL_SEPARATORS = re.compile(r"[ ()-]")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("011 15 5555-0101", "+5491155550101"),
        ("0341 15 555-0101", "+5493415550101"),
        ("02966 15 550101", "+5492966550101"),
    ],
)
def test_locked_library_proves_domestic_mobile_national_round_trip(raw, expected):
    parsed = phonenumbers.parse(raw, "AR")

    assert phonenumbers.is_valid_number(parsed)
    assert phonenumbers.format_number(parsed, PhoneNumberFormat.E164) == expected
    national = _VISUAL_SEPARATORS.sub("", phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL))
    assert national.lstrip("0") == _VISUAL_SEPARATORS.sub("", raw).lstrip("0")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+54 9 11 5555 0101", "+5491155550101"),
        ("011 15 5555-0101", "+5491155550101"),
        ("0341 15 555-0101", "+5493415550101"),
        ("341155550101", "+5493415550101"),
        ("02966 15 550101", "+5492966550101"),
        ("296615550101", "+5492966550101"),
        ("+54 (11) 5555-0102", "+541155550102"),
    ],
)
def test_normalizes_supported_argentine_numbers(raw, expected):
    assert normalize_phone(raw, region="AR") == expected


def test_normalization_is_idempotent():
    canonical = normalize_phone("+54 9 11 5555 0101", region="AR")

    assert normalize_phone(canonical, region="AR") == canonical


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0(341) 15 555-0101", "+5493415550101"),
        ("+54 9 (11) 5555-0101", "+5491155550101"),
    ],
)
def test_normalizes_balanced_visual_groups(raw, expected):
    assert normalize_phone(raw, region="AR") == expected


@pytest.mark.parametrize("raw", ["+54 () 11 5555-0102", "+54 ((11)) 5555-0102"])
def test_rejects_empty_or_nested_parentheses(raw):
    with pytest.raises(PhoneNormalizationError) as raised:
        normalize_phone(raw, region="AR")

    assert raised.value.reason == "invalid_syntax"


@pytest.mark.parametrize("raw", ["+-54 9 11 5555 0101", "+54--9 11 5555 0101"])
def test_rejects_dangling_hyphens(raw):
    with pytest.raises(PhoneNormalizationError) as raised:
        normalize_phone(raw, region="AR")

    assert raised.value.reason == "invalid_syntax"


@pytest.mark.parametrize(
    ("raw", "region", "reason"),
    [
        ("011 5555-0101", "AR", "ambiguous_or_incomplete"),
        ("1155550101", "AR", "ambiguous_or_incomplete"),
        ("5555-0101", "AR", "ambiguous_or_incomplete"),
        ("15 5555-0101", "AR", "ambiguous_or_incomplete"),
        ("011 15 555-010", "AR", "invalid_number"),
        ("+549115555010", "AR", "invalid_number"),
        ("+54911555501011", "AR", "invalid_number"),
        ("011 5515-0101", "AR", "ambiguous_or_incomplete"),
        ("+54 011 5555-0102", "AR", "invalid_number"),
        ("0054 9 11 5555 0101", "AR", "ambiguous_or_incomplete"),
        ("5491155550101", "AR", "ambiguous_or_incomplete"),
        ("+56 9 5555 0101", "AR", "unsupported_country"),
        ("+54 800 555 0101", "AR", "unsupported_type"),
        ("Call +54 9 11 5555 0101 ext 7", "AR", "invalid_syntax"),
        ("tel:+5491155550101", "AR", "invalid_syntax"),
        ("1-800-QORA", "AR", "invalid_syntax"),
        ("+54.9.11.5555.0101", "AR", "invalid_syntax"),
        ("+54 9 11 5555 0101\n", "AR", "invalid_syntax"),
        ("+54 9 11 5555 ٠١٠١", "AR", "invalid_syntax"),
        ("+54 (11 5555-0102", "AR", "invalid_syntax"),
        (123, "AR", "invalid_syntax"),
        (True, "AR", "invalid_syntax"),
        ("011 15 5555-0101", "", "region_required"),
        ("011 15 5555-0101", "US", "unsupported_region"),
    ],
)
def test_rejects_unsupported_input_without_echoing_it(raw, region, reason):
    with pytest.raises(PhoneNormalizationError) as raised:
        normalize_phone(raw, region=region)

    assert raised.value.reason == reason
    assert str(raised.value) == f"Invalid phone: {reason}"
    assert str(raw) not in str(raised.value)
