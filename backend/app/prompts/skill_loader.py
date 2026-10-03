"""QORA Skill Registry — DB-backed resolver (skill-packages P4-D3 runtime cutover).

load_skill_registry() / load_skill_content_by_slug() resolve an agent's
skills from skill_packages/skills/skill_revisions via
app.skills.service.resolve_agent_skills(), through the per-process
AgentSkillsCache (app.skills.service.get_default_skills_cache()). The
filesystem registry.yaml reader this module used before the skill-packages
cutover is fully removed — see app.skills.service for the resolution order
(P4-D2: agent-section > client-general > qora on slug collision) and the
cache's contract (P4-D3: keyed by agent_id, invalidated explicitly on writes).

An agent with no contributing skills resolves to an empty list — the same
semantics a missing registry.yaml had before this cutover.

build_skills_index() keeps its exact pre-cutover formatting contract: an
empty entry list returns "" (no block injected into the prompt).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.tenants.models import Agent


@dataclass(frozen=True)
class SkillRegistryEntry:
    """One resolved skill. Fields match the pre-cutover registry.yaml schema
    exactly, so the system prompt index and the load_skill tool contract are
    unchanged by the DB cutover.

        name:          Unique skill identifier (used as load_skill argument).
        description:   What the skill contains (shown in system prompt index).
        trigger_hint:  When the LLM should use this skill (shown in index).
        filler_text:   Phrase emitted to SSE stream before loading.
    """

    name: str
    description: str
    trigger_hint: str
    filler_text: str


async def load_skill_registry(
    session: "AsyncSession", agent: "Agent"
) -> list[SkillRegistryEntry]:
    """Resolve *agent*'s skills from the DB via the per-process cache.

    Returns an empty list when the agent has no contributing skills — the
    same semantics a missing registry.yaml had before this cutover.
    """
    from app.skills.service import get_default_skills_cache

    resolved = await get_default_skills_cache().get(session, agent)
    return resolved.entries


async def load_skill_content_by_slug(
    session: "AsyncSession", agent: "Agent"
) -> dict[str, str]:
    """Return {skill_name: content_md} for *agent*'s resolved skills.

    Sourced from the same cached resolution load_skill_registry() uses — no
    extra DB query beyond the first resolution per agent (P4-D3 hot path).
    """
    from app.skills.service import get_default_skills_cache

    resolved = await get_default_skills_cache().get(session, agent)
    return dict(resolved.content_by_slug)


# ---------------------------------------------------------------------------
# build_skills_index() — formats index text for system prompt injection
# ---------------------------------------------------------------------------


def build_skills_index(entries: Sequence[SkillRegistryEntry]) -> str:
    """Build the ## Available Skills block from registry entries.

    Returns empty string when entries is empty (no block injected).

    Args:
        entries: Sequence of SkillRegistryEntry objects.

    Returns:
        Formatted text block for injection after the system prompt, or ''.
    """
    if not entries:
        return ""

    lines: list[str] = [
        "## Available Skills",
        "You have access to specialized knowledge that can be loaded on demand.",
        "Call the `load_skill` tool when the conversation topic matches a skill below.",
        "Only load a skill ONCE per conversation — the knowledge persists after loading.",
        "",
        "| Skill | Description | When to use |",
        "|-------|-------------|-------------|",
    ]

    for entry in entries:
        lines.append(
            f"| {entry.name} | {entry.description} | {entry.trigger_hint} |"
        )

    return "\n".join(lines)
