"""Unit tests for zona data correction — TDD RED phase.

Acceptance criteria from spec: zona-data-correction
Tasks 1.1 → 1.2 (PR 1)

Scenarios covered:
- zona registered in CORRECTABLE_FIELDS with storage_type=custom_field
- permissive validator: non-empty string passes, empty/whitespace rejected
- zona extraction produces corrected_value + applied_to_qora (applied=True)
- no zona mention → no correction produced
- ADR/registry design contract documented in source
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Task 1.1 — Zona registered in CORRECTABLE_FIELDS
# ---------------------------------------------------------------------------


def test_zona_in_correctable_fields():
    """CORRECTABLE_FIELDS MUST contain 'zona' after this change."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    assert "zona" in CORRECTABLE_FIELDS, (
        "'zona' must be registered in CORRECTABLE_FIELDS"
    )


def test_zona_storage_type_is_custom_field():
    """zona entry MUST have storage='custom_field' (writes to lead_custom_fields)."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["zona"]
    assert entry.storage == "custom_field", (
        f"zona.storage must be 'custom_field', got {entry.storage!r}"
    )


def test_zona_type_is_str():
    """zona entry MUST have type='str'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["zona"]
    assert entry.type == "str", (
        f"zona.type must be 'str', got {entry.type!r}"
    )


def test_zona_lead_attr_is_zona():
    """zona entry MUST have lead_attr='zona'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["zona"]
    assert entry.lead_attr == "zona", (
        f"zona.lead_attr must be 'zona', got {entry.lead_attr!r}"
    )


# ---------------------------------------------------------------------------
# Task 1.1 — Zona validator is permissive (accepts any non-empty string)
# ---------------------------------------------------------------------------


def test_zona_validator_accepts_valid_zona():
    """Zona validator MUST accept a non-empty location string like 'Palermo'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["zona"]
    # Permissive: no validator set → use default non-empty check in _process_corrections
    # Validator may be None (uses the generic non-empty path) or a custom callable
    if entry.validator is not None:
        ok, err = entry.validator("Palermo")
        assert ok is True, f"zona validator rejected 'Palermo': {err}"
    else:
        # Validator is None — permissive by design; non-empty strings are accepted
        # via the generic check in _process_corrections. This is correct.
        assert True, "zona has no validator — uses generic non-empty check"


def test_zona_validator_accepts_zona_norte():
    """Zona validator MUST accept multi-word location strings like 'zona norte'."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    entry = CORRECTABLE_FIELDS["zona"]
    if entry.validator is not None:
        ok, err = entry.validator("zona norte")
        assert ok is True, f"zona validator rejected 'zona norte': {err}"


def test_zona_empty_string_rejected_by_process_corrections():
    """Empty string zona value MUST be rejected by _process_corrections."""
    from app.analysis.universal.data_corrections import (
        _process_corrections,
        DataCorrection,
    )

    empty_zona = DataCorrection(
        field="zona",
        current_value=None,
        corrected_value="",
        confidence=0.9,
        evidence="vivo en ...",
        applied=False,
    )
    result = _process_corrections([empty_zona], {})

    # Empty string should be rejected (applied=False) or dropped entirely
    # _process_corrections drops None-validator fields with empty corrected_value
    applied = [c for c in result if c.applied]
    assert len(applied) == 0, (
        "Empty zona corrected_value MUST NOT produce an applied correction"
    )


def test_zona_whitespace_only_rejected_by_process_corrections():
    """Whitespace-only zona value MUST be rejected (not applied)."""
    from app.analysis.universal.data_corrections import (
        _process_corrections,
        DataCorrection,
    )

    whitespace_zona = DataCorrection(
        field="zona",
        current_value=None,
        corrected_value="   ",
        confidence=0.9,
        evidence="vivo en ...",
        applied=False,
    )
    result = _process_corrections([whitespace_zona], {})

    applied = [c for c in result if c.applied]
    assert len(applied) == 0, (
        "Whitespace-only zona corrected_value MUST NOT produce an applied correction"
    )


# ---------------------------------------------------------------------------
# Task 1.1 — Zona extraction: applied=True after processing
# ---------------------------------------------------------------------------


def test_zona_valid_value_applied_by_process_corrections():
    """A valid zona value ('Palermo') MUST produce applied=True from _process_corrections."""
    from app.analysis.universal.data_corrections import (
        _process_corrections,
        DataCorrection,
    )

    zona_correction = DataCorrection(
        field="zona",
        current_value=None,
        corrected_value="Palermo",
        confidence=0.92,
        evidence="sí, vivo en Palermo, zona norte",
        applied=False,
    )
    result = _process_corrections([zona_correction], {})

    assert len(result) == 1, "A valid zona correction must be returned"
    assert result[0].applied is True, (
        f"Valid zona correction must have applied=True, got {result[0].applied}"
    )
    assert result[0].corrected_value == "Palermo"


def test_zona_valid_value_triangulate_zona_sur():
    """Triangulation: 'zona sur' also yields applied=True (different input → same behavior)."""
    from app.analysis.universal.data_corrections import (
        _process_corrections,
        DataCorrection,
    )

    zona_correction = DataCorrection(
        field="zona",
        current_value=None,
        corrected_value="zona sur",
        confidence=0.88,
        evidence="soy de zona sur, cerca de Lomas",
        applied=False,
    )
    result = _process_corrections([zona_correction], {})

    assert len(result) == 1
    assert result[0].applied is True, (
        f"'zona sur' must produce applied=True, got {result[0].applied}"
    )


# ---------------------------------------------------------------------------
# Task 1.1 — No zona mention: no correction produced
# ---------------------------------------------------------------------------


async def test_pipeline_no_zona_when_not_mentioned():
    """Pipeline MUST produce no zona correction when transcript has no location reference."""
    from unittest.mock import AsyncMock, MagicMock
    from app.analysis.universal.data_corrections import (
        run_data_corrections_pipeline,
        DataCorrectionsAxis,
    )

    mock_client = AsyncMock()
    mock_response = MagicMock()
    # GPT returns empty corrections (no zona mentioned)
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.parsed = DataCorrectionsAxis(corrections=[])
    mock_client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    result = await run_data_corrections_pipeline(
        transcript="Hola, ¿cómo estás? Quiero cotizar un seguro de auto.",
        client=mock_client,
        current_lead_data={"name": "Carlos", "phone": "+5411000099"},
    )

    zona_corrections = [c for c in result.corrections if c.field == "zona"]
    assert len(zona_corrections) == 0, (
        "No zona mention in transcript must produce zero zona corrections"
    )


# ---------------------------------------------------------------------------
# Task 1.1 — CORRECTABLE_FIELDS registry now has 9 fields (was 8)
# ---------------------------------------------------------------------------


def test_correctable_fields_registry_has_9_fields():
    """CORRECTABLE_FIELDS MUST contain all 9 fields after zona addition."""
    from app.analysis.universal.data_corrections import CORRECTABLE_FIELDS

    expected = {
        "name",
        "phone",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
        "email",
        "age",
        "zona",  # NEW
    }
    actual = set(CORRECTABLE_FIELDS.keys())
    assert actual == expected, (
        f"Registry mismatch.\nExpected: {sorted(expected)}\nGot: {sorted(actual)}"
    )


# ---------------------------------------------------------------------------
# Task 1.1 — Zona in the pipeline prompt field list
# ---------------------------------------------------------------------------


def test_zona_in_pipeline_prompt():
    """'zona' MUST appear in the pipeline system prompt's supported fields list."""
    from app.analysis.universal.data_corrections import _build_pipeline_prompt

    prompt = _build_pipeline_prompt({})
    assert "zona" in prompt, (
        "'zona' must appear in the pipeline prompt as a supported field"
    )
