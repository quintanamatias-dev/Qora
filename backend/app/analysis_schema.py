"""QORA — Post-call analysis schema (Phase 5, Issue #7).

Self-contained module: only imports pydantic + enum.
NO app dependencies (no FastAPI, no SQLAlchemy, no structlog, no app.*).

This module is the N8N migration boundary. When migrating to N8N:
- Copy this file + ANALYSIS_SYSTEM_PROMPT to the N8N webhook handler.
- Remove from this codebase.
- The webhook receives transcript text, calls OpenAI with PostCallAnalysis
  as response_format, and returns JSON.

Owned here:
- OutcomeClassification, EngagementQuality, Urgency enums
- CallOutcome, DetectedInterests, IdentifiedProblem axis models
- PostCallAnalysis root model (existing 6 fields + 3 new axes)
- ANALYSIS_SYSTEM_PROMPT (portable prompt, no schema hardcoding)
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


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

RULES:
- next_action_suggested = "do_not_call" ONLY if lead explicitly asked not to be called again
- interest_level: base it on enthusiasm, engagement, and stated intent
- call_outcome.classification = "no_answer" if the call never connected
- call_outcome.engagement_quality = "none" if the lead said nothing meaningful
- detected_interests fields default to empty lists if nothing was detected
- identified_problem.pain_points defaults to empty list if unclear
- Always return valid JSON matching the schema exactly
"""
