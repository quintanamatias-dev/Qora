"""QORA Tools — handle_load_skill() handler.

Reads a single agent skill file from the filesystem.
Security: skill_name is validated against registry entries (allowlist) BEFORE
any filesystem I/O — prevents path traversal by design.

Architecture decisions:
- Registry acts as an explicit allowlist; any name not in the registry is rejected.
- Never raises exceptions — always returns {"content": ...} or {"error": ...}.
- File path is constructed from client_id + agent_slug + skill_name (no raw paths).
- clients_dir is injectable for tests; defaults to backend/clients.

Covers: Phase 2, Tasks 2.2.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.prompts.skill_loader import SkillRegistryEntry

logger = logging.getLogger(__name__)

# Default clients directory (same resolution as skill_loader.py in prompts)
_DEFAULT_CLIENTS_DIR = Path(__file__).resolve().parents[2] / "clients"


async def handle_load_skill(
    *,
    client_id: str,
    agent_slug: str,
    skill_name: str,
    registry_entries: "list[SkillRegistryEntry]",
    clients_dir: Path | None = None,
) -> dict:
    """Load a single skill file content.

    Security model: skill_name MUST exist in registry_entries (allowlist check)
    before any filesystem access is performed. This prevents path traversal
    — only explicitly declared skills can be loaded.

    Args:
        client_id:        Tenant slug (e.g. "quintana-seguros").
        agent_slug:       Agent slug (e.g. "jaumpablo").
        skill_name:       The skill name from the LLM tool call.
        registry_entries: Parsed registry entries for this agent session.
        clients_dir:      Override clients root — used in tests via tmp_path.

    Returns:
        {"content": "<full skill markdown>"} on success.
        {"error": "<human-readable message>"} on any failure.
        NEVER raises.
    """
    try:
        # --- Security: explicit path-separator validation (defense-in-depth) ---
        # Reject any skill_name containing path separators or '..' components BEFORE
        # registry lookup. The registry allowlist is the primary guard, but a poisoned
        # registry entry with a slash in the name could otherwise escape the skills dir.
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

        # --- Build file path from known-safe components ---
        base = clients_dir if clients_dir is not None else _DEFAULT_CLIENTS_DIR
        skills_dir = base / client_id / "agents" / agent_slug / "skills"
        skill_file = skills_dir / f"{skill_name}.agent-skill.md"

        # --- Read file (async) ---
        exists = await asyncio.to_thread(skill_file.exists)
        if not exists:
            logger.warning(
                "skill_file_missing: client=%s agent=%s skill=%s path=%s",
                client_id,
                agent_slug,
                skill_name,
                skill_file,
            )
            return {
                "error": (
                    f"Skill file for '{skill_name}' could not be read. "
                    "The skill may not be available right now."
                )
            }

        content = await asyncio.to_thread(skill_file.read_text, "utf-8")
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
