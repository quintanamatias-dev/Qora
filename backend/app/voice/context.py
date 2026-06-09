"""QORA Voice — Per-session context cache.

Defines VoiceSessionContext (frozen dataclass) and build_voice_context()
async factory. Context is built once at call initiation and cached on
ConversationState to eliminate repeated DB queries and filesystem I/O per turn.

Architecture decisions:
- AD-1: VoiceSessionContext lives here (not in session.py) — single
  responsibility; session.py stays pure state tracking.
- AD-2: Cache location is ConversationState.context (in-memory) — no new infra.
- AD-4: Skills loaded via PromptLoader.load_agent_skills() — registry-based index only (no glob-all).
- AD-5: misc_notes from lead.extracted_facts["misc_notes"] — reuse existing.
- AD-6: system_prompt built by existing PromptLoader.render_for_agent().

Covers: VSC-1, VSC-2, VSC-3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from app.prompts.loader import PromptLoader
from app.prompts.skill_loader import SkillRegistryEntry

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.tenants.models import Agent, Client
    from app.leads.models import Lead


logger = structlog.get_logger()

LEAD_TEMPLATE_VARIABLES: frozenset[str] = frozenset(
    {
        "lead_name",
        "car_make",
        "car_model",
        "car_year",
        "current_insurance",
    }
)


def _agent_log_fields(agent: "Agent") -> dict:
    return {
        "agent_id": getattr(agent, "id", None),
        "agent_name": getattr(agent, "name", None),
        "agent_slug": getattr(agent, "slug", None),
        "client_id": getattr(agent, "client_id", None),
    }


def parse_agent_tool_config(agent: "Agent") -> dict | None:
    """Parse agent.tool_config (JSON TEXT column) into a dict.

    Centralises the parsing logic so webhook.py and context.py never diverge.

    Returns:
        Parsed dict, or None if the column is absent, empty, or not valid JSON/dict.
    """
    raw = getattr(agent, "tool_config", None)
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def prompt_uses_lead_placeholders(prompt: str | None) -> bool:
    """Return True when a prompt template already injects lead raw fields."""
    if not prompt:
        return False
    placeholders = set(re.findall(r"\{\{(\w+)\}\}", prompt))
    return bool(placeholders & LEAD_TEMPLATE_VARIABLES)


# ---------------------------------------------------------------------------
# VoiceSessionContext — immutable per-session context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VoiceSessionContext:
    """Immutable per-session context, built once at initiation.

    Fields:
        system_prompt: Fully rendered system prompt, ready to use as system message.
        skills_content: Legacy field — always None in registry mode. Kept for
            backward compatibility with existing tests that construct this dataclass
            directly. Do NOT use for new code; use skills_index instead.
        misc_notes: From extracted_facts["misc_notes"] (empty if absent/no lead).
        lead_profile: Formatted lead data block (empty if no lead).
        model: LLM model identifier from agent config.
        temperature: Sampling temperature from agent config.
        max_tokens: Max tokens from agent config.
        tools: Parsed tool definitions (None if empty/disabled).
        skip_lead_profile_in_assembly: When True, lead_profile is NOT appended to the
            assembled system message. Set when the agent uses template vars ({{lead_name}},
            etc.) so render_for_agent() already substituted lead data — appending lead_profile
            would duplicate it (Issue #21).
        skills_index: Formatted ## Available Skills index block from registry.yaml.
            None when agent has no registry (no skills injected). Set by build_voice_context()
            from load_agent_skills() output.
    """

    system_prompt: str
    skills_content: str | None
    misc_notes: str
    lead_profile: str
    model: str
    temperature: float
    max_tokens: int
    tools: list[dict] | None
    # Parsed Agent.tool_config JSON. Required by webhook dispatch so capture_data can
    # validate runtime arguments against the same per-agent schema used for OpenAI tools.
    agent_tool_config: dict | None = None
    skip_lead_profile_in_assembly: bool = False
    # TTS runtime config — resolved from Agent columns (Agent-first, defaults as fallback)
    tts_speed: float = 0.95
    tts_stability: float = 0.4
    tts_similarity_boost: float = 0.75
    tts_model: str = "eleven_flash_v2_5"
    # Registry-based skills index — NEW in Phase 1 (dynamic-agent-skills)
    skills_index: str | None = None
    # Registry entries stored as tuple (frozen dataclass requires hashable types)
    # NEW in Phase 2: used by load_skill dispatcher to validate + load skill files
    skill_registry_entries: tuple[SkillRegistryEntry, ...] = ()
    # Agent slug stored for tool routing (load_skill needs client_id + agent_slug)
    # NEW in Phase 2
    agent_slug: str | None = None


# ---------------------------------------------------------------------------
# Lead profile block builder
# ---------------------------------------------------------------------------


def _build_lead_profile_block(lead: "Lead", custom_fields: dict | None = None) -> str:
    """Format lead data into a [CONTEXTO DEL LEAD] block.

    Business fields (car_make, car_model, car_year, current_insurance) are read
    from custom_fields (lead_custom_fields table) rather than legacy ORM columns
    that no longer exist on the Lead model.

    Args:
        lead: Lead ORM instance.
        custom_fields: Dict of custom field values from lead_custom_fields table.
            If None or empty, business fields are omitted from the block.

    Returns:
        Formatted string with lead context data. Empty string if all fields empty.
    """
    name = getattr(lead, "name", "") or ""
    status = getattr(lead, "status", "") or ""
    notes = getattr(lead, "notes", "") or ""

    cf = custom_fields or {}
    car_make = cf.get("car_make", "") or ""
    car_model = cf.get("car_model", "") or ""
    car_year = str(cf.get("car_year", "")) if cf.get("car_year") else ""
    current_insurance = cf.get("current_insurance", "") or ""

    # If all key fields are empty, return empty string
    if not name and not car_make:
        return ""

    parts = ["[CONTEXTO DEL LEAD]"]
    if name:
        parts.append(f"Nombre: {name}")
    car_parts = " ".join(filter(None, [car_make, car_model, car_year]))
    if car_parts:
        parts.append(f"Auto: {car_parts}")
    if current_insurance:
        parts.append(f"Seguro actual: {current_insurance}")
    if status:
        parts.append(f"Estado: {status}")
    if notes:
        parts.append(f"Notas: {notes}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# build_voice_context() — async context factory
# ---------------------------------------------------------------------------


async def build_voice_context(
    *,
    agent: "Agent",
    lead: "Lead | None",
    db: "AsyncSession",
    client: "Client",
) -> VoiceSessionContext:
    """Assemble all context components for one voice session.

    Calls PromptLoader.render_for_agent() and load_agent_skills() to build
    a fully populated VoiceSessionContext. Exceptions from PromptLoader
    propagate — callers are responsible for handling them.

    Args:
        agent: Agent ORM instance with system_prompt, model, etc.
        lead: Optional Lead ORM instance (None for anonymous calls).
        db: AsyncSession for memory context queries.
        client: Client ORM instance for company name etc.

    Returns:
        Frozen VoiceSessionContext with all fields populated.

    Raises:
        Any exception raised by PromptLoader.render_for_agent() propagates.
    """
    client_id = getattr(agent, "client_id", None) or "unknown"
    agent_slug = getattr(agent, "slug", None)
    if not isinstance(agent_slug, str) or not agent_slug.strip():
        agent_slug = str(getattr(agent, "name", "agent")).lower().replace(" ", "-")

    loader = PromptLoader()  # uses module-level import (patchable in tests)

    # Render system prompt (may raise — let it propagate per VSC-2)
    system_prompt = await loader.render_for_agent(agent, lead, db=db, client=client)

    # Load skills registry index — returns ## Available Skills block or '' if no registry
    # The old glob-all behavior is REMOVED. No registry.yaml → no skills.
    try:
        _skills_raw = await loader.load_agent_skills(client_id, agent_slug)
    except Exception as exc:  # noqa: BLE001 - skills are optional context, not critical path
        logger.warning(
            "voice_context_skills_index_load_failed",
            **_agent_log_fields(agent),
            error_type=type(exc).__name__,
            error_msg=str(exc),
        )
        _skills_raw = ""
    # Normalize: empty string → None (no block injected into prompt)
    skills_index: str | None = _skills_raw if _skills_raw else None
    # skills_content is always None in registry mode
    skills_content: str | None = None

    # Load registry entries (raw objects) for load_skill allowlist validation
    # Stored as a tuple (frozen dataclass requires hashable types)
    try:
        _registry_entries_list = await loader.load_skill_registry_entries(client_id, agent_slug)
    except Exception as exc:  # noqa: BLE001 - registry entries degrade to no load_skill allowlist
        logger.warning(
            "voice_context_skill_registry_entries_load_failed",
            **_agent_log_fields(agent),
            error_type=type(exc).__name__,
            error_msg=str(exc),
        )
        _registry_entries_list = []
    skill_registry_entries: tuple[SkillRegistryEntry, ...] = tuple(_registry_entries_list)

    # Extract misc_notes from lead.extracted_facts. confirmed_facts no longer
    # carries misc_notes, so this is the single runtime channel for those notes.
    # misc_notes in DB can be a dict {"notes": [...]} or a plain string.
    misc_notes = ""
    if lead is not None:
        extracted = getattr(lead, "extracted_facts", None)
        if isinstance(extracted, dict):
            raw_notes = extracted.get("misc_notes", "")
            if isinstance(raw_notes, str):
                misc_notes = raw_notes
            elif isinstance(raw_notes, dict):
                # Format structured notes into readable text
                notes_list = raw_notes.get("notes", [])
                if isinstance(notes_list, list) and notes_list:
                    formatted = []
                    for note in notes_list:
                        if isinstance(note, dict):
                            formatted.append(note.get("note", ""))
                        elif isinstance(note, str):
                            formatted.append(note)
                    misc_notes = "\n".join(n for n in formatted if n)
                else:
                    misc_notes = ""
            else:
                misc_notes = str(raw_notes) if raw_notes else ""

    # Load custom fields for the lead profile block (FIX-6)
    lead_custom_fields: dict = {}
    if lead is not None:
        try:
            from app.leads.lead_custom_fields_service import get_all as _get_all_cf

            lead_custom_fields = await _get_all_cf(db, str(lead.id), client_id)
        except Exception as exc:  # noqa: BLE001 - custom fields are best-effort context
            logger.warning(
                "voice_context_custom_fields_load_failed",
                **_agent_log_fields(agent),
                error_type=type(exc).__name__,
                error_msg=str(exc),
            )

    # Build lead profile block — always computed for metadata/inspection.
    # Whether it's included in the assembled system message depends on whether
    # the agent system_prompt has template vars (see _assemble_context_system_content).
    lead_profile = _build_lead_profile_block(lead, lead_custom_fields) if lead is not None else ""

    # Track whether the effective prompt template uses lead vars. Filesystem
    # prompts are canonical; agent.system_prompt is only the legacy fallback.
    try:
        effective_prompt_template = await loader.load_agent_system_prompt(client_id, agent_slug)
    except Exception as exc:  # noqa: BLE001 - duplicate guard should not block calls
        logger.warning(
            "voice_context_effective_prompt_load_failed",
            **_agent_log_fields(agent),
            error_type=type(exc).__name__,
            error_msg=str(exc),
        )
        effective_prompt_template = None
    if not effective_prompt_template:
        effective_prompt_template = getattr(agent, "system_prompt", None) or ""
    _prompt_uses_lead_placeholders = prompt_uses_lead_placeholders(effective_prompt_template)

    # Model config from agent
    model = getattr(agent, "model", "gpt-4o") or "gpt-4o"
    temperature = getattr(agent, "temperature", 0.7)
    if temperature is None:
        temperature = 0.7
    max_tokens = getattr(agent, "max_tokens", 300)
    if max_tokens is None:
        max_tokens = 300

    # Parse tools from agent.tools_enabled
    # load_skill is ALWAYS injected when the agent has registry entries — it is an
    # infrastructure tool, not a CRM tool, and must be available regardless of what
    # tools_enabled lists. A demo agent seeded with tools_enabled="[]" would otherwise
    # be unable to call load_skill even when a registry.yaml is present (CRITICAL-1 fix).
    tools: list[dict] | None = None
    agent_tool_config: dict | None = None
    tools_enabled_str = getattr(agent, "tools_enabled", None)
    try:
        from app.tools.registry import build_tool_definitions as _build_tool_definitions

        enabled_names: list[str] = []
        if tools_enabled_str:
            try:
                enabled_names = json.loads(tools_enabled_str)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "voice_context_tools_enabled_malformed",
                    **_agent_log_fields(agent),
                    error="invalid_json",
                )
                enabled_names = []

        # Strip deprecated tool names from DB with deprecation warning (Phase 2).
        # Agents that still have register_interest/mark_not_interested/schedule_followup
        # in their stored tools_enabled continue operating with the remaining tools.
        from app.agents.schemas import strip_deprecated_tools as _strip_deprecated

        enabled_names = _strip_deprecated(enabled_names)

        # Inject load_skill unconditionally when the agent has registry entries
        if skill_registry_entries and "load_skill" not in enabled_names:
            enabled_names = list(enabled_names) + ["load_skill"]

        # Parse agent's tool_config (JSON TEXT column → dict) for dynamic tool schemas
        # Used by capture_data to get the per-agent parameters schema.
        agent_tool_config = parse_agent_tool_config(agent)

        # Load CRM config — provides field_definitions for capture_data schema (FIX-1)
        from app.integrations.crm_config import CRMConfigLoader as _CRMConfigLoader

        _crm_config = _CRMConfigLoader.load(client_id)

        tools = _build_tool_definitions(
            enabled_names,
            agent_tool_config=agent_tool_config,
            crm_config=_crm_config,
        )
    except ImportError as exc:
        logger.warning(
            "voice_context_tool_helpers_import_failed",
            **_agent_log_fields(agent),
            error_type=type(exc).__name__,
            error_msg=str(exc),
        )
        tools = None
        agent_tool_config = None

    # TTS config — Agent columns are authoritative; fall back to module defaults when NULL/absent
    tts_speed = getattr(agent, "tts_speed", None)
    if tts_speed is None:
        tts_speed = 0.95
    tts_stability = getattr(agent, "tts_stability", None)
    if tts_stability is None:
        tts_stability = 0.4
    tts_similarity_boost = getattr(agent, "tts_similarity_boost", None)
    if tts_similarity_boost is None:
        tts_similarity_boost = 0.75
    tts_model = getattr(agent, "tts_model", None)
    if tts_model is None:
        tts_model = "eleven_flash_v2_5"

    return VoiceSessionContext(
        system_prompt=system_prompt,
        skills_content=skills_content,
        misc_notes=misc_notes,
        lead_profile=lead_profile,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        agent_tool_config=agent_tool_config,
        skip_lead_profile_in_assembly=_prompt_uses_lead_placeholders,
        tts_speed=tts_speed,
        tts_stability=tts_stability,
        tts_similarity_boost=tts_similarity_boost,
        tts_model=tts_model,
        skills_index=skills_index,
        skill_registry_entries=skill_registry_entries,
        agent_slug=agent_slug,
    )
