"""QORA Phase 7 — Idempotent migration: create agents table + seed default agents.

Steps:
1. Create `agents` table (if not exists)
2. For each existing Client, seed one default Agent copying agent config fields
   (agent_name → name, voice_id, model, temperature, max_tokens, tools_enabled,
   system_prompt_override → system_prompt, knowledge_base)

Safe to run multiple times — checks if table/agents exist before acting.

Usage:
    python scripts/migrate_add_agents.py
    python scripts/migrate_add_agents.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid


async def table_exists(conn, table: str) -> bool:
    """Return True if the table already exists in the database."""
    import sqlalchemy

    result = await conn.execute(
        sqlalchemy.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:table"
        ),
        {"table": table},
    )
    return result.fetchone() is not None


async def run_migration(database_url: str) -> None:
    """Run Phase 7 agents table creation and seeding idempotently."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import sqlalchemy

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    async with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 1. Create agents table (if not exists)
        # ------------------------------------------------------------------
        print("\nChecking agents table...")
        if await table_exists(conn, "agents"):
            print("  [skip] agents table already exists")
        else:
            await conn.execute(
                sqlalchemy.text(
                    """
                    CREATE TABLE agents (
                        id TEXT PRIMARY KEY,
                        client_id TEXT NOT NULL REFERENCES clients(id),
                        slug TEXT NOT NULL,
                        name TEXT NOT NULL,
                        voice_id TEXT NOT NULL,
                        system_prompt TEXT,
                        knowledge_base TEXT,
                        model TEXT NOT NULL DEFAULT 'gpt-4o',
                        temperature REAL NOT NULL DEFAULT 0.7,
                        max_tokens INTEGER NOT NULL DEFAULT 300,
                        tools_enabled TEXT NOT NULL DEFAULT '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
                        is_active BOOLEAN NOT NULL DEFAULT 1,
                        is_default BOOLEAN NOT NULL DEFAULT 0,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(client_id, slug)
                    )
                    """
                )
            )
            await conn.execute(
                sqlalchemy.text(
                    "CREATE INDEX IF NOT EXISTS ix_agents_client_id ON agents(client_id)"
                )
            )
            print("  [create] agents table + ix_agents_client_id + UNIQUE(client_id, slug)")

        # ------------------------------------------------------------------
        # 1b. Ensure UNIQUE index on (client_id, slug) exists regardless of
        #     whether the table was just created or already existed from an
        #     older migration run that lacked the constraint.
        # ------------------------------------------------------------------
        await conn.execute(
            sqlalchemy.text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_client_slug "
                "ON agents(client_id, slug)"
            )
        )
        print("  [index] uq_agents_client_slug UNIQUE index ensured")

        # ------------------------------------------------------------------
        # 2. Seed one default Agent per existing Client (if not already seeded)
        # ------------------------------------------------------------------
        print("\nSeeding default agents for existing clients...")
        clients_result = await conn.execute(
            sqlalchemy.text(
                "SELECT id, agent_name, voice_id, model, temperature, max_tokens, "
                "tools_enabled, system_prompt_override, knowledge_base FROM clients"
            )
        )
        clients = clients_result.fetchall()

        seeded = 0
        skipped = 0
        for client_row in clients:
            (
                client_id,
                agent_name,
                voice_id,
                model,
                temperature,
                max_tokens,
                tools_enabled,
                system_prompt_override,
                knowledge_base,
            ) = client_row

            # Check if default agent already exists for this client
            existing = await conn.execute(
                sqlalchemy.text(
                    "SELECT id FROM agents WHERE client_id=:client_id AND is_default=1"
                ),
                {"client_id": client_id},
            )
            if existing.fetchone() is not None:
                print(f"  [skip] default agent already exists for client={client_id!r}")
                skipped += 1
                continue

            # Build slug from agent_name
            slug = (agent_name or "agent").lower().replace(" ", "-")
            agent_id = str(uuid.uuid4())

            await conn.execute(
                sqlalchemy.text(
                    """
                    INSERT INTO agents
                        (id, client_id, slug, name, voice_id, system_prompt, knowledge_base,
                         model, temperature, max_tokens, tools_enabled, is_active, is_default)
                    VALUES
                        (:id, :client_id, :slug, :name, :voice_id, :system_prompt,
                         :knowledge_base, :model, :temperature, :max_tokens,
                         :tools_enabled, 1, 1)
                    """
                ),
                {
                    "id": agent_id,
                    "client_id": client_id,
                    "slug": slug,
                    "name": agent_name or "Agent",
                    "voice_id": voice_id,
                    "system_prompt": system_prompt_override,
                    "knowledge_base": knowledge_base,
                    "model": model or "gpt-4o",
                    "temperature": temperature if temperature is not None else 0.7,
                    "max_tokens": max_tokens or 300,
                    "tools_enabled": tools_enabled or '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',
                },
            )
            print(f"  [seed] created default agent={agent_id!r} for client={client_id!r}")
            seeded += 1

        print(f"\nSeeded: {seeded} agents, skipped: {skipped} (already existed)")

    await engine.dispose()
    print("\nMigration complete.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Phase 7 — Agents table creation and seeding"
    )
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./qora.db",
        help="SQLAlchemy async database URL (default: sqlite+aiosqlite:///./qora.db)",
    )
    args = parser.parse_args()

    try:
        asyncio.run(run_migration(args.db_url))
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
