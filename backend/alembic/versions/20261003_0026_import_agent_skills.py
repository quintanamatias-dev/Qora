"""One-time import: skills rows from existing registry.yaml + *.agent-skill.md files (P4-D4).

Reads every backend/clients/{client}/agents/{agent}/skills/registry.yaml and,
for each entry in its skills: list, reads the referenced
{entry.name}.agent-skill.md file and inserts an agent-section skills row +
revision 1 for the matching agent.

A client gets a skill_packages row (owner_type="client") only if at least
one of its agents has a non-empty registry.yaml — a client whose every
agent registry is "skills: []" (e.g. jaumpablo today) gets no package at
all. A registry.yaml referencing an agent slug with no matching `agents`
row for that client is skipped (FK-safe, logged).

This migration deliberately does NOT import any `app.*` module (house
pattern, same as 20261003_0022): yaml and markdown are read inline.

Idempotent: re-running upgrade() does not duplicate an existing
(package_id, slug, agent_id) skills row — checked via SELECT before INSERT.

The filesystem files are NOT deleted by this migration or this phase —
deletion is deferred to a later release (P4-D4), same as 20261003_0022's
crm.yaml deferred-deletion rule.

Design: openspec/changes/skill-packages/design.md P4-D4.

Rollback plan:
  1. Run: alembic downgrade -1
  2. All skill_revisions, skills, and skill_packages rows are deleted.
     Safe — no runtime code reads these tables yet (task 3 is the cutover),
     and these tables did not exist before 20261003_0025 in this same
     migration chain, so no pre-existing row can be lost.

Revision ID: 20261003_0026
Revises: 20261003_0025
Create Date: 2026-10-03
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
import yaml
from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "20261003_0026"
down_revision: Union[str, None] = "20261003_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# backend/clients — module-level so tests can monkeypatch it to a tmp dir.
_CLIENTS_ROOT = Path(__file__).resolve().parent.parent.parent / "clients"

_REQUIRED_ENTRY_FIELDS = ("name", "description", "trigger_hint", "filler_text")


def _parse_registry(registry_path: Path) -> list[dict]:
    """Mirrors app/prompts/skill_loader.py's load_skill_registry() validation
    rules, duplicated here deliberately: migrations never import app.* (house
    pattern). Malformed YAML, a missing/non-list skills: key, or any entry
    missing a required field -> empty list (skip, logged).
    """
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        logger.error("import_agent_skills: malformed YAML at %s: %s", registry_path, exc)
        return []

    if not isinstance(raw, dict):
        return []

    entries = raw.get("skills")
    if not entries or not isinstance(entries, list):
        return []

    parsed: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            logger.error("import_agent_skills: non-mapping entry in %s", registry_path)
            return []
        missing = [f for f in _REQUIRED_ENTRY_FIELDS if not entry.get(f)]
        if missing:
            logger.error(
                "import_agent_skills: entry in %s missing fields %s", registry_path, missing
            )
            return []
        parsed.append(entry)
    return parsed


def upgrade() -> None:
    """Import every backend/clients/*/agents/*/skills/registry.yaml."""
    bind = op.get_bind()

    if not _CLIENTS_ROOT.exists():
        logger.info("import_agent_skills: clients root %s absent, skipped", _CLIENTS_ROOT)
        return

    existing_agents = {
        (row[0], row[1]): row[2]
        for row in bind.execute(
            sa.text("SELECT client_id, slug, id FROM agents")
        ).fetchall()
    }

    now = datetime.now(timezone.utc)

    for client_dir in sorted(_CLIENTS_ROOT.iterdir()):
        if not client_dir.is_dir():
            continue
        client_id = client_dir.name
        agents_dir = client_dir / "agents"
        if not agents_dir.exists():
            continue

        # Gather (agent_slug, agent_id, entries) for every agent with at
        # least one valid, non-empty registry entry — before creating any
        # package row, so a client whose every agent registry is empty
        # never gets an orphaned package (P4-D4).
        agent_entries: list[tuple[str, str, list[dict]]] = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_slug = agent_dir.name
            registry_path = agent_dir / "skills" / "registry.yaml"
            if not registry_path.exists():
                continue

            entries = _parse_registry(registry_path)
            if not entries:
                continue

            agent_id = existing_agents.get((client_id, agent_slug))
            if agent_id is None:
                logger.info(
                    "import_agent_skills: no agents row for client=%r slug=%r, skipped",
                    client_id,
                    agent_slug,
                )
                continue

            agent_entries.append((agent_slug, agent_id, entries))

        if not agent_entries:
            continue

        package_id = _ensure_client_package(bind, client_id, now)

        for agent_slug, agent_id, entries in agent_entries:
            skills_dir = agents_dir / agent_slug / "skills"
            for entry in entries:
                _import_entry(bind, package_id, agent_id, skills_dir, entry, now)


def _ensure_client_package(bind, client_id: str, now: datetime) -> str:
    existing = bind.execute(
        sa.text(
            "SELECT id FROM skill_packages WHERE owner_type = 'client' AND client_id = :client_id"
        ),
        {"client_id": client_id},
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    package_id = str(uuid.uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO skill_packages (id, owner_type, client_id, name, created_at, updated_at) "
            "VALUES (:id, 'client', :client_id, :name, :now, :now)"
        ),
        {
            "id": package_id,
            "client_id": client_id,
            "name": f"{client_id} skills",
            "now": now,
        },
    )
    return package_id


def _import_entry(
    bind, package_id: str, agent_id: str, skills_dir: Path, entry: dict, now: datetime
) -> None:
    slug = entry["name"]

    existing = bind.execute(
        sa.text(
            "SELECT id FROM skills WHERE package_id = :package_id AND slug = :slug "
            "AND agent_id = :agent_id"
        ),
        {"package_id": package_id, "slug": slug, "agent_id": agent_id},
    ).scalar_one_or_none()
    if existing is not None:
        return  # idempotent — already imported

    skill_file = skills_dir / f"{slug}.agent-skill.md"
    if not skill_file.exists():
        logger.error("import_agent_skills: missing skill file %s, skipped", skill_file)
        return

    content_md = skill_file.read_text(encoding="utf-8")

    skill_id = str(uuid.uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO skills (id, package_id, slug, section, agent_id, active_revision_id) "
            "VALUES (:id, :package_id, :slug, 'agent', :agent_id, NULL)"
        ),
        {"id": skill_id, "package_id": package_id, "slug": slug, "agent_id": agent_id},
    )

    revision_id = str(uuid.uuid4())
    bind.execute(
        sa.text(
            "INSERT INTO skill_revisions "
            "(id, skill_id, revision_number, content_md, filler_text, trigger_hint, "
            "description, source, created_by, created_at, note) "
            "VALUES (:id, :skill_id, 1, :content_md, :filler_text, :trigger_hint, "
            ":description, 'import', 'system', :now, "
            "'seeded revision 1 by migration 20261003_0026')"
        ),
        {
            "id": revision_id,
            "skill_id": skill_id,
            "content_md": content_md,
            "filler_text": entry["filler_text"],
            "trigger_hint": entry["trigger_hint"],
            "description": entry["description"],
            "now": now,
        },
    )

    bind.execute(
        sa.text("UPDATE skills SET active_revision_id = :revision_id WHERE id = :skill_id"),
        {"revision_id": revision_id, "skill_id": skill_id},
    )


def downgrade() -> None:
    """Delete every row this migration (or a re-run of it) could have created.

    skill_packages/skills/skill_revisions do not exist before 20261003_0025
    in this chain, so a full delete across all three tables cannot lose any
    pre-existing data.
    """
    op.execute("DELETE FROM skill_revisions")
    op.execute("DELETE FROM skills")
    op.execute("DELETE FROM skill_packages")
