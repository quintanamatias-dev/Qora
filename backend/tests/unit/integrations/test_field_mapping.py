"""Unit tests for CRM field mapping and coercion — TDD RED phase.

Covers spec scenarios:
- FM-5: coerce/reject field values that don't match declared types
- FM-6: arbitrary key-value field_map entries supported
- String coercion (passthrough)
- Integer coercion from numeric str and int
- Boolean coercion from bool, "true"/"false", 1/0
- Date coercion — ISO 8601 string passthrough, datetime → ISO string
- Phone normalization to E.164 format
- Required field missing → raises MappingError
- Source field absent from lead data → omitted (not required) or raises (required)
- Mapping is pure — no IO, no side effects

Test layer: Unit — pure functions, no IO, no mocks needed.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. String coercion — passthrough
# ---------------------------------------------------------------------------


def test_map_string_field_passthrough():
    """String type: value passed through as-is."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="name", target="Nombre", type="string")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"name": "Lucía Fernández"})

    assert result == {"Nombre": "Lucía Fernández"}


def test_map_string_field_int_value_coerced_to_str():
    """String type: integer value is coerced to string."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="age", target="EdadStr", type="string")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"age": 35})

    assert result == {"EdadStr": "35"}


# ---------------------------------------------------------------------------
# 2. Integer coercion
# ---------------------------------------------------------------------------


def test_map_integer_field_from_int():
    """Integer type: native int passes through unchanged."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="interest_level", target="Interés", type="integer")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"interest_level": 7})

    assert result == {"Interés": 7}


def test_map_integer_field_from_numeric_string():
    """Integer type: numeric string "42" coerced to int 42."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="age", target="Edad", type="integer")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"age": "42"})

    assert result == {"Edad": 42}


def test_map_integer_field_from_integral_float():
    """Integer type: integral float 42.0 is accepted as exact int 42."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="age", target="Edad", type="integer")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"age": 42.0})

    assert result == {"Edad": 42}


def test_map_integer_field_rejects_fractional_float():
    """Integer type: fractional float must not be silently truncated."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="age", target="Edad", type="integer")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="age"):
        mapper.map({"age": 3.14})


def test_map_integer_field_invalid_string_raises():
    """Integer type: non-numeric string raises MappingError."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="age", target="Edad", type="integer")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="age"):
        mapper.map({"age": "not-a-number"})


def test_map_integer_field_rejects_bool():
    """Integer type: bool must NOT be silently coerced to 0/1 (avoids type confusion)."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="flag", target="Edad", type="integer")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="flag"):
        mapper.map({"flag": True})


# ---------------------------------------------------------------------------
# 3. Boolean coercion
# ---------------------------------------------------------------------------


def test_map_boolean_field_from_bool():
    """Boolean type: native bool passes through."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="do_not_call", target="NoLlamar", type="boolean")]
    mapper = FieldMapper(field_defs)

    assert mapper.map({"do_not_call": True}) == {"NoLlamar": True}
    assert mapper.map({"do_not_call": False}) == {"NoLlamar": False}


def test_map_boolean_field_from_string_true():
    """Boolean type: string 'true'/'1' coerced to True."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="active", target="Activo", type="boolean")]
    mapper = FieldMapper(field_defs)

    assert mapper.map({"active": "true"}) == {"Activo": True}
    assert mapper.map({"active": "1"}) == {"Activo": True}
    assert mapper.map({"active": "yes"}) == {"Activo": True}


def test_map_boolean_field_from_string_false():
    """Boolean type: string 'false'/'0' coerced to False."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="active", target="Activo", type="boolean")]
    mapper = FieldMapper(field_defs)

    assert mapper.map({"active": "false"}) == {"Activo": False}
    assert mapper.map({"active": "0"}) == {"Activo": False}
    assert mapper.map({"active": "no"}) == {"Activo": False}


def test_map_boolean_field_accepts_explicit_int_0_and_1():
    """Boolean type: ints 0 and 1 are accepted (explicit binary representation)."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="active", target="Activo", type="boolean")]
    mapper = FieldMapper(field_defs)

    assert mapper.map({"active": 1}) == {"Activo": True}
    assert mapper.map({"active": 0}) == {"Activo": False}


def test_map_boolean_field_rejects_arbitrary_int():
    """Boolean type: ints other than 0/1 (e.g. 2) must raise, not silently become True."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="active", target="Activo", type="boolean")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="active"):
        mapper.map({"active": 2})


# ---------------------------------------------------------------------------
# 4. Date coercion
# ---------------------------------------------------------------------------


def test_map_date_field_iso_string_passthrough():
    """Date type: ISO 8601 string passes through unchanged."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="created_at", target="FechaCreación", type="date")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"created_at": "2024-01-15"})

    assert result == {"FechaCreación": "2024-01-15"}


def test_map_date_field_datetime_object_to_iso_string():
    """Date type: datetime object serialized to ISO 8601 date string."""
    from datetime import datetime, timezone
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="updated_at", target="FechaActualización", type="date")]
    mapper = FieldMapper(field_defs)
    dt = datetime(2024, 3, 10, 14, 30, 0, tzinfo=timezone.utc)

    result = mapper.map({"updated_at": dt})

    assert result == {"FechaActualización": "2024-03-10"}


def test_map_date_field_malformed_string_raises():
    """Date type: non-ISO / malformed date string must raise MappingError."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="created_at", target="FechaCreación", type="date")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="created_at"):
        mapper.map({"created_at": "not-a-date"})


def test_map_date_field_invalid_calendar_date_raises():
    """Date type: syntactically ISO-like but invalid calendar date must raise."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="created_at", target="FechaCreación", type="date")]
    mapper = FieldMapper(field_defs)

    # Month 13 does not exist
    with pytest.raises(MappingError, match="created_at"):
        mapper.map({"created_at": "2024-13-01"})


# ---------------------------------------------------------------------------
# 5. Phone normalization to E.164
# ---------------------------------------------------------------------------


def test_map_phone_field_already_e164():
    """Phone type: E.164 formatted phone passes through."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="phone", target="Teléfono", type="phone")]
    mapper = FieldMapper(field_defs)

    result = mapper.map({"phone": "+5491112345678"})

    assert result == {"Teléfono": "+5491112345678"}


def test_map_phone_field_strips_dashes_spaces_parens():
    """Phone type: formatting noise removed and E.164 preserved."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="phone", target="Teléfono", type="phone")]
    mapper = FieldMapper(field_defs)

    # Already has + prefix and only digits after strip
    result = mapper.map({"phone": "+54 9 11 1234-5678"})

    # Should produce normalized E.164
    assert result["Teléfono"].startswith("+")
    assert all(c.isdigit() for c in result["Teléfono"][1:])


def test_map_phone_field_accepts_argentina_e164_format():
    """Phone type: Argentina number already stored as E.164 is accepted."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="phone", target="Teléfono", type="phone")]
    mapper = FieldMapper(field_defs)

    # Phone already stored as E.164 in Qora DB (all leads are stored with +)
    result = mapper.map({"phone": "+541112345678"})

    assert result["Teléfono"] == "+541112345678"


def test_map_phone_field_rejects_non_e164_local_number():
    """Phone type: a local number without '+' country code must be rejected.

    This slice does NOT implement Argentina normalization — non-E.164 input
    must fail loudly rather than be silently 'fixed' with a bare '+' prefix.
    """
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="phone", target="Teléfono", type="phone")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="phone"):
        mapper.map({"phone": "1112345678"})


def test_map_phone_field_rejects_empty_or_plus_only():
    """Phone type: empty or '+'-only strings have no digits and must be rejected."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [CRMFieldDef(source="phone", target="Teléfono", type="phone")]
    mapper = FieldMapper(field_defs)

    with pytest.raises(MappingError, match="phone"):
        mapper.map({"phone": "+"})


def test_normalize_phone_e164_rejects_non_e164():
    """normalize_phone_e164: reject inputs that are not already E.164."""
    from app.integrations.field_mapping import normalize_phone_e164, MappingError

    with pytest.raises(MappingError):
        normalize_phone_e164("1112345678")


def test_normalize_phone_e164_accepts_valid_e164_with_noise():
    """normalize_phone_e164: strip formatting noise from a valid E.164 number."""
    from app.integrations.field_mapping import normalize_phone_e164

    assert normalize_phone_e164("+54 9 11 1234-5678") == "+5491112345678"


# ---------------------------------------------------------------------------
# 6. Required field missing — raises MappingError
# ---------------------------------------------------------------------------


def test_required_field_absent_raises_mapping_error():
    """FM-5: required field missing from lead data raises MappingError."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper, MappingError

    field_defs = [
        CRMFieldDef(source="name", target="Nombre", type="string", required=True),
        CRMFieldDef(source="phone", target="Teléfono", type="phone", required=True),
    ]
    mapper = FieldMapper(field_defs)

    # phone is present but name is absent
    with pytest.raises(MappingError, match="name"):
        mapper.map({"phone": "+5491112345678"})


def test_optional_field_absent_is_omitted_from_output():
    """FM-5: optional field absent from lead data is silently omitted."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [
        CRMFieldDef(source="name", target="Nombre", type="string", required=True),
        CRMFieldDef(source="car_make", target="Marca", type="string", required=False),
    ]
    mapper = FieldMapper(field_defs)

    # car_make absent — should be omitted, not raise
    result = mapper.map({"name": "Carlos"})

    assert result == {"Nombre": "Carlos"}
    assert "Marca" not in result


# ---------------------------------------------------------------------------
# 7. Arbitrary field_map entries (FM-6)
# ---------------------------------------------------------------------------


def test_arbitrary_field_map_entries_all_mapped():
    """FM-6: full set of field mappings produces correct CRM payload."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [
        CRMFieldDef(source="name", target="Nombre", type="string", required=True),
        CRMFieldDef(source="phone", target="Teléfono", type="phone", required=True),
        CRMFieldDef(source="interest_level", target="Interés", type="integer"),
        CRMFieldDef(source="summary_last_call", target="Resumen", type="string"),
        CRMFieldDef(source="status", target="Estado", type="string"),
    ]
    mapper = FieldMapper(field_defs)

    lead_data = {
        "name": "María García",
        "phone": "+5491112345678",
        "interest_level": 8,
        "summary_last_call": "Very interested in auto insurance",
        "status": "interested",
    }

    result = mapper.map(lead_data)

    assert result["Nombre"] == "María García"
    assert result["Teléfono"] == "+5491112345678"
    assert result["Interés"] == 8
    assert result["Resumen"] == "Very interested in auto insurance"
    assert result["Estado"] == "interested"


def test_map_is_pure_same_input_same_output():
    """Mapping is pure: same lead_data always produces same CRM payload."""
    from app.integrations.crm_config import CRMFieldDef
    from app.integrations.field_mapping import FieldMapper

    field_defs = [CRMFieldDef(source="name", target="Nombre", type="string")]
    mapper = FieldMapper(field_defs)
    lead = {"name": "Test"}

    result1 = mapper.map(lead)
    result2 = mapper.map(lead)

    assert result1 == result2 == {"Nombre": "Test"}
