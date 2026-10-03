"""QORA Tools — handle_load_skill() handler.

Reads a single agent skill's content from the already-resolved,
DB-sourced content map built once per session (skill-packages P4-D3 runtime
cutover) — no per-call filesystem or DB read.

Security: skill_name is validated against registry entries (allowlist) BEFORE
any content lookup — prevents path traversal / unauthorized access by design.

Architecture decisions:
- Registry acts as an explicit allowlist; any name not in the registry is rejected.
- Never raises exceptions — always returns {"content": ...} or {"error": ...}.
- content_by_slug is the per-session resolved map (VoiceSessionContext.skill_content_by_slug);
  callers build it once via app.prompts.skill_loader.load_skill_content_by_slug().

Covers: Phase 2, Tasks 2.2. Skill-packages Task 3.4 (DB cutover).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.prompts.skill_loader import SkillRegistryEntry

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Load detailed knowledge about a specific topic from your available skills. "
            "Call this when the conversation requires specialized knowledge listed in "
            "## Available Skills. Call it ONCE per skill per conversation — the knowledge "
            "persists in context after loading."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "The skill name from the ## Available Skills list",
                }
            },
            "required": ["skill_name"],
        },
    },
}

FILLER_TEXT = "Un momento, déjame revisar eso..."


async def handle_load_skill(
    *,
    client_id: str,
    agent_slug: str,
    skill_name: str,
    registry_entries: "list[SkillRegistryEntry]",
    content_by_slug: dict[str, str] | None = None,
) -> dict:
    """Load a single skill's content from the pre-resolved content map.

    Security model: skill_name MUST exist in registry_entries (allowlist check)
    before any content lookup is performed. This prevents path traversal /
    unauthorized access — only explicitly declared skills can be loaded.

    Args:
        client_id:        Tenant slug (e.g. "quintana-seguros").
        agent_slug:       Agent slug (e.g. "jaumpablo").
        skill_name:       The skill name from the LLM tool call.
        registry_entries: Parsed registry entries for this agent session.
        content_by_slug:  DB-sourced {skill_name: content_md} map resolved once
                           per session (VoiceSessionContext.skill_content_by_slug).

    Returns:
        {"content": "<full skill markdown>"} on success.
        {"error": "<human-readable message>"} on any failure.
        NEVER raises.
    """
    try:
        # --- Security: explicit path-separator validation (defense-in-depth) ---
        # Reject any skill_name containing path separators or '..' components BEFORE
        # registry lookup. The registry allowlist is the primary guard, but a poisoned
        # registry entry with a slash in the name could otherwise escape this check.
        _UNSAFE_CHARS = ("/", "\\", "..")
        if any(ch in skill_name for ch in _UNSAFE_CHARS):
            return {
                "error": (
                    f"Invalid skill name '{skill_name}': "
                    "path separators and '..' are not allowed."
                )
            }

        # --- Security: validate against registry allowlist ---
        # Build a lookup dict: name → entry
        registry_by_name = {entry.name: entry for entry in registry_entries}

        if skill_name not in registry_by_name:
            return {
                "error": (
                    f"Skill '{skill_name}' not found in registry. "
                    f"Available skills: {list(registry_by_name.keys()) or 'none'}."
                )
            }

        # --- Look up content from the already-resolved session map ---
        content = (content_by_slug or {}).get(skill_name)
        if content is None:
            logger.warning(
                "skill_content_missing: client=%s agent=%s skill=%s",
                client_id,
                agent_slug,
                skill_name,
            )
            return {
                "error": (
                    f"Skill content for '{skill_name}' could not be read. "
                    "The skill may not be available right now."
                )
            }

        return {"content": content}

    except Exception as exc:  # noqa: BLE001
        logger.error(
            "handle_load_skill_unexpected_error: client=%s agent=%s skill=%s error=%s",
            client_id,
            agent_slug,
            skill_name,
            exc,
        )
        return {"error": f"Unexpected error loading skill '{skill_name}'."}
