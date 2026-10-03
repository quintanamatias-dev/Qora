"""One-time import: agent_config_revisions revision 1 per existing agent.

For every existing agent row, creates exactly one `source=import`
AgentConfigV1-shaped revision and activates it (agents.active_revision_id).
The imported `system_prompt` equals the filesystem
`clients/{client_id}/agents/{agent_slug}/system-prompt.md` content when that
file exists, else the agent's `system_prompt` DB column — matching the
priority `render_for_agent` used prior to this change (design.md D6).

This migration deliberately does NOT import any `app.*` module: those may
change shape or be removed later, and an Alembic migration must remain
runnable against the schema as it was AT THIS REVISION regardless of future
application code changes. All logic needed (the filesystem lookup, the
AgentConfigV1 JSON shape) is inlined below.

Idempotent-safe: an agent whose active_revision_id is already set is skipped
entirely — re-running this migration (e.g. via `alembic upgrade head` twice,
or a manual re-invocation of upgrade()) never creates a second import
revision for an agent that already has one.

Design: openspec/changes/agent-config-revisions-routing/design.md D6.

Rollback plan:
  1. Run: alembic downgrade -1
  2. Every `source=import` revision created by this migration is deleted and
     every agent's active_revision_id is reset to NULL. The schema (table +
     column) from 20261002_0014 is untouched — it stays.

Revision ID: 20261002_0015
Revises: 20261002_0014
Create Date: 2026-10-02
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261002_0015"
down_revision: Union[str, None] = "20261002_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# backend/alembic/versions/<this file> -> parents[2] == backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_CLIENTS_DIR = _BACKEND_DIR / "clients"


def _read_filesystem_system_prompt(client_id: str, agent_slug: str) -> str | None:
    """Mirror app.prompts.loader.PromptLoader.load_agent_system_prompt, inlined.

    Intentionally duplicated rather than imported (see module docstring).
    """
    prompt_path = _CLIENTS_DIR / client_id / "agents" / agent_slug / "system-prompt.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return None


def _build_agent_config_v1_json(row: dict, system_prompt: str) -> str:
    """Build the AgentConfigV1-shaped JSON payload from one agents row.

    Field order and names match design.md D5. Fields with no Agent column
    source today (goal, first_message, language, turn_eagerness) are None —
    Phase 1a imports only what Agent.* already carries.
    """
    try:
        tools_enabled = json.loads(row["tools_enabled"]) if row["tools_enabled"] else []
    except (TypeError, ValueError):
        tools_enabled = []

    config = {
        "schema_version": "v1",
        "system_prompt": system_prompt,
        "goal": None,
        "voice_id": row["voice_id"],
        "tts_model": row["tts_model"],
        "tts_speed": row["tts_speed"],
        "tts_stability": row["tts_stability"],
        "tts_similarity_boost": row["tts_similarity_boost"],
        "model": row["model"],
        "temperature": row["temperature"],
        "max_tokens": row["max_tokens"],
        "tools_enabled": tools_enabled,
        "first_message": None,
        "language": None,
        "turn_eagerness": None,
        "soft_timeout_seconds": row["soft_timeout_seconds"],
        "soft_timeout_message": row["soft_timeout_message"],
        "soft_timeout_use_llm": (
            bool(row["soft_timeout_use_llm"])
            if row["soft_timeout_use_llm"] is not None
            else None
        ),
        "voicemail_detection_enabled": (
            bool(row["voicemail_detection_enabled"])
            if row["voicemail_detection_enabled"] is not None
            else None
        ),
        "max_call_duration_seconds": row["max_call_duration_seconds"],
    }
    return json.dumps(config)


def upgrade() -> None:
    """Create + activate one import revision per agent without one yet."""
    bind = op.get_bind()

    agents = bind.execute(
        sa.text(
            "SELECT id, client_id, slug, system_prompt, voice_id, tts_model, "
            "tts_speed, tts_stability, tts_similarity_boost, model, temperature, "
            "max_tokens, tools_enabled, soft_timeout_seconds, soft_timeout_message, "
            "soft_timeout_use_llm, voicemail_detection_enabled, "
            "max_call_duration_seconds "
            "FROM agents WHERE active_revision_id IS NULL"
        )
    ).mappings().all()

    now = datetime.now(timezone.utc)

    for agent in agents:
        file_prompt = _read_filesystem_system_prompt(agent["client_id"], agent["slug"])
        system_prompt = file_prompt if file_prompt is not None else agent["system_prompt"]

        config_json = _build_agent_config_v1_json(agent, system_prompt)
        revision_id = str(uuid.uuid4())

        bind.execute(
            sa.text(
                "INSERT INTO agent_config_revisions "
                "(id, agent_id, revision_number, config, schema_version, source, "
                "created_by, created_at, note) "
                "VALUES (:id, :agent_id, 1, :config, 'v1', 'import', 'system', "
                ":created_at, 'one-time import from Agent.* + filesystem system-prompt.md')"
            ),
            {
                "id": revision_id,
                "agent_id": agent["id"],
                "config": config_json,
                "created_at": now,
            },
        )
        bind.execute(
            sa.text("UPDATE agents SET active_revision_id = :rev_id WHERE id = :agent_id"),
            {"rev_id": revision_id, "agent_id": agent["id"]},
        )


def downgrade() -> None:
    """Delete every import revision and reset active_revision_id to NULL."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE agents SET active_revision_id = NULL "
            "WHERE active_revision_id IN ("
            "SELECT id FROM agent_config_revisions WHERE source = 'import')"
        )
    )
    bind.execute(sa.text("DELETE FROM agent_config_revisions WHERE source = 'import'"))
