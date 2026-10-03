"""Golden regression (skill-packages, P4-D4) — Task 1.3/2.2.

Seeds quintana-seguros + its leads-agent via the real migration chain (not a
hand-built fixture), runs the real 20261003_0026 import migration, then
asserts resolve_agent_skills("leads-agent") returns entries and contents
byte-identical to the current registry.yaml + *.agent-skill.md files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
ALEMBIC_DIR = BACKEND_DIR / "alembic"
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
QUINTANA_SKILLS_DIR = (
    BACKEND_DIR / "clients" / "quintana-seguros" / "agents" / "leads-agent" / "skills"
)


def _make_migration_alembic_config(db_path: Path):
    from alembic.config import Config

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    return cfg


@pytest.fixture
def quintana_migrated_db(tmp_path):
    """Seed quintana-seguros + leads-agent via the real migration chain, then
    run the real 20261003_0026 import against the real backend/clients tree."""
    import sqlite3

    from alembic import command

    db_file = tmp_path / "skill_packages_golden.db"
    cfg = _make_migration_alembic_config(db_file)
    command.upgrade(cfg, "20261003_0025")

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "INSERT INTO clients (id, name, voice_id, is_active, created_at) "
        "VALUES ('quintana-seguros', 'Quintana Seguros', 'v1', 1, '2026-10-03T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO agents (id, client_id, slug, name, voice_id, created_at) "
        "VALUES ('leads-agent-id', 'quintana-seguros', 'leads-agent', 'Leads Agent', "
        "'v1', '2026-10-03T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    command.upgrade(cfg, "head")
    return db_file


async def test_quintana_leads_agent_registry_and_content_are_byte_identical_to_files(
    quintana_migrated_db,
):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from app.skills.service import resolve_agent_skills
    from app.tenants.models import Agent

    registry = yaml.safe_load((QUINTANA_SKILLS_DIR / "registry.yaml").read_text(encoding="utf-8"))
    file_entries_by_name = {entry["name"]: entry for entry in registry["skills"]}

    engine = create_async_engine(f"sqlite+aiosqlite:///{quintana_migrated_db}")
    try:
        async with AsyncSession(engine) as session:
            agent = (
                await session.execute(select(Agent).where(Agent.slug == "leads-agent"))
            ).scalar_one()
            resolved = await resolve_agent_skills(session, agent)
    finally:
        await engine.dispose()

    assert {e.name for e in resolved.entries} == set(file_entries_by_name)

    for entry in resolved.entries:
        file_entry = file_entries_by_name[entry.name]
        assert entry.description == file_entry["description"]
        assert entry.trigger_hint == file_entry["trigger_hint"]
        assert entry.filler_text == file_entry["filler_text"]

        file_content = (QUINTANA_SKILLS_DIR / f"{entry.name}.agent-skill.md").read_text(
            encoding="utf-8"
        )
        assert resolved.content_by_slug[entry.name] == file_content
