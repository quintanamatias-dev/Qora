"""Profile facts dimension — stateful, operation-based personality/preference pipeline.

qora-profile-facts: Replaced flat list[str] facts with structured add/update/remove
operations. ProfileFactsAxis now holds a list of ProfileFactUpdate items (max 5).
The `run_profile_facts_pipeline()` standalone function is defined here (Phase 2).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, model_validator


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

_PIPELINE_SYSTEM_PROMPT = """\
You are an expert at building a persistent personality profile from sales call transcripts.

BOUNDARY RULES:
- profile_facts = STABLE traits (personality, preferences, lifestyle patterns).
- NOT temporal context: appointments, follow-ups, action items → those go to misc_notes.
  Example: "consulta decisiones con su pareja" = profile_fact (decision_style trait).
           "llamar el martes" = NOT a profile_fact.

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


def _build_pipeline_prompt(current_facts: list[dict]) -> str:
    """Build the system prompt with current facts serialized."""
    import json

    categories_block = "\n".join(
        f"  {k}: {v}" for k, v in _CATEGORY_DESCRIPTIONS.items()
    )
    prompt = _PIPELINE_SYSTEM_PROMPT.format(categories=categories_block)

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
) -> ProfileFactsAxis:
    """Standalone async profile facts pipeline.

    Args:
        transcript: The call transcript text.
        client: AsyncOpenAI client instance.
        current_facts: List of dicts from get_active_profile_facts(db, lead_id).
            Each dict contains fact_key, fact_value, recorded_at, source_call_id.
            Pass [] or None for the first call.

    Returns:
        ProfileFactsAxis with validated updates. Never raises — returns empty axis on failure.
    """
    facts = current_facts or []

    try:
        system_prompt = _build_pipeline_prompt(facts)
        response = await client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": transcript},
            ],
            response_format=ProfileFactsAxis,
        )
        raw_axis: ProfileFactsAxis = response.choices[0].message.parsed

        # Validate and filter updates against current facts
        validated_updates = _validate_updates_against_current_facts(
            raw_axis.updates, facts
        )

        return ProfileFactsAxis(updates=validated_updates)

    except Exception:
        # Profile facts are non-critical — return empty on any failure
        return ProfileFactsAxis()
