"""System prompt strings and the generic prompt builder.

Co-located with the schema for N8N portability — when migrating to N8N, the
webhook handler can import these strings without pulling the full app.
"""

from __future__ import annotations

from app.analysis.config import ExtractionConfig

ANALYSIS_SYSTEM_PROMPT: str = """\
You are an expert insurance sales call analyst. You receive a transcript from \
an insurance sales call (Quintana Seguros — Argentine auto insurance broker) \
and must return a structured JSON analysis.

Analyze the call and extract ALL of the following fields:

EXISTING FIELDS:
- summary: Concise plain-language summary of the call (max 150 tokens)
- objections: List of objections or hesitations the lead raised
- interest_level: Integer 0-100 (0 = completely uninterested, 100 = ready to buy immediately)
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

_AXIS_RULE_LINES: dict[str, str] = {
    "service_issues": "- service_issues.issues defaults to empty list if no issues mentioned",
    "profile_facts": "- profile_facts.facts defaults to empty list if no facts revealed",
    "commitment_signals": "- commitment_signals.signals defaults to empty list if no signals",
    "abandonment_reason": "- abandonment_reason.reason is null if lead did not disengage",
}


def _universal_axis_order() -> list[str]:
    """Canonical iteration order for universal axes in prompts and rules."""
    return [
        "service_issues",
        "profile_facts",
        "commitment_signals",
        "abandonment_reason",
    ]


def build_system_prompt(config: "ExtractionConfig | None") -> str:
    """Build a generic system prompt for the extraction pipeline.

    NULL config → returns ANALYSIS_SYSTEM_PROMPT (backward compat).
    """
    if config is None:
        return ANALYSIS_SYSTEM_PROMPT

    disabled = set(config.disabled_axes)

    parts = [_BASE_SYSTEM_INTRO]

    active_axes = [name for name in _universal_axis_order() if name not in disabled]
    if active_axes:
        parts.append("UNIVERSAL AXES:")
        for axis_name in active_axes:
            parts.append(_UNIVERSAL_AXIS_INSTRUCTIONS[axis_name])

    if config.extra_axes:
        parts.append("\nCLIENT-SPECIFIC EXTRA AXES (capture in extra_axes_data):")
        for ax in config.extra_axes:
            parts.append(f"- {ax.name}: {ax.description} (type: {ax.field_type})")

    rules_lines = _BASE_RULES.rstrip().split("\n")
    for axis_name in _universal_axis_order():
        if axis_name not in disabled and axis_name in _AXIS_RULE_LINES:
            rules_lines.append(_AXIS_RULE_LINES[axis_name])
    parts.append("\n".join(rules_lines))

    if config.prompt_addendum.strip():
        parts.append(f"\nADDITIONAL CONTEXT:\n{config.prompt_addendum.strip()}")

    return "\n".join(parts)
