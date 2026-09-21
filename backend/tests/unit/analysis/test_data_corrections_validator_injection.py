"""Validator injection contract for the data corrections pipeline.

Architecture boundary: ``app/analysis`` must stay copy-pastable into other
runtimes, so it cannot import ``app.phones``. The phone validator therefore
lives outside the package and is injected at the call site.

These tests verify:
- ``app/analysis`` no longer imports ``app.phones`` anywhere.
- Fail-closed default: without an injected validator a ``phone`` correction is
  rejected (``applied=False`` with a rejection reason), never applied blindly.
- Injected validator path: a supplied validator decides ``phone`` corrections —
  valid ones apply, invalid ones are rejected with the validator's reason.
- The summarizer owns the real phones-backed validator and wires it in.
"""

from __future__ import annotations

import ast
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest

ANALYSIS_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app" / "analysis"


# ---------------------------------------------------------------------------
# Boundary: no app.phones import inside app/analysis
# ---------------------------------------------------------------------------


def test_analysis_package_does_not_import_app_phones() -> None:
    """No module under app/analysis may import app.phones.*."""
    offenders: list[str] = []
    for py_file in ANALYSIS_ROOT.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name == "app.phones" or name.startswith("app.phones."):
                    offenders.append(f"{py_file}: {name}")
    assert offenders == [], f"app/analysis must not import app.phones: {offenders}"


# ---------------------------------------------------------------------------
# Fail-closed default for phone
# ---------------------------------------------------------------------------


def test_phone_field_has_no_phones_backed_validator() -> None:
    """The registry phone entry must not expose a phones-backed validator."""
    from app.analysis.universal import data_corrections

    assert not hasattr(
        data_corrections, "_validate_phone"
    ), "_validate_phone must move out of app/analysis (it needs app.phones)"


def test_process_corrections_rejects_phone_without_injected_validator() -> None:
    """Fail-closed: a phone correction is rejected when no validator is injected."""
    from app.analysis.universal.data_corrections import (
        DataCorrection,
        _process_corrections,
    )

    result = _process_corrections(
        [
            DataCorrection(
                field="phone",
                current_value="+5491155550101",
                corrected_value="011 15 5555-0101",
                confidence=0.9,
                evidence="Synthetic correction",
            )
        ],
        {"phone": "+5491155550101"},
    )

    assert len(result) == 1
    assert result[0].applied is False, "phone must fail closed without a validator"
    assert result[0].rejection_reason, "rejection_reason must explain the refusal"


@pytest.mark.asyncio
async def test_pipeline_rejects_phone_without_injected_validator() -> None:
    """The pipeline fails closed on phone corrections when no validator is passed."""
    from app.analysis.universal import data_corrections

    correction = data_corrections.DataCorrection(
        field="phone",
        current_value="+5491155550101",
        corrected_value="011 15 5555-0101",
        confidence=0.9,
        evidence="Synthetic correction",
    )
    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = data_corrections.DataCorrectionsAxis(
        corrections=[correction]
    )
    client.beta.chat.completions.parse.return_value = response

    result = await data_corrections.run_data_corrections_pipeline(
        "Synthetic transcript",
        client,
        current_lead_data={"phone": "+5491155550101"},
    )

    assert len(result.corrections) == 1
    assert result.corrections[0].applied is False
    assert result.corrections[0].rejection_reason


# ---------------------------------------------------------------------------
# Injected validator path
# ---------------------------------------------------------------------------


def test_process_corrections_uses_injected_validator_to_accept() -> None:
    """An injected validator that accepts makes the phone correction apply."""
    from app.analysis.universal.data_corrections import (
        DataCorrection,
        _process_corrections,
    )

    result = _process_corrections(
        [
            DataCorrection(
                field="phone",
                current_value="+5491155550101",
                corrected_value="011 15 5555-0102",
                confidence=0.9,
                evidence="Synthetic correction",
            )
        ],
        {"phone": "+5491155550101"},
        validators={"phone": lambda value: (True, None)},
    )

    assert result[0].applied is True
    assert result[0].rejection_reason is None


def test_process_corrections_uses_injected_validator_to_reject() -> None:
    """An injected validator that rejects propagates its reason verbatim."""
    from app.analysis.universal.data_corrections import (
        DataCorrection,
        _process_corrections,
    )

    result = _process_corrections(
        [
            DataCorrection(
                field="phone",
                current_value="+5491155550101",
                corrected_value="011 5555-0101",
                confidence=0.9,
                evidence="Synthetic correction",
            )
        ],
        {"phone": "+5491155550101"},
        validators={"phone": lambda value: (False, "ambiguous_or_incomplete")},
    )

    assert result[0].applied is False
    assert result[0].rejection_reason == "ambiguous_or_incomplete"


@pytest.mark.asyncio
async def test_pipeline_forwards_injected_validators() -> None:
    """run_data_corrections_pipeline forwards validators to the processing step."""
    from app.analysis.universal import data_corrections

    correction = data_corrections.DataCorrection(
        field="phone",
        current_value="+5491155550101",
        corrected_value="011 15 5555-0102",
        confidence=0.9,
        evidence="Synthetic correction",
    )
    client = AsyncMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = data_corrections.DataCorrectionsAxis(
        corrections=[correction]
    )
    client.beta.chat.completions.parse.return_value = response

    result = await data_corrections.run_data_corrections_pipeline(
        "Synthetic transcript",
        client,
        current_lead_data={"phone": "+5491155550101"},
        validators={"phone": lambda value: (True, None)},
    )

    assert result.corrections[0].applied is True


def test_injected_validator_does_not_affect_other_fields() -> None:
    """A phone override leaves other fields on their registry validators."""
    from app.analysis.universal.data_corrections import (
        DataCorrection,
        _process_corrections,
    )

    result = _process_corrections(
        [
            DataCorrection(
                field="email",
                current_value=None,
                corrected_value="not-an-email",
                confidence=0.9,
                evidence="Synthetic correction",
            )
        ],
        {},
        validators={"phone": lambda value: (True, None)},
    )

    assert result[0].applied is False
    assert result[0].rejection_reason


# ---------------------------------------------------------------------------
# Injected normalizer path (canonical value + format-insensitive idempotency)
# ---------------------------------------------------------------------------


def test_injected_normalizer_canonicalizes_applied_value() -> None:
    """An injected normalizer rewrites the stored value to its canonical form."""
    from app.analysis.universal.data_corrections import (
        DataCorrection,
        _process_corrections,
    )

    result = _process_corrections(
        [
            DataCorrection(
                field="phone",
                current_value="+5491155550101",
                corrected_value="0341 15 555-0101",
                confidence=0.9,
                evidence="Synthetic correction",
            )
        ],
        {"phone": "+5491155550101"},
        validators={"phone": lambda value: (True, None)},
        normalizers={"phone": lambda value: "+5493415550101"},
    )

    assert result[0].applied is True
    assert result[0].corrected_value == "+5493415550101"


def test_injected_normalizer_runs_before_idempotency_gate() -> None:
    """A restated value in another format is dropped once normalized."""
    from app.analysis.universal.data_corrections import (
        DataCorrection,
        _process_corrections,
    )

    result = _process_corrections(
        [
            DataCorrection(
                field="phone",
                current_value="+5491155550101",
                corrected_value="011 15 5555-0101",
                confidence=0.9,
                evidence="Synthetic correction",
            )
        ],
        {"phone": "+5491155550101"},
        validators={"phone": lambda value: (True, None)},
        normalizers={"phone": lambda value: "+5491155550101"},
    )

    assert result == [], "a normalized no-op correction must be dropped"


# ---------------------------------------------------------------------------
# The real validator lives in the summarizer and is wired at the call site
# ---------------------------------------------------------------------------


def test_summarizer_exposes_phones_backed_phone_validator() -> None:
    """The real phone validator lives in app.summarizer, where app.phones is legal."""
    from app.summarizer import validate_phone_correction

    ok, reason = validate_phone_correction("011 15 5555-0101")
    assert ok is True
    assert reason is None

    ok, reason = validate_phone_correction("011 5555-0101")
    assert ok is False
    assert reason == "ambiguous_or_incomplete"

    ok, reason = validate_phone_correction("12345")
    assert ok is False
    assert reason


def test_summarizer_registers_phone_in_data_correction_validators() -> None:
    """The summarizer's validator map wires phone to the real validator."""
    from app.summarizer import DATA_CORRECTION_VALIDATORS, validate_phone_correction

    assert DATA_CORRECTION_VALIDATORS["phone"] is validate_phone_correction


def test_summarizer_phone_normalizer_canonicalizes_or_passes_through() -> None:
    """The summarizer's phone normalizer never raises on an invalid value."""
    from app.summarizer import DATA_CORRECTION_NORMALIZERS, normalize_phone_correction

    assert DATA_CORRECTION_NORMALIZERS["phone"] is normalize_phone_correction
    assert normalize_phone_correction("011 15 5555-0101") == "+5491155550101"
    # Unnormalizable input is returned untouched so the validator can reject it.
    assert normalize_phone_correction("12345") == "12345"
