"""Data corrections pipeline — structured correction engine.

qora-data-corrections: Replaces the string-extraction DataCorrectionsAxis with
a standalone, structured correction engine. GPT extracts corrections from the
transcript; a confidence gate (disabled, threshold=0.0) determines application.

Exports:
- DataCorrection       — individual structured correction item
- DataCorrectionsAxis  — pipeline result (list of DataCorrection)
- CorrectableField     — registry entry dataclass
- CORRECTABLE_FIELDS   — registry dict (8 allowed fields)
- coerce_value         — type coercion helper (pure function)
- _validate_phone      — per-field validator
- _validate_car_year   — per-field validator
- _validate_name       — per-field validator
- _validate_email      — per-field validator
- _validate_age        — per-field validator
- run_data_corrections_pipeline — async standalone pipeline
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

import logging

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence gate — DISABLED (threshold=0.0 means all corrections auto-apply)
# FUTURE: enable when client approval flow exists (set to 0.8).
# ---------------------------------------------------------------------------
_CONFIDENCE_THRESHOLD = 0.0  # TODO: set to 0.8 when client approval flow exists


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class DataCorrection(BaseModel):
    """A single structured correction to a lead's personal data.

    GPT returns a list of these; the pipeline validates and sets `applied`.
    `rejection_reason` is populated (non-None) when `applied=False` due to
    validation failure or idempotency. It is always None for applied=True items.
    """

    field: str
    current_value: str | None = None
    corrected_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str
    applied: bool = False
    rejection_reason: str | None = None


class DataCorrectionsAxis(BaseModel):
    """Pipeline result: list of structured DataCorrection items.

    GPT returns this as structured output; post-processing sets applied flags.
    """

    corrections: list[DataCorrection] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-field validators  (pure functions: return (ok: bool, error: str | None))
# ---------------------------------------------------------------------------


def _validate_phone(value: str) -> tuple[bool, str | None]:
    """Phone: E.164 or normalized 10-digit format."""
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 10:
        return True, None
    return False, f"Phone '{value}' has fewer than 10 digits (got {len(digits)})"


def _extract_int(value: str) -> int | None:
    """Extract the first integer from free text like '30 años' or '2019 aprox'.

    Returns None if no digit sequence is present (e.g. 'treinta'). Never raises.
    """
    if value is None:
        return None
    match = re.search(r"-?\d+", str(value))
    return int(match.group()) if match else None


def _validate_car_year(value: str) -> tuple[bool, str | None]:
    """Car year: integer in range 1900–2030, extracted from free text."""
    year = _extract_int(value)
    if year is None:
        return False, f"Car year '{value}' has no parseable number"
    if year < 1900:
        return False, f"Car year {year} is before 1900"
    if year > 2030:
        return False, f"Car year {year} is after 2030"
    return True, None


def _validate_name(value: str) -> tuple[bool, str | None]:
    """Name: non-empty string after stripping whitespace."""
    if not value or not value.strip():
        return False, "Name cannot be empty or whitespace-only"
    return True, None


def _validate_email(value: str) -> tuple[bool, str | None]:
    """Email: minimal RFC 5322 check — must contain '@' and a non-empty domain."""
    if "@" not in value:
        return False, f"Email '{value}' missing '@'"
    local, _, domain = value.partition("@")
    if not domain or "." not in domain:
        return False, f"Email '{value}' has invalid domain"
    return True, None


def _validate_age(value: str) -> tuple[bool, str | None]:
    """Age: integer in range 1–120, extracted from free text like '30 años'."""
    age = _extract_int(value)
    if age is None:
        return False, f"Age '{value}' has no parseable number"
    if age < 1:
        return False, f"Age {age} is less than 1"
    if age > 120:
        return False, f"Age {age} is greater than 120"
    return True, None


# ---------------------------------------------------------------------------
# Type coercion helper (pure function)
# ---------------------------------------------------------------------------


def coerce_value(value: str, type_: str) -> int | float | str:
    """Coerce a string value to the target type.

    Args:
        value: Raw string value from GPT.
        type_: One of 'str', 'int', 'float'.

    Returns:
        Coerced value.

    Raises:
        ValueError: If coercion fails.
    """
    if type_ == "int":
        parsed = _extract_int(value)
        if parsed is None:
            raise ValueError(f"cannot extract int from {value!r}")
        return parsed
    if type_ == "float":
        return float(value)
    return str(value)


# ---------------------------------------------------------------------------
# Correctable fields registry
# ---------------------------------------------------------------------------


@dataclass
class CorrectableField:
    """Registry entry for a correctable lead field.

    Attributes:
        lead_attr:  SQLAlchemy column name on Lead model.
        type:       Target Python type ('str', 'int', 'float').
        crm_field:  Reserved for future CRM sync mapping (None today).
        validator:  Optional per-field validation callable.
    """

    lead_attr: str
    type: str
    crm_field: str | None
    validator: Callable[[str], tuple[bool, str | None]] | None = None


# Registry — hardcoded today, designed to be per-client configurable in future.
# CRM_FUTURE: populate crm_field per client when CRM sync activates.
CORRECTABLE_FIELDS: dict[str, CorrectableField] = {
    "name": CorrectableField(
        lead_attr="name",
        type="str",
        crm_field=None,
        validator=_validate_name,
    ),
    "phone": CorrectableField(
        lead_attr="phone",
        type="str",
        crm_field=None,
        validator=_validate_phone,
    ),
    "email": CorrectableField(
        lead_attr="email",
        type="str",
        crm_field=None,
        validator=_validate_email,
    ),
    "age": CorrectableField(
        lead_attr="age",
        type="int",
        crm_field=None,
        validator=_validate_age,
    ),
    "car_make": CorrectableField(
        lead_attr="car_make",
        type="str",
        crm_field=None,
        validator=None,
    ),
    "car_model": CorrectableField(
        lead_attr="car_model",
        type="str",
        crm_field=None,
        validator=None,
    ),
    "car_year": CorrectableField(
        lead_attr="car_year",
        type="int",
        crm_field=None,
        validator=_validate_car_year,
    ),
    "current_insurance": CorrectableField(
        lead_attr="current_insurance",
        type="str",
        crm_field=None,
        validator=None,
    ),
}

# ---------------------------------------------------------------------------
# Backward-compat DIMENSION stub (still referenced by DIMENSION_MODULES import)
# data_corrections is kept in DIMENSION_MODULES for the string-based fallback
# dimension. The new structured pipeline is invoked separately by the summarizer.
# ---------------------------------------------------------------------------


class _DataCorrectionsLegacyAxis(BaseModel):
    """Legacy string-based schema for DIMENSION_MODULES compatibility.

    Phase 4 removes data_corrections from DIMENSION_MODULES entirely.
    Until then, this keeps PostCallAnalysis.data_corrections: str valid.
    """

    corrections: str = Field(
        default="",
        description="Legacy string field. Now empty — use run_data_corrections_pipeline instead.",
    )


DIMENSION = {
    "name": "data_corrections",
    "display_name": "Data Corrections",
    "schema": _DataCorrectionsLegacyAxis,
    "target_field": "data_corrections",
    "prompt": (
        "Return JSON with: corrections (empty string '').  "
        "Data corrections are now handled by a separate pipeline."
    ),
    "model": "gpt-4o-mini",
}


async def analyze(transcript: str, client: AsyncOpenAI) -> str:
    """Run the DIMENSION_MODULES-compatible analyze coroutine.

    Returns an empty string for backward compat with PostCallAnalysis.data_corrections: str.
    The new structured pipeline (run_data_corrections_pipeline) is called separately
    by the summarizer with full lead context — this dimension stub exists only to keep
    DIMENSION_MODULES intact during the transition (Phase 4 removes it).
    """
    # NOTE: This stub returns "" because Phase 4 removes data_corrections from
    # DIMENSION_MODULES entirely. Until then, the new pipeline handles corrections.
    return ""


# ---------------------------------------------------------------------------
# Pipeline system prompt
# ---------------------------------------------------------------------------

_PIPELINE_SYSTEM_PROMPT = """\
You are an expert at detecting personal data corrections from sales call transcripts.

GOAL: Identify any field corrections the lead explicitly stated during the call.
Supported fields: {field_list}

CURRENT LEAD DATA (for comparison):
{lead_snapshot}

RULES:
- Only return corrections where the lead EXPLICITLY stated a different value.
- Do NOT infer or guess — only report what was clearly said.
- `current_value` is the existing value from the lead record (may be null).
- `corrected_value` is the new value the lead stated.
- `evidence` MUST be a verbatim quote or close paraphrase from the transcript.
- `confidence` is your certainty that this is a real correction (0.0–1.0).
- Return an empty corrections list if no explicit corrections were made.

CAR MAKE vs CAR MODEL — CRITICAL DISTINCTION:
- `car_make` is the BRAND/MANUFACTURER (e.g. Volkswagen, Toyota, Ford, Chevrolet, Fiat, Renault).
- `car_model` is the SPECIFIC MODEL within that brand (e.g. Polo, Corolla, Ranger, Cruze, Cronos).
- When the lead says a single word like "Polo", "Corolla", "Cruze", "Cronos", "Hilux", "Ranger",
  "Gol", "Onix", "Tracker", "Argo", "Duster", "Sandero", "Kicks" — that is a MODEL, not a make.
- If the lead says only a model name and car_make is null, infer the correct make from the model.
  Common examples: Polo/Gol/Vento/Amarok → Volkswagen, Corolla/Hilux/Etios → Toyota,
  Cruze/Onix/Tracker → Chevrolet, Cronos/Argo/Toro → Fiat, Ranger/EcoSport/Ka → Ford,
  Sandero/Duster/Kwid → Renault, 208/2008/308 → Peugeot.
- If car_model is null but car_make contains a model name (misclassification), correct BOTH fields:
  set car_model to the model name and car_make to the correct brand.
- NEVER put a model name in car_make or a brand name in car_model.
"""


def _build_pipeline_prompt(current_lead_data: dict) -> str:
    """Build the system prompt with current lead snapshot and field allowlist."""
    import json

    field_list = ", ".join(sorted(CORRECTABLE_FIELDS.keys()))

    # Build a clean snapshot of correctable fields only
    snapshot = {
        k: current_lead_data.get(v.lead_attr, current_lead_data.get(k))
        for k, v in CORRECTABLE_FIELDS.items()
    }
    # Filter out keys not in current_lead_data to avoid noise
    snapshot_clean = {k: v for k, v in snapshot.items() if v is not None}

    lead_snapshot = (
        json.dumps(snapshot_clean, ensure_ascii=False, indent=2)
        if snapshot_clean
        else "{}"
    )

    return _PIPELINE_SYSTEM_PROMPT.format(
        field_list=field_list,
        lead_snapshot=lead_snapshot,
    )


# ---------------------------------------------------------------------------
# Post-processing: validate, idempotency, confidence gate
# ---------------------------------------------------------------------------


def _process_corrections(
    raw_corrections: list[DataCorrection],
    current_lead_data: dict,
) -> list[DataCorrection]:
    """Apply idempotency, registry lookup, validation, and confidence gate.

    Steps per correction:
    1. Registry lookup — drop unknown fields (silently).
    2. Idempotency — drop if corrected_value == current_value (case-insensitive for str).
    3. Per-field validation — set applied=False on invalid values.
    4. Confidence gate — DISABLED (threshold=0.0, all corrections auto-apply).
       FUTURE: set applied=False when confidence < 0.8.

    Returns:
        Filtered and annotated list of DataCorrection items.
    """
    processed: list[DataCorrection] = []

    for correction in raw_corrections:
        field = correction.field

        # 1. Registry lookup — reject unknown fields
        if field not in CORRECTABLE_FIELDS:
            logger.debug(
                "data_corrections_unknown_field_dropped field=%s corrected_value=%s",
                field,
                correction.corrected_value,
            )
            continue

        entry = CORRECTABLE_FIELDS[field]

        # 2. Idempotency gate — drop if corrected == current (case-insensitive for strings)
        lead_attr = entry.lead_attr
        current_value = current_lead_data.get(lead_attr, current_lead_data.get(field))

        if current_value is not None and correction.corrected_value is not None:
            current_str = str(current_value).strip().lower()
            corrected_str = correction.corrected_value.strip().lower()
            if current_str == corrected_str:
                logger.debug(
                    "data_corrections_idempotency_skip field=%s value=%s",
                    field,
                    current_value,
                )
                continue  # Same value — drop entirely

        # 3. Per-field validation
        validator = entry.validator
        applied = True
        rejection_reason: str | None = None
        if validator is not None:
            ok, error_msg = validator(correction.corrected_value)
            if not ok:
                applied = False
                rejection_reason = error_msg
                logger.info(
                    "data_corrections_validation_failed field=%s corrected_value=%s error=%s",
                    field,
                    correction.corrected_value,
                    error_msg,
                )
        else:
            # Fields without validators: non-empty string value required
            if (
                not correction.corrected_value
                or not str(correction.corrected_value).strip()
            ):
                applied = False
                rejection_reason = "corrected_value is empty or whitespace-only"

        # 4. Confidence gate — DISABLED (threshold=0.0)
        # FUTURE: enable when client approval flow exists
        # if correction.confidence < _CONFIDENCE_THRESHOLD:
        #     applied = False

        processed.append(
            DataCorrection(
                field=field,
                current_value=correction.current_value,
                corrected_value=correction.corrected_value,
                confidence=correction.confidence,
                evidence=correction.evidence,
                applied=applied,
                rejection_reason=rejection_reason,
            )
        )

    return processed


# ---------------------------------------------------------------------------
# Standalone async pipeline
# ---------------------------------------------------------------------------


async def run_data_corrections_pipeline(
    transcript: str,
    client: AsyncOpenAI,
    *,
    current_lead_data: dict | None = None,
    previous_corrections: list[dict] | None = None,
    client_config: dict | None = None,
) -> DataCorrectionsAxis:
    """Standalone async data corrections pipeline.

    Following the profile_facts pattern: receives transcript + current lead
    snapshot → returns structured DataCorrectionsAxis with validated corrections.

    Args:
        transcript: The call transcript text.
        client: AsyncOpenAI client instance.
        current_lead_data: Snapshot of correctable lead fields for comparison.
            Keys can be field names (e.g. 'name') or lead_attr names (e.g. 'car_make').
        previous_corrections: Prior correction records for context (not used today).
        client_config: Per-client configuration (reserved for future registry override).

    Returns:
        DataCorrectionsAxis with validated, idempotency-filtered corrections.
        Never raises — returns empty axis on any failure.
    """
    lead_data = current_lead_data or {}

    try:
        system_prompt = _build_pipeline_prompt(lead_data)

        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            response_format=DataCorrectionsAxis,
        )

        raw_axis: DataCorrectionsAxis | None = response.choices[0].message.parsed
        if raw_axis is None:
            return DataCorrectionsAxis()

        processed = _process_corrections(raw_axis.corrections, lead_data)
        return DataCorrectionsAxis(corrections=processed)

    except Exception as exc:
        logger.warning(
            "data_corrections_pipeline_exception error=%s error_type=%s",
            str(exc),
            type(exc).__name__,
        )
        return DataCorrectionsAxis()
