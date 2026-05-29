"""CRM field mapping and type coercion — pure, no IO.

Transforms a Qora lead dict into a CRM-ready payload dict using the
field_mappings declared in crm.yaml.

Design decisions:
- FieldMapper is stateless after construction: map() is a pure function
- All coercions are explicit and deterministic (same input → same output)
- Phone normalization: strip formatting noise, keep E.164 (+<digits>)
- Missing required field → MappingError (fail fast, explicit)
- Missing optional field → omit from output (silent skip)
- No IO, no DB calls, no side effects — safe to call from any context
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.integrations.crm_config import CRMFieldDef


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class MappingError(Exception):
    """Raised when a lead field cannot be coerced to the declared CRM type,
    or when a required field is absent from the lead data.
    """


# ---------------------------------------------------------------------------
# Phone normalization (pure)
# ---------------------------------------------------------------------------

_PHONE_STRIP_RE = re.compile(r"[\s\-\(\)\.]")
_E164_RE = re.compile(r"^\+[1-9]\d{1,14}$")


def normalize_phone_e164(raw: str) -> str:
    """Normalize a phone string to E.164 format (+<country><number>).

    Strategy:
    - Strip spaces, dashes, parentheses, dots.
    - Accept only valid E.164 after stripping.
    - Reject local/national numbers instead of guessing a country code.

    Qora stores phones with a '+' prefix by convention, so the E.164 path is the
    happy path. Local Argentina normalization is intentionally out of scope for
    this foundation slice; failing loudly avoids broken CRM de-duplication.
    """
    stripped = _PHONE_STRIP_RE.sub("", raw)
    if not _E164_RE.fullmatch(stripped):
        raise MappingError(
            f"Cannot coerce phone value {raw!r} to E.164. "
            "Expected '+<country_code><number>' with 2-15 digits total."
        )
    return stripped


# ---------------------------------------------------------------------------
# Type coercers (pure functions — one per declared type)
# ---------------------------------------------------------------------------

_TRUTHY_STRINGS = frozenset({"true", "1", "yes", "on"})
_FALSY_STRINGS = frozenset({"false", "0", "no", "off"})


def _coerce_string(source: str, value: Any) -> str:
    return str(value)


def _coerce_integer(source: str, value: Any) -> int:
    if isinstance(value, bool):
        # bool is a subclass of int in Python — reject it explicitly.
        raise MappingError(
            f"Cannot coerce field '{source}' value {value!r} to integer"
        )
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise MappingError(
            f"Cannot coerce field '{source}' value {value!r} to integer"
        )
    try:
        return int(value)
    except (ValueError, TypeError) as exc:
        raise MappingError(
            f"Cannot coerce field '{source}' value {value!r} to integer"
        ) from exc


def _coerce_boolean(source: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise MappingError(
            f"Cannot coerce field '{source}' value {value!r} to boolean. "
            "Integer booleans must be exactly 0 or 1."
        )
    if isinstance(value, str):
        lower = value.lower().strip()
        if lower in _TRUTHY_STRINGS:
            return True
        if lower in _FALSY_STRINGS:
            return False
    raise MappingError(
        f"Cannot coerce field '{source}' value {value!r} to boolean. "
        f"Expected one of: true/false, yes/no, 1/0, on/off"
    )


def _coerce_date(source: str, value: Any) -> str:
    """Serialize to ISO 8601 date string (YYYY-MM-DD)."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError as exc:
            raise MappingError(
                f"Cannot coerce field '{source}' value {value!r} to date string"
            ) from exc
    raise MappingError(
        f"Cannot coerce field '{source}' value {value!r} to date string"
    )


def _coerce_phone(source: str, value: Any) -> str:
    if not isinstance(value, str):
        value = str(value)
    return normalize_phone_e164(value)


_COERCERS = {
    "string": _coerce_string,
    "integer": _coerce_integer,
    "boolean": _coerce_boolean,
    "date": _coerce_date,
    "phone": _coerce_phone,
}


# ---------------------------------------------------------------------------
# FieldMapper
# ---------------------------------------------------------------------------


class FieldMapper:
    """Maps lead data to a CRM payload using declared field definitions.

    Constructed once from a list of CRMFieldDef; map() is a pure function.

    Example:
        field_defs = config.field_mappings
        mapper = FieldMapper(field_defs)
        crm_payload = mapper.map(lead_data)
    """

    def __init__(self, field_defs: list[CRMFieldDef]) -> None:
        self._field_defs = field_defs

    def map(self, lead_data: dict[str, Any]) -> dict[str, Any]:
        """Transform lead_data dict into a CRM-ready payload.

        Args:
            lead_data: Flat dict of lead fields (e.g. from Lead model or dict).

        Returns:
            Dict keyed by CRM target field names with coerced values.

        Raises:
            MappingError: If a required field is absent or a value cannot be coerced.
        """
        payload: dict[str, Any] = {}

        for field_def in self._field_defs:
            source = field_def.source
            target = field_def.target
            field_type = field_def.type
            required = field_def.required

            value = lead_data.get(source)

            if value is None:
                if required:
                    raise MappingError(
                        f"Required CRM field '{source}' is absent from lead data"
                    )
                # Optional — silently omit
                continue

            coercer = _COERCERS.get(field_type)
            if coercer is None:
                raise MappingError(
                    f"Unsupported CRM field type {field_type!r} for field '{source}'"
                )
            else:
                payload[target] = coercer(source, value)

        return payload
