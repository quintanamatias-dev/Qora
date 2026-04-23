"""Integration tests for Agent entity migration — Phase 7 (Task 2.1 RED).

Covers:
- migrate_add_agents: creates agents table, seeds one default Agent per existing Client
- migrate_add_agent_id_fks: adds nullable agent_id to call_sessions and scheduled_calls,
  backfills agent_id from client's default agent
- Both scripts are idempotent (run twice, no errors, no duplicates)
- Backfill preserves existing session rows (all get a non-null agent_id)
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


async def _create_base_schema(conn) -> None:
    """Create the minimal schema expected by migration scripts."""
    await conn.execute(
        sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                broker_name TEXT NOT NULL,
                agent_name TEXT NOT NULL DEFAULT 'Jaumpablo',
                voice_id TEXT NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT 1,
                model TEXT NOT NULL DEFAULT 'gpt-4o',
                temperature REAL NOT NULL DEFAULT 0.7,
                max_tokens INTEGER NOT NULL DEFAULT 300,
                tools_enabled TEXT NOT NULL DEFAULT '["get_lead_details"]',
                system_prompt_override TEXT,
                knowledge_base TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS call_sessions (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL REFERENCES clients(id),
                lead_id TEXT REFERENCES leads(id),
                status TEXT NOT NULL DEFAULT 'initiated',
                started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    await conn.execute(
        sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS scheduled_calls (
                id TEXT PRIMARY KEY,
                client_id TEXT NOT NULL REFERENCES clients(id),
                lead_id TEXT NOT NULL REFERENCES leads(id),
                source_session_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                scheduled_at DATETIME NOT NULL,
                attempt_number INTEGER NOT NULL DEFAULT 1,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                trigger_reason TEXT NOT NULL,
                notes TEXT,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


async def _seed_client(conn, client_id: str, name: str, agent_name: str = "Jaumpablo") -> None:
    """Insert a minimal client row."""
    await conn.execute(
        sqlalchemy.text(
            "INSERT INTO clients (id, name, broker_name, agent_name, voice_id) "
            "VALUES (:id, :name, :broker_name, :agent_name, :voice_id)"
        ),
        {
            "id": client_id,
            "name": name,
            "broker_name": name,
            "agent_name": agent_name,
            "voice_id": "pNInz6obpgDQGcFmaJgB",
        },
    )


async def _seed_session(conn, session_id: str, client_id: str) -> None:
    """Insert a minimal call_sessions row."""
    await conn.execute(
        sqlalchemy.text(
            "INSERT INTO call_sessions (id, client_id) VALUES (:id, :client_id)"
        ),
        {"id": session_id, "client_id": client_id},
    )


async def _seed_scheduled_call(conn, sc_id: str, client_id: str, lead_id: str) -> None:
    """Insert a minimal scheduled_calls row."""
    await conn.execute(
        sqlalchemy.text(
            "INSERT INTO scheduled_calls "
            "(id, client_id, lead_id, scheduled_at, trigger_reason) "
            "VALUES (:id, :client_id, :lead_id, datetime('now'), 'manual')"
        ),
        {"id": sc_id, "client_id": client_id, "lead_id": lead_id},
    )


# ---------------------------------------------------------------------------
# Tests: migrate_add_agents
# ---------------------------------------------------------------------------


async def test_migrate_add_agents_creates_agents_table(tmp_path: Path):
    """migrate_add_agents creates the agents table."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_agents_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)

    await engine.dispose()

    from scripts.migrate_add_agents import run_migration
    await run_migration(db_url)

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='agents'"
            )
        )
        row = result.fetchone()
        assert row is not None, "agents table was not created"
    await engine2.dispose()


async def test_migrate_add_agents_seeds_default_per_client(tmp_path: Path):
    """migrate_add_agents creates exactly one default Agent per existing Client."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_seed_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)
        await _seed_client(conn, "broker-a", "Broker A", "AgentA")
        await _seed_client(conn, "broker-b", "Broker B", "AgentB")

    await engine.dispose()

    from scripts.migrate_add_agents import run_migration
    await run_migration(db_url)

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        # broker-a has 1 default agent
        result_a = await conn.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM agents WHERE client_id='broker-a' AND is_default=1"
            )
        )
        count_a = result_a.scalar()
        assert count_a == 1, f"Expected 1 default agent for broker-a, got {count_a}"

        # broker-b has 1 default agent
        result_b = await conn.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM agents WHERE client_id='broker-b' AND is_default=1"
            )
        )
        count_b = result_b.scalar()
        assert count_b == 1, f"Expected 1 default agent for broker-b, got {count_b}"

        # Agent for broker-a has correct name from client.agent_name
        result_name = await conn.execute(
            sqlalchemy.text("SELECT name FROM agents WHERE client_id='broker-a'")
        )
        agent_name = result_name.scalar()
        assert agent_name == "AgentA", f"Agent name mismatch: got {agent_name!r}"

    await engine2.dispose()


async def test_migrate_add_agents_is_idempotent(tmp_path: Path):
    """Running migrate_add_agents twice does not create duplicate agents."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_idempotent_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)
        await _seed_client(conn, "broker-idem", "Broker Idem")

    await engine.dispose()

    from scripts.migrate_add_agents import run_migration

    # Run twice
    await run_migration(db_url)
    await run_migration(db_url)  # Must NOT raise or duplicate

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM agents WHERE client_id='broker-idem'"
            )
        )
        count = result.scalar()
        assert count == 1, f"Expected exactly 1 agent (idempotent), got {count}"

    await engine2.dispose()


# ---------------------------------------------------------------------------
# Tests: migrate_add_agent_id_fks
# ---------------------------------------------------------------------------


async def test_migrate_add_agent_id_fks_adds_column_to_call_sessions(tmp_path: Path):
    """migrate_add_agent_id_fks adds agent_id column to call_sessions."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_fks_sessions_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)
        await _seed_client(conn, "fk-client-a", "FK Client A")
        # Must run agents migration first to have agents table
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    system_prompt TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        # Insert a default agent manually
        import uuid
        agent_id = str(uuid.uuid4())
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_default) "
                "VALUES (:id, 'fk-client-a', 'agent-a', 'Agent A', 'v-a', 1)"
            ),
            {"id": agent_id},
        )

    await engine.dispose()

    from scripts.migrate_add_agent_id_fks import run_migration
    await run_migration(db_url)

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(call_sessions)"))
        columns = {row[1] for row in result.fetchall()}
        assert "agent_id" in columns, "agent_id column missing from call_sessions"

    await engine2.dispose()


async def test_migrate_add_agent_id_fks_adds_column_to_scheduled_calls(tmp_path: Path):
    """migrate_add_agent_id_fks adds agent_id column to scheduled_calls."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_fks_sched_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)
        await _seed_client(conn, "fk-client-b", "FK Client B")
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    system_prompt TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        import uuid
        agent_id = str(uuid.uuid4())
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_default) "
                "VALUES (:id, 'fk-client-b', 'agent-b', 'Agent B', 'v-b', 1)"
            ),
            {"id": agent_id},
        )

    await engine.dispose()

    from scripts.migrate_add_agent_id_fks import run_migration
    await run_migration(db_url)

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(scheduled_calls)"))
        columns = {row[1] for row in result.fetchall()}
        assert "agent_id" in columns, "agent_id column missing from scheduled_calls"

    await engine2.dispose()


async def test_migrate_fks_backfill_assigns_agent_id_to_existing_sessions(tmp_path: Path):
    """Backfill assigns default agent_id to all existing call_sessions for the client."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_backfill_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)
        await _seed_client(conn, "backfill-client", "Backfill Client")
        # Pre-create agents table with one default agent
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    system_prompt TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        import uuid
        agent_id = str(uuid.uuid4())
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_default) "
                "VALUES (:id, 'backfill-client', 'main', 'Main', 'v-main', 1)"
            ),
            {"id": agent_id},
        )
        # Insert 3 existing sessions (no agent_id yet)
        await _seed_session(conn, "sess-001", "backfill-client")
        await _seed_session(conn, "sess-002", "backfill-client")
        await _seed_session(conn, "sess-003", "backfill-client")

    await engine.dispose()

    from scripts.migrate_add_agent_id_fks import run_migration
    await run_migration(db_url)

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT id, agent_id FROM call_sessions WHERE client_id='backfill-client'"
            )
        )
        rows = result.fetchall()
        assert len(rows) == 3, f"Expected 3 session rows, got {len(rows)}"
        for row in rows:
            assert row[1] is not None, f"Session {row[0]} has NULL agent_id after backfill"
            assert row[1] == agent_id, (
                f"Session {row[0]} has wrong agent_id: {row[1]!r} (expected {agent_id!r})"
            )

    await engine2.dispose()


async def test_migrate_fks_is_idempotent(tmp_path: Path):
    """Running migrate_add_agent_id_fks twice does not raise or corrupt data."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/migrate_fks_idem_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await _create_base_schema(conn)
        await _seed_client(conn, "idem-client", "Idem Client")
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    system_prompt TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        import uuid
        agent_id = str(uuid.uuid4())
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_default) "
                "VALUES (:id, 'idem-client', 'main', 'Main', 'v-m', 1)"
            ),
            {"id": agent_id},
        )
        await _seed_session(conn, "idem-sess-001", "idem-client")

    await engine.dispose()

    from scripts.migrate_add_agent_id_fks import run_migration

    # Run twice — must NOT raise
    await run_migration(db_url)
    await run_migration(db_url)

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        result = await conn.execute(sqlalchemy.text("PRAGMA table_info(call_sessions)"))
        columns = {row[1] for row in result.fetchall()}
        assert "agent_id" in columns

        row_result = await conn.execute(
            sqlalchemy.text("SELECT agent_id FROM call_sessions WHERE id='idem-sess-001'")
        )
        row = row_result.fetchone()
        assert row is not None
        assert row[0] == agent_id

    await engine2.dispose()
