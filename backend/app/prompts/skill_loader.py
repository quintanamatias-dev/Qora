"""QORA Skill Registry Loader — Phase 1.

Parses registry.yaml from the agent's skills directory and builds the
## Available Skills index block for injection into the system prompt.

Architecture decisions:
- Registry-only mode: no registry.yaml → no skills. NEVER falls back to
  globbing *.agent-skill.md files. That old behavior is completely removed.
- Malformed YAML or missing required fields → log warning + return empty list.
- build_skills_index([]) → empty string (no block injected into prompt).
- Multi-tenant isolation enforced by accepting client_id + agent_slug as
  explicit parameters (never raw filesystem paths).

Covers: Phase 1 Tasks 1.1, 1.2.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default clients directory — same resolution as loader.py
# ---------------------------------------------------------------------------

_DEFAULT_CLIENTS_DIR = Path(__file__).resolve().parents[2] / "clients"

# ---------------------------------------------------------------------------
# Required fields for each registry entry
# ---------------------------------------------------------------------------

_REQUIRED_ENTRY_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "trigger_hint",
)

# Optional fields and their defaults — omitting them in YAML is safe.
_DEFAULT_FILLER_TEXT = "Un momento, déjame revisar eso..."
_DEFAULT_TRANSITION_TEXT = "Listo, ya encontré la información."


# ---------------------------------------------------------------------------
# SkillRegistryEntry — immutable value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SkillRegistryEntry:
    """One entry from registry.yaml.

    Fields:
        name:            Unique skill identifier (used as load_skill argument).
        description:     What the skill contains (shown in system prompt index).
        trigger_hint:    When the LLM should use this skill (shown in index).
        filler_text:     Phrase emitted to SSE stream before loading the skill.
                         Optional — defaults to _DEFAULT_FILLER_TEXT if absent.
        transition_text: Phrase prepended to the follow-up LLM system message
                         after the skill is loaded, so the assistant begins its
                         answer with a natural transition (e.g. "Listo, ya
                         encontré la información."). Optional — defaults to
                         _DEFAULT_TRANSITION_TEXT if absent.
    """

    name: str
    description: str
    trigger_hint: str
    filler_text: str = _DEFAULT_FILLER_TEXT
    transition_text: str = _DEFAULT_TRANSITION_TEXT


# ---------------------------------------------------------------------------
# load_skill_registry() — async YAML parser
# ---------------------------------------------------------------------------


async def load_skill_registry(
    client_id: str,
    agent_slug: str,
    clients_dir: Path | None = None,
) -> list[SkillRegistryEntry]:
    """Parse registry.yaml → list of SkillRegistryEntry objects.

    Returns an empty list when:
    - The registry.yaml file does not exist (no glob-all fallback).
    - The skills: key is absent, null, or an empty list.
    - The YAML is malformed (logs a warning).
    - Any entry is missing a required field (logs a warning).

    Args:
        client_id:   Tenant slug (e.g. "quintana-seguros").
        agent_slug:  Agent slug (e.g. "jaumpablo").
        clients_dir: Override for the clients/ root — used in tests via tmp_path.

    Returns:
        Ordered list of SkillRegistryEntry objects, empty on any error.
    """
    base = clients_dir if clients_dir is not None else _DEFAULT_CLIENTS_DIR
    registry_path = base / client_id / "agents" / agent_slug / "skills" / "registry.yaml"

    # File not found → empty (no fallback)
    exists = await asyncio.to_thread(registry_path.exists)
    if not exists:
        return []

    raw = await asyncio.to_thread(registry_path.read_text, encoding="utf-8")

    # Parse YAML — malformed → log warning + return empty
    try:
        data = yaml.safe_load(raw)
    except Exception as exc:
        logger.warning(
            "skill_registry_yaml_parse_error: client=%s agent=%s error=%s",
            client_id,
            agent_slug,
            exc,
        )
        return []

    # skills: key absent or null
    if not isinstance(data, dict):
        logger.warning(
            "skill_registry_invalid_root: client=%s agent=%s — expected mapping, got %s",
            client_id,
            agent_slug,
            type(data).__name__,
        )
        return []

    raw_skills = data.get("skills")
    if not raw_skills:
        return []

    if not isinstance(raw_skills, list):
        logger.warning(
            "skill_registry_invalid_skills_key: client=%s agent=%s — expected list",
            client_id,
            agent_slug,
        )
        return []

    # Parse each entry — any missing required field → log warning + return empty
    entries: list[SkillRegistryEntry] = []
    for idx, item in enumerate(raw_skills):
        if not isinstance(item, dict):
            logger.warning(
                "skill_registry_entry_not_mapping: client=%s agent=%s entry=%d",
                client_id,
                agent_slug,
                idx,
            )
            return []

        missing = [f for f in _REQUIRED_ENTRY_FIELDS if not item.get(f)]
        if missing:
            logger.warning(
                "skill_registry_entry_missing_fields: client=%s agent=%s entry=%d missing=%s",
                client_id,
                agent_slug,
                idx,
                missing,
            )
            return []

        entries.append(
            SkillRegistryEntry(
                name=item["name"],
                description=item["description"],
                trigger_hint=item["trigger_hint"],
                filler_text=item.get("filler_text") or _DEFAULT_FILLER_TEXT,
                transition_text=item.get("transition_text") or _DEFAULT_TRANSITION_TEXT,
            )
        )

    return entries


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
