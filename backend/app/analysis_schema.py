"""QORA — Post-call analysis schema (Phase 5, Issue #7; Enhanced extraction Issue #35).

Self-contained module: only imports pydantic + enum + re + functools.
NO app dependencies (no FastAPI, no SQLAlchemy, no structlog, no app.*).

This module is the N8N migration boundary. When migrating to N8N:
- Copy this file + ANALYSIS_SYSTEM_PROMPT to the N8N webhook handler.
- Remove from this codebase.
- The webhook receives transcript text, calls OpenAI with PostCallAnalysis
  as response_format, and returns JSON.

Owned here:
- OutcomeClassification, EngagementQuality, Urgency enums
- CallOutcome, DetectedInterests, IdentifiedProblem axis models
- 4 new universal axis models: ServiceIssuesAxis, ProfileFactsAxis,
  CommitmentSignalsAxis, AbandonmentReasonAxis
- PostCallAnalysis root model (existing 6 fields + 3 Phase5 axes + 4 new axes)
- ExtractionConfig + AxisFieldDef (per-client extraction configuration)
- build_analysis_model() factory (dynamic model via pydantic.create_model())
- build_system_prompt() builder (generic prompt, replaces insurance-specific one)
- ANALYSIS_SYSTEM_PROMPT (deprecated alias — kept for backward compat / N8N)
"""

from __future__ import annotations

import re
from collections import OrderedDict
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator, AliasChoices


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OutcomeClassification(str, Enum):
    """Semantic classification of the call outcome."""

    interested = "interested"
    not_interested = "not_interested"
    busy = "busy"
    follow_up = "follow_up"
    no_answer = "no_answer"
    hostile = "hostile"
    confused = "confused"


class EngagementQuality(str, Enum):
    """How actively the lead participated in the conversation."""

    high = "high"
    medium = "medium"
    low = "low"
    none = "none"


class Urgency(str, Enum):
    """How urgently the lead needs the product."""

    high = "high"
    medium = "medium"
    low = "low"


# ---------------------------------------------------------------------------
# Axis 1: Call Outcome
# ---------------------------------------------------------------------------


class CallOutcome(BaseModel):
    """Semantic classification of a call's result and lead engagement."""

    classification: OutcomeClassification = Field(
        description="Overall call result: interested, not_interested, busy, follow_up, no_answer, hostile, confused"
    )
    reason: str = Field(
        description="One sentence explaining WHY this classification was chosen"
    )
    engagement_quality: EngagementQuality = Field(
        description="How actively the lead participated: high, medium, low, none"
    )


# ---------------------------------------------------------------------------
# Axis 2: Detected Interests
# ---------------------------------------------------------------------------


class DetectedInterests(BaseModel):
    """Insurance products and needs the lead expressed interest in."""

    products: list[str] = Field(
        default_factory=list,
        description=(
            "Insurance products mentioned or inquired about: "
            "todo_riesgo, terceros_completo, terceros, vida, hogar, etc."
        ),
    )
    specific_needs: list[str] = Field(
        default_factory=list,
        description=(
            "Specific requirements the lead expressed: "
            "precio_competitivo, cobertura_amplia, atencion_personalizada, etc."
        ),
    )
    buying_signals: list[str] = Field(
        default_factory=list,
        description=(
            "Concrete buying signals observed: "
            "asked about price, comparing quotes, has a specific deadline, etc."
        ),
    )


# ---------------------------------------------------------------------------
# Axis 3: Identified Problem
# ---------------------------------------------------------------------------


class IdentifiedProblem(BaseModel):
    """The underlying need or problem driving the lead's potential purchase."""

    primary_need: str = Field(
        description="One sentence — what the lead actually needs (not just what they said)"
    )
    pain_points: list[str] = Field(
        default_factory=list,
        description="Current pain points driving the lead's interest in insurance",
    )
    urgency: Urgency = Field(
        description="How urgently the lead needs the product: high, medium, low"
    )


# ---------------------------------------------------------------------------
# Issue #35 — 4 new universal axis models
# ---------------------------------------------------------------------------


class ServiceIssuesAxis(BaseModel):
    """Service problems or complaints the lead mentioned during the call."""

    issues: list[str] = Field(
        default_factory=list,
        description="Service problems or complaints mentioned by the lead",
    )


class ProfileFactsAxis(BaseModel):
    """Personal or professional facts about the lead revealed during the call."""

    facts: list[str] = Field(
        default_factory=list,
        description="Personal/professional facts about the lead revealed during the call",
    )


class CommitmentSignalsAxis(BaseModel):
    """Verbal commitments or intent signals from the lead."""

    signals: list[str] = Field(
        default_factory=list,
        description="Verbal commitments or intent signals expressed by the lead",
    )


class AbandonmentReasonAxis(BaseModel):
    """Why the lead disengaged or wants to stop, if applicable."""

    reason: str | None = Field(
        default=None,
        description="Why the lead disengaged or wants to stop, if applicable",
    )


# ---------------------------------------------------------------------------
# Issue #35 — ExtractionConfig + AxisFieldDef (per-client extraction config)
# ---------------------------------------------------------------------------

# Known base axis names (used for collision and disabled_axes validation)
_BASE_AXIS_NAMES: frozenset[str] = frozenset(
    {
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    }
)

# All top-level PostCallAnalysis field names (used for collision detection)
_BASE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "summary",
        "objections",
        "interest_level",
        "current_insurance",
        "next_action_suggested",
        "misc_notes",
        "data_corrections",
        "call_outcome",
        "detected_interests",
        "identified_problem",
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    }
)

_KNOWN_BASE_AXES: frozenset[str] = _BASE_AXIS_NAMES

_AXIS_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

_ALLOWED_FIELD_TYPES: frozenset[str] = frozenset({"str", "list[str]", "int"})


class AxisFieldDef(BaseModel):
    """Definition of a single client-specific extra axis field.

    Used in ExtractionConfig.extra_axes to define per-client extraction extensions.
    Only OpenAI-safe scalar types are permitted to ensure JSON Schema compatibility.
    """

    name: str = Field(description="Field name — snake_case, ^[a-z][a-z0-9_]{1,30}$")
    field_type: Literal["str", "list[str]", "int"] = Field(
        description="Python type for this axis field — one of: str, list[str], int"
    )
    description: str = Field(
        description="Human-readable description passed to Field(description=...)"
    )

    @field_validator("name")
    @classmethod
    def name_must_be_snake_case(cls, v: str) -> str:
        if not _AXIS_NAME_RE.match(v):
            raise ValueError(
                f"AxisFieldDef.name must match ^[a-z][a-z0-9_]{{1,30}}$, got: {v!r}"
            )
        return v


class ExtractionConfig(BaseModel):
    """Per-client extraction configuration stored as JSON in Client.extraction_config.

    Validates and carries settings for the per-call extraction pipeline:
    - disabled_axes: base axes to skip (must be in _KNOWN_BASE_AXES)
    - extra_axes: client-specific additional fields (max 10, no name collision)
    - prompt_addendum: text appended after axis instructions in the system prompt
    """

    disabled_axes: list[str] = Field(
        default_factory=list,
        description="Base axis names to skip (subset of known base axes)",
    )
    extra_axes: list[AxisFieldDef] = Field(
        default_factory=list,
        description="Client-specific additional axes (max 10)",
    )
    prompt_addendum: str = Field(
        default="",
        description="Appended after axis instructions in the generated system prompt",
        validation_alias=AliasChoices("prompt_addendum", "context_description"),
    )

    @property
    def context_description(self) -> str:
        """Alias for prompt_addendum — forward-compat with spec field name."""
        return self.prompt_addendum

    @field_validator("disabled_axes")
    @classmethod
    def disabled_axes_must_be_known(cls, v: list[str]) -> list[str]:
        unknown = set(v) - _KNOWN_BASE_AXES
        if unknown:
            raise ValueError(
                f"disabled_axes references unknown axis names: {sorted(unknown)}. "
                f"Known axes: {sorted(_KNOWN_BASE_AXES)}"
            )
        return v

    @model_validator(mode="after")
    def validate_extra_axes(self) -> "ExtractionConfig":
        if len(self.extra_axes) > 10:
            raise ValueError(
                f"extra_axes may not have more than 10 entries, got {len(self.extra_axes)}"
            )
        for ax in self.extra_axes:
            if ax.name in _BASE_FIELD_NAMES:
                raise ValueError(
                    f"extra_axes name {ax.name!r} collides with a base PostCallAnalysis field. "
                    "Choose a different name."
                )
        return self


# ---------------------------------------------------------------------------
# Root schema — existing 6 fields + 3 new Phase 5 axes
# ---------------------------------------------------------------------------


class PostCallAnalysis(BaseModel):
    """Complete post-call analysis output.

    Used as response_format for OpenAI Structured Outputs
    (client.chat.completions.parse(response_format=PostCallAnalysis)).

    The summarizer imports this model and uses it as the response schema.
    """

    # ---- Existing fields (Phase 2 / CAP-4) ----

    summary: str = Field(
        description="Concise call summary, max 150 tokens, plain language"
    )
    objections: list[str] = Field(
        default_factory=list,
        description="Objections the lead raised during the call",
    )
    interest_level: int = Field(
        description="0-100 estimated interest level: 0 = completely uninterested, 100 = ready to buy"
    )
    current_insurance: str | None = Field(
        default=None,
        description="Current insurance carrier if the lead mentioned it, or null",
    )
    next_action_suggested: str = Field(
        description="One of: call_again, send_quote, wait, do_not_call"
    )
    misc_notes: str = Field(
        default="",
        description="Any other relevant facts or observations not covered by the structured fields above, as a brief text note",
    )

    # ---- Issue #21: data correction tracking (str NOT dict — OpenAI Structured Outputs) ----

    data_corrections: str = Field(
        default="",
        description=(
            "If the lead corrected any personal data during the call "
            "(car make, car model, car year, name, phone), list each correction "
            "as 'field_name: corrected_value' on a separate line. "
            "Example: 'car_model: Polo Trend\\ncar_year: 2022'. "
            "Empty string if no corrections were made."
        ),
    )

    # ---- New Phase 5 axes ----

    call_outcome: CallOutcome = Field(
        description="Semantic classification of the call result and lead engagement quality"
    )
    detected_interests: DetectedInterests = Field(
        description="Insurance products, specific needs, and buying signals detected in the transcript"
    )
    identified_problem: IdentifiedProblem = Field(
        description="The underlying need or problem driving the lead's potential purchase"
    )

    # ---- Issue #35 — 4 new universal axes ----

    service_issues: ServiceIssuesAxis = Field(
        default_factory=ServiceIssuesAxis,
        description="Service problems or complaints the lead mentioned",
    )
    profile_facts: ProfileFactsAxis = Field(
        default_factory=ProfileFactsAxis,
        description="Personal or professional facts about the lead revealed during the call",
    )
    commitment_signals: CommitmentSignalsAxis = Field(
        default_factory=CommitmentSignalsAxis,
        description="Verbal commitments or intent signals expressed by the lead",
    )
    abandonment_reason: AbandonmentReasonAxis = Field(
        default_factory=AbandonmentReasonAxis,
        description="Why the lead disengaged or wants to stop, if applicable",
    )


# ---------------------------------------------------------------------------
# System prompt — co-located for N8N portability
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT: str = """\
You are an expert insurance sales call analyst. You receive a transcript from \
an insurance sales call (Quintana Seguros — Argentine auto insurance broker) \
and must return a structured JSON analysis.

Analyze the call and extract ALL of the following fields:

EXISTING FIELDS:
- summary: Concise plain-language summary of the call (max 150 tokens)
- objections: List of objections or hesitations the lead raised
- interest_level: Integer 0-100 (0 = completely uninterested, 100 = ready to buy immediately)
- current_insurance: Current carrier if mentioned, otherwise null
- next_action_suggested: One of: call_again, send_quote, wait, do_not_call
- misc_notes: Any other relevant facts as a brief text note (empty string if nothing extra)

NEW ANALYSIS AXES:
- call_outcome: Structured outcome classification
  - classification: One of: interested, not_interested, busy, follow_up, no_answer, hostile, confused
  - reason: One sentence explaining WHY this classification applies
  - engagement_quality: One of: high, medium, low, none

- detected_interests: What the lead was interested in
  - products: Insurance products mentioned (todo_riesgo, terceros_completo, terceros, vida, hogar, etc.)
  - specific_needs: Requirements expressed (precio_competitivo, cobertura_amplia, etc.)
  - buying_signals: Concrete indicators of purchase intent

- identified_problem: The underlying need driving interest
  - primary_need: One sentence — what the lead actually needs
  - pain_points: Current pain points motivating their interest
  - urgency: One of: high, medium, low

NEW FIELD — data_corrections:
- data_corrections: If the lead explicitly corrected factual data (car model, car make,
  car year, name, phone), record each correction as 'field_name: corrected_value' on a
  separate line. Example: 'car_model: Polo Trend\\ncar_year: 2022'.
  Use empty string "" if no corrections were made.

UNIVERSAL AXES (Issue #35):
- service_issues: Service problems or complaints the lead mentioned
  - issues: List of service problems or complaints mentioned

- profile_facts: Personal or professional facts about the lead
  - facts: List of personal/professional facts revealed during the call

- commitment_signals: Verbal commitments or intent signals from the lead
  - signals: List of verbal commitments or intent signals

- abandonment_reason: Why the lead disengaged, if applicable
  - reason: String explaining why the lead disengaged, or null

RULES:
- next_action_suggested = "do_not_call" ONLY if lead explicitly asked not to be called again
- interest_level: base it on enthusiasm, engagement, and stated intent
- call_outcome.classification = "no_answer" if the call never connected
- call_outcome.engagement_quality = "none" if the lead said nothing meaningful
- detected_interests fields default to empty lists if nothing was detected
- identified_problem.pain_points defaults to empty list if unclear
- service_issues.issues defaults to empty list if no issues mentioned
- profile_facts.facts defaults to empty list if no facts revealed
- commitment_signals.signals defaults to empty list if no signals
- abandonment_reason.reason is null if lead did not disengage
- Always return valid JSON matching the schema exactly
"""


# ---------------------------------------------------------------------------
# Issue #35 — Dynamic model builder + system prompt builder
# ---------------------------------------------------------------------------

# Python type map for extra_axes field_type → (annotation, default_factory/default)
_FIELD_TYPE_MAP: dict[str, type] = {
    "str": str,
    "list[str]": list,
    "int": int,
}


def _config_cache_key(config: ExtractionConfig) -> str:
    """Stable string key for caching based on config content."""
    import json as _json

    return _json.dumps(
        {
            "disabled_axes": sorted(config.disabled_axes),
            "extra_axes": [
                {
                    "name": ax.name,
                    "field_type": ax.field_type,
                    "description": ax.description,
                }
                for ax in sorted(config.extra_axes, key=lambda x: x.name)
            ],
            "prompt_addendum": config.prompt_addendum,
        },
        sort_keys=True,
    )


def _make_model_for_config(config: "ExtractionConfig") -> type[BaseModel]:
    """Build the Pydantic model for the given ExtractionConfig.

    Starts from PostCallAnalysis fields, removes disabled axes, adds extra_axes_data
    when client extra axes are present.
    """
    from pydantic import create_model

    disabled = set(config.disabled_axes)

    # Collect fields from PostCallAnalysis, excluding disabled axes
    base_fields: dict[str, tuple] = {}
    for field_name, field_info in PostCallAnalysis.model_fields.items():
        if field_name in disabled:
            continue
        annotation = PostCallAnalysis.__annotations__.get(field_name)
        if annotation is None:
            # Fallback: use the field info annotation
            annotation = field_info.annotation
        # Re-create the field with the same info
        base_fields[field_name] = (annotation, field_info)

    # If extra axes are configured, add extra_axes_data JSON catch-all
    if config.extra_axes:
        from pydantic import Field as PydanticField

        base_fields["extra_axes_data"] = (
            dict | None,
            PydanticField(
                default=None,
                description="Client-specific extra axis data (JSON catch-all for extensions)",
            ),
        )

    DynamicModel = create_model(
        "DynamicPostCallAnalysis",
        __base__=None,
        **base_fields,
    )
    return DynamicModel


_MODEL_CACHE_MAX_SIZE: int = 100

# LRU model cache: OrderedDict(cache_key → model_class)
# Evicts the oldest entry when size exceeds _MODEL_CACHE_MAX_SIZE.
_model_cache: "OrderedDict[str, type[BaseModel]]" = OrderedDict()


def build_analysis_model(config: "ExtractionConfig | None") -> type[BaseModel]:
    """Return a Pydantic model class composed from PostCallAnalysis + config extensions.

    Cached with a simple LRU dict (max 100 entries, oldest evicted first).
    NULL config → returns PostCallAnalysis unchanged (backward compat).
    Compatible with OpenAI parse(response_format=...).

    Args:
        config: ExtractionConfig instance (or None for base-only model).

    Returns:
        A Pydantic model class suitable as response_format for OpenAI parse().
    """
    if config is None:
        return PostCallAnalysis

    cache_key = _config_cache_key(config)

    if cache_key in _model_cache:
        # Move to end (most recently used)
        _model_cache.move_to_end(cache_key)
        return _model_cache[cache_key]

    # Build the model for the given config
    model = _make_model_for_config(config)

    # Evict oldest entry if at capacity
    if len(_model_cache) >= _MODEL_CACHE_MAX_SIZE:
        _model_cache.popitem(last=False)  # Remove oldest (first) entry

    _model_cache[cache_key] = model
    return model


# ---------------------------------------------------------------------------
# Issue #35 — Generic system prompt builder
# ---------------------------------------------------------------------------

_UNIVERSAL_AXIS_INSTRUCTIONS: dict[str, str] = {
    "service_issues": """\
- service_issues: Service problems or complaints the lead mentioned
  - issues: List of service problems or complaints (empty list if none)""",
    "profile_facts": """\
- profile_facts: Personal or professional facts about the lead revealed during the call
  - facts: List of facts (empty list if none revealed)""",
    "commitment_signals": """\
- commitment_signals: Verbal commitments or intent signals from the lead
  - signals: List of commitments or signals (empty list if none)""",
    "abandonment_reason": """\
- abandonment_reason: Why the lead disengaged, if applicable
  - reason: String explaining disengagement, or null if lead did not disengage""",
}

_BASE_SYSTEM_INTRO = """\
You are an expert sales call analyst. You receive a transcript from a sales call \
and must return a structured JSON analysis.

Analyze the call and extract ALL of the following fields:

BASE FIELDS:
- summary: Concise plain-language summary of the call (max 150 tokens)
- objections: List of objections or hesitations the lead raised
- interest_level: Integer 0-100 (0 = completely uninterested, 100 = ready to buy immediately)
- current_insurance: Current carrier/provider if mentioned, otherwise null
- next_action_suggested: One of: call_again, send_quote, wait, do_not_call
- misc_notes: Any other relevant facts as a brief text note (empty string if nothing extra)
- data_corrections: If the lead explicitly corrected factual data, record each correction \
as 'field_name: corrected_value' on a separate line. Empty string if no corrections.

ANALYSIS AXES:
- call_outcome: Structured outcome classification
  - classification: One of: interested, not_interested, busy, follow_up, no_answer, hostile, confused
  - reason: One sentence explaining WHY this classification applies
  - engagement_quality: One of: high, medium, low, none

- detected_interests: What the lead was interested in
  - products: Products or services mentioned or inquired about
  - specific_needs: Requirements expressed by the lead
  - buying_signals: Concrete indicators of purchase intent

- identified_problem: The underlying need driving interest
  - primary_need: One sentence — what the lead actually needs
  - pain_points: Current pain points motivating their interest
  - urgency: One of: high, medium, low
"""

_BASE_RULES = """\
RULES:
- next_action_suggested = "do_not_call" ONLY if lead explicitly asked not to be called again
- interest_level: base it on enthusiasm, engagement, and stated intent
- call_outcome.classification = "no_answer" if the call never connected
- call_outcome.engagement_quality = "none" if the lead said nothing meaningful
- detected_interests fields default to empty lists if nothing was detected
- identified_problem.pain_points defaults to empty list if unclear
- Always return valid JSON matching the schema exactly
"""

# Per-axis rule lines (only appended when axis is not disabled)
_AXIS_RULE_LINES: dict[str, str] = {
    "service_issues": "- service_issues.issues defaults to empty list if no issues mentioned",
    "profile_facts": "- profile_facts.facts defaults to empty list if no facts revealed",
    "commitment_signals": "- commitment_signals.signals defaults to empty list if no signals",
    "abandonment_reason": "- abandonment_reason.reason is null if lead did not disengage",
}


def build_system_prompt(config: "ExtractionConfig | None") -> str:
    """Build a generic system prompt for the extraction pipeline.

    Composes: intro + per-axis blocks (skipping disabled) + extra axis instructions
    + RULES + optional client addendum.

    NULL config → returns ANALYSIS_SYSTEM_PROMPT (backward compat).

    Args:
        config: ExtractionConfig instance (or None for legacy prompt).

    Returns:
        System prompt string ready for use as the system message.
    """
    if config is None:
        return ANALYSIS_SYSTEM_PROMPT

    disabled = set(config.disabled_axes)

    parts = [_BASE_SYSTEM_INTRO]

    # Universal axes — include only non-disabled ones
    active_axes = [name for name in _universal_axis_order() if name not in disabled]
    if active_axes:
        parts.append("UNIVERSAL AXES:")
        for axis_name in active_axes:
            parts.append(_UNIVERSAL_AXIS_INSTRUCTIONS[axis_name])

    # Client extra axes instructions
    if config.extra_axes:
        parts.append("\nCLIENT-SPECIFIC EXTRA AXES (capture in extra_axes_data):")
        for ax in config.extra_axes:
            parts.append(f"- {ax.name}: {ax.description} (type: {ax.field_type})")

    # Rules section — base rules + per-active-axis rules
    rules_lines = _BASE_RULES.rstrip().split("\n")
    for axis_name in _universal_axis_order():
        if axis_name not in disabled and axis_name in _AXIS_RULE_LINES:
            rules_lines.append(_AXIS_RULE_LINES[axis_name])
    parts.append("\n".join(rules_lines))

    # Optional client addendum
    if config.prompt_addendum.strip():
        parts.append(f"\nADDITIONAL CONTEXT:\n{config.prompt_addendum.strip()}")

    return "\n".join(parts)


def _universal_axis_order() -> list[str]:
    """Return the canonical order of universal axis names."""
    return [
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    ]
