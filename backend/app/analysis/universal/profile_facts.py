"""Profile facts dimension — stateful, operation-based personality/preference pipeline.

qora-profile-facts: Replaced flat list[str] facts with structured add/update/remove
operations. ProfileFactsAxis now holds a list of ProfileFactUpdate items (max 5).
The `run_profile_facts_pipeline()` standalone function is defined here (Phase 2).

post-call-analysis-bi-friendly PR 2: Added EXCLUDED_STRUCTURED_FIELDS set and
_filter_excluded_profile_facts() post-processing suppression (spec: profile-facts-exclusion).

Locale-aware: `fact` and `evidence` are written in the client's configured
analysis_language. `operation`, `category`, and `confidence` remain canonical codes.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

import logging
import re

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class ProfileFactCategory(str, Enum):
    """Valid categories for profile facts."""

    OCCUPATION = "occupation"
    AVAILABILITY = "availability"
    COMMUNICATION_PREFERENCE = "communication_preference"
    DECISION_STYLE = "decision_style"
    FAMILY_CONTEXT = "family_context"
    LIFESTYLE = "lifestyle"
    FINANCIAL_ATTITUDE = "financial_attitude"
    PRODUCT_KNOWLEDGE = "product_knowledge"
    PROVIDER_RELATIONSHIP = "provider_relationship"
    PERSONALITY_TONE = "personality_tone"
    OTHER = "other"


class ProfileFactUpdate(BaseModel):
    """A single add / update / remove operation on a profile fact."""

    operation: Literal["add", "update", "remove"]
    category: ProfileFactCategory
    fact: str = Field(description="Human-readable fact text")
    evidence: str = Field(
        description="Transcript quote or paraphrase supporting the fact"
    )
    confidence: Literal["low", "medium", "high"]
    target_fact_id: str | None = Field(
        default=None,
        description="fact_key of the existing row to replace/delete; required for update/remove",
    )

    @model_validator(mode="after")
    def validate_target_fact_id(self) -> "ProfileFactUpdate":
        """update and remove operations MUST supply target_fact_id."""
        if self.operation in ("update", "remove") and self.target_fact_id is None:
            raise ValueError(
                f"target_fact_id is required when operation='{self.operation}'"
            )
        return self


class ProfileFactsAxis(BaseModel):
    """Operation-based profile facts output from GPT (max 5 updates per call)."""

    updates: list[ProfileFactUpdate] = Field(
        default_factory=list,
        max_length=5,
        description="Profile fact operations emitted by GPT (max 5 per call)",
    )


# ---------------------------------------------------------------------------
# run_profile_facts_pipeline — standalone async pipeline.
# Receives current facts + transcript, returns add/update/remove operations.
# ---------------------------------------------------------------------------

_CATEGORY_DESCRIPTIONS = {
    "occupation": "Job, profession, or business role",
    "availability": "When / how the lead can be reached or is free",
    "communication_preference": "Preferred contact channel, language, or communication style",
    "decision_style": "How the lead makes decisions (solo, consults partner, needs time, etc.)",
    "family_context": "Household composition, dependents, partner, children",
    "lifestyle": "Hobbies, routines, activities, values",
    "financial_attitude": "Attitudes toward money, spending, insurance value",
    "product_knowledge": "Level of insurance knowledge or familiarity with products",
    "provider_relationship": "History or opinion of current/past insurance providers",
    "personality_tone": "General communication style, humor, formality, openness",
    "other": "Any stable trait that doesn't fit the other categories",
}

DEFAULT_LANGUAGE = "Spanish"

# ---------------------------------------------------------------------------
# post-call-analysis-bi-friendly PR 2 — structured field exclusion
# Spec: profile-facts-exclusion AD-4
# ---------------------------------------------------------------------------

EXCLUDED_STRUCTURED_FIELDS: frozenset[str] = frozenset(
    {
        "age",
        "zona",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
        "name",
        "phone",
        "email",
    }
)

# Regex patterns for structured field exclusion.
# Each entry: (exclusion_reason, route_note, compiled_regex)
# Patterns use word boundaries (\b) to avoid substring false positives.
# Design: AD-4 — post-processing suppression; keeps boundary rules lightweight.
_EXCLUSION_REGEX_PATTERNS: list[tuple[str, str, "re.Pattern[str]"]] = [
    # Age fields: match "N años", "edad", "year old", "tengo N" (age statement)
    (
        "structured_field_exists",
        "routed_to_corrections:age",
        re.compile(r"\b(años|year\s+old|edad\b|tengo\s+\d)", re.IGNORECASE),
    ),
    # Zona / location: match "zona X", "vive en", "vivo en", "barrio", "localidad"
    (
        "structured_field_exists",
        "routed_to_corrections:zona",
        re.compile(
            r"\b(zona\s+(sur|norte|oeste|este|centro|[a-záéíóúñ]+)|viv[eo]\s+en\s|"
            r"barrio\b|localidad\b)",
            re.IGNORECASE,
        ),
    ),
    # Car fields: brand names and car-related terms
    (
        "structured_field_exists",
        "routed_to_corrections:car",
        re.compile(
            r"\b(toyota|ford\b|chevrolet|volkswagen|renault|fiat\b|honda\b|peugeot|"
            r"nissan|hyundai|kia\b|mazda\b|mitsubishi|bmw\b|mercedes|corolla|fiesta\b|"
            r"golf\b|clio\b|sandero|veh[íi]culo\b)",
            re.IGNORECASE,
        ),
    ),
    # Current insurance: insurer names and insurance-related phrases
    (
        "structured_field_exists",
        "routed_to_corrections:current_insurance",
        re.compile(
            r"\b(la\s+caja\b|federaci[oó]n\s+patronal|sancor\b|zurich\b|allianz\b|"
            r"mapfre\b|galeno\b|swiss\s+medical|osde\b|seguro\s+(actual|en|con)\b|"
            r"asegurad[oa]\s+(con|en)\b)",
            re.IGNORECASE,
        ),
    ),
    # Contact fields: email addresses, phone mentions, name statements
    (
        "structured_field_exists",
        "routed_to_contact_fields",
        re.compile(
            r"(@|\b(tel[eé]fono|celular|n[uú]mero\s+de\s+tel|email\b|correo\b|"
            r"su\s+nombre\s+es\b|se\s+llama\b))",
            re.IGNORECASE,
        ),
    ),
]


def _filter_excluded_profile_facts(
    updates: list["ProfileFactUpdate"],
    *,
    call_id: str | None = None,
) -> tuple[list["ProfileFactUpdate"], list["ProfileFactUpdate"]]:
    """Filter profile fact updates that correspond to known structured lead fields.

    Applies regex-based exclusion on fact + evidence text using word boundaries
    to avoid false-positive substring matches. If a pattern matches, the update
    is suppressed and a structured audit log is emitted via logger.info
    (AD-4 — internal QA/audit only, not user-visible).

    Args:
        updates: List of ProfileFactUpdate items from GPT or validation.
        call_id: Source call ID for the audit log. Pass None if unavailable.

    Returns:
        Tuple of (allowed_updates, suppressed_updates).
        allowed_updates: Updates that do NOT match any exclusion pattern.
        suppressed_updates: Updates that were filtered out.
    """
    allowed: list[ProfileFactUpdate] = []
    suppressed: list[ProfileFactUpdate] = []

    for update in updates:
        combined_text = f"{update.fact} {update.evidence}"
        matched_reason: str | None = None

        for reason, route, pattern in _EXCLUSION_REGEX_PATTERNS:
            if pattern.search(combined_text):
                matched_reason = reason
                logger.info(
                    "profile_fact_suppressed: category=%s reason=%s route=%s call_id=%s fact_preview=%r",
                    str(update.category),
                    reason,
                    route,
                    call_id,
                    update.fact[:80] if update.fact else "",
                )
                break

        if matched_reason is not None:
            suppressed.append(update)
        else:
            allowed.append(update)

    return allowed, suppressed


_PIPELINE_SYSTEM_PROMPT = """\
You are an expert at building a persistent personality profile from sales call transcripts.

LANGUAGE NOTE: Write the `fact` and `evidence` fields in {language}. \
Keep `operation`, `category`, and `confidence` as the exact English codes listed above.

BOUNDARY RULES:
- profile_facts = STABLE traits about the PERSON (personality, preferences, habits, lifestyle patterns).
- NOT temporal context: appointments, follow-ups, action items → those go to misc_notes.
- NOT product interests or insurance needs: "wants auto insurance", "needs home coverage" → those go to the interests dimension.
- NOT provider complaints or service issues → those go to service_issues.
  Example: "consulta decisiones con su pareja" = profile_fact (decision_style — stable trait about HOW the person decides).
           "llamar el martes" = NOT a profile_fact (temporal → misc_notes).
           "quiere asegurar el auto" = NOT a profile_fact (product need → interests).
  The test: would this fact still be true about this person 6 months from now regardless of any insurance transaction? If yes → profile_fact. If no → it belongs elsewhere.

OPERATIONS:
- add: New fact not covered by current profile. target_fact_id must be null.
- update: Contradicts/refines an existing fact. target_fact_id = id of fact to replace.
- remove: Fact proven false or no longer applicable. target_fact_id = id to delete.

CATEGORIES (choose the best fit):
{categories}

CONSTRAINTS:
- Maximum 5 updates total.
- evidence is REQUIRED (direct quote or paraphrase from transcript).
- confidence: "low" | "medium" | "high".
- No duplicate facts from current profile — prefer update over add+remove when a fact evolves.
- If no stable traits are detected, return an empty updates list.
"""


def _build_pipeline_prompt(
    current_facts: list[dict],
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Build the system prompt with current facts serialized."""
    import json

    categories_block = "\n".join(
        f"  {k}: {v}" for k, v in _CATEGORY_DESCRIPTIONS.items()
    )
    prompt = _PIPELINE_SYSTEM_PROMPT.format(
        language=language, categories=categories_block
    )

    if current_facts:
        facts_json = json.dumps(
            [
                {
                    "id": f.get("fact_key", f.get("id", "")),
                    "category": f.get("category", ""),
                    "fact": f.get("fact_value", f.get("fact", "")),
                }
                for f in current_facts
            ],
            ensure_ascii=False,
            indent=2,
        )
        prompt += f"\nCURRENT FACTS:\n{facts_json}\n"
    else:
        prompt += "\nCURRENT FACTS: [] (first call — only 'add' operations are valid)\n"

    return prompt


def _validate_updates_against_current_facts(
    updates: list[ProfileFactUpdate],
    current_facts: list[dict],
) -> list[ProfileFactUpdate]:
    """Validate update/remove operations against current facts.

    - update with invalid target_fact_id → demote to add (delete the target_fact_id)
    - remove with invalid target_fact_id → silently discard
    - When current_facts is empty, discard all update/remove ops.
    """
    if not current_facts:
        # First call: only add operations are valid
        return [u for u in updates if u.operation == "add"]

    valid_ids = {f.get("fact_key", f.get("id", "")) for f in current_facts}

    validated: list[ProfileFactUpdate] = []
    for upd in updates:
        if upd.operation == "add":
            validated.append(upd)
        elif upd.operation == "update":
            if upd.target_fact_id in valid_ids:
                validated.append(upd)
            else:
                # Demote to add: create new without target
                demoted = ProfileFactUpdate(
                    operation="add",
                    category=upd.category,
                    fact=upd.fact,
                    evidence=upd.evidence,
                    confidence=upd.confidence,
                    target_fact_id=None,
                )
                validated.append(demoted)
        elif upd.operation == "remove":
            if upd.target_fact_id in valid_ids:
                validated.append(upd)
            # else: silently discard

    return validated


async def run_profile_facts_pipeline(
    transcript: str,
    client: AsyncOpenAI,
    *,
    current_facts: list[dict] | None = None,
    language: str = DEFAULT_LANGUAGE,
    call_id: str | None = None,
) -> ProfileFactsAxis:
    """Standalone async profile facts pipeline.

    Args:
        transcript: The call transcript text.
        client: AsyncOpenAI client instance.
        current_facts: List of dicts from get_active_profile_facts(db, lead_id).
            Each dict contains fact_key, fact_value, recorded_at, source_call_id.
            Pass [] or None for the first call.
        language: Output language for the `fact` and `evidence` fields.
            `operation`, `category`, and `confidence` stay canonical English codes.
        call_id: Source call session ID for suppression audit logging (AD-4).
            Pass None if unavailable — log still emits but without call context.

    Returns:
        ProfileFactsAxis with validated and excluded-filtered updates.
        Never raises — returns empty axis on failure.
    """
    facts = current_facts or []

    try:
        system_prompt = _build_pipeline_prompt(facts, language=language)
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            response_format=ProfileFactsAxis,
        )
        raw_axis: ProfileFactsAxis = response.choices[0].message.parsed

        # Validate update/remove operations against current facts
        validated_updates = _validate_updates_against_current_facts(
            raw_axis.updates, facts
        )

        # post-call-analysis-bi-friendly PR 2: apply structured field exclusion filter.
        # Suppresses profile facts that duplicate known structured lead fields (age, zona,
        # car fields, current_insurance, name, phone, email). Suppressed facts are logged
        # for internal QA/audit via logger.info (AD-4 — not user-visible).
        allowed_updates, _suppressed = _filter_excluded_profile_facts(
            validated_updates, call_id=call_id
        )

        return ProfileFactsAxis(updates=allowed_updates)

    except Exception:
        # Profile facts are non-critical — return empty on any failure
        return ProfileFactsAxis()
