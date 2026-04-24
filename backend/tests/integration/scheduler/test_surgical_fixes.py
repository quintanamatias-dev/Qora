"""Surgical fix tests — migration and scheduler issues.

Covers:
- WARNING 2: migrate_add_agents.py DDL missing UNIQUE(client_id, slug)
- WARNING 4: backfill_agent_id N+1 → single correlated UPDATE
- WARNING 5: FK migration must check agents table exists first
- ALSO: redundant import in scheduler/service.py auto_schedule()
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy


# ---------------------------------------------------------------------------
# WARNING 2: agents table DDL must include UNIQUE(client_id, slug)
# ---------------------------------------------------------------------------


async def test_agents_migration_ddl_has_unique_constraint_on_client_slug(
    tmp_path: Path,
):
    """migrate_add_agents creates agents table with UNIQUE(client_id, slug)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/ddl_unique_test.db"
    engine = create_async_engine(db_url, echo=False)

    # Create minimal clients table (prerequisite)
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Agent',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    system_prompt_override TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    await engine.dispose()

    # Run migration
    from scripts.migrate_add_agents import run_migration

    await run_migration(db_url)

    # Verify the UNIQUE constraint on (client_id, slug) exists
    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        # Check via sqlite_master for unique index
        result = await conn.execute(
            sqlalchemy.text(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type IN ('table','index') AND tbl_name='agents'"
            )
        )
        rows = result.fetchall()
        found_unique = False
        for row in rows:
            name, sql_text = row
            if sql_text and "UNIQUE" in sql_text.upper():
                if "client_id" in sql_text.lower() and "slug" in sql_text.lower():
                    found_unique = True
                    break

        # Also check via pragma index_list which gives us unique indexes
        idx_result = await conn.execute(sqlalchemy.text("PRAGMA index_list(agents)"))
        indexes = idx_result.fetchall()
        for idx in indexes:
            # idx format: (seq, name, unique, origin, partial)
            is_unique = idx[2]  # unique flag
            idx_name = idx[1]
            if is_unique:
                # Check if this unique index covers both client_id and slug
                col_result = await conn.execute(
                    sqlalchemy.text(f"PRAGMA index_info({idx_name!r})")
                )
                col_names = {row[2] for row in col_result.fetchall()}
                if "client_id" in col_names and "slug" in col_names:
                    found_unique = True
                    break

    await engine2.dispose()

    assert found_unique, (
        "agents table must have a UNIQUE constraint on (client_id, slug). "
        "Migration DDL or index creation is missing it."
    )


async def test_agents_migration_enforces_unique_via_insert(tmp_path: Path):
    """After migration, inserting a duplicate (client_id, slug) raises IntegrityError."""
    import sqlalchemy.exc
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/unique_enforce_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Agent',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    system_prompt_override TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO clients (id, name, broker_name, voice_id) "
                "VALUES ('test-client', 'Test Client', 'Test SA', 'v-test')"
            )
        )
    await engine.dispose()

    from scripts.migrate_add_agents import run_migration

    await run_migration(db_url)

    # Now attempt to insert two agents with the same (client_id, slug)
    engine3 = create_async_engine(db_url, echo=False)
    import uuid

    with pytest.raises(Exception):  # sqlalchemy.exc.IntegrityError
        async with engine3.begin() as conn:
            await conn.execute(
                sqlalchemy.text(
                    "INSERT INTO agents (id, client_id, slug, name, voice_id) "
                    "VALUES (:id1, 'test-client', 'agent-slug', 'Agent 1', 'v-1')"
                ),
                {"id1": str(uuid.uuid4())},
            )
            # Duplicate slug for same client — must raise
            await conn.execute(
                sqlalchemy.text(
                    "INSERT INTO agents (id, client_id, slug, name, voice_id) "
                    "VALUES (:id2, 'test-client', 'agent-slug', 'Agent 2', 'v-2')"
                ),
                {"id2": str(uuid.uuid4())},
            )

    await engine3.dispose()


# ---------------------------------------------------------------------------
# WARNING 4: backfill uses single correlated UPDATE (not N+1 loop)
# ---------------------------------------------------------------------------


def test_backfill_agent_id_uses_correlated_update():
    """backfill_agent_id source code must use a correlated UPDATE, not SELECT+UPDATE loop.

    This tests the implementation approach by inspecting the function source code.
    The N+1 pattern would have a Python loop with individual UPDATEs.
    The correct pattern uses a single SQL UPDATE with a correlated subquery.
    """
    import inspect
    from scripts.migrate_add_agent_id_fks import backfill_agent_id

    source = inspect.getsource(backfill_agent_id)

    # Must NOT have a for loop iterating over rows with individual updates
    # The correlated UPDATE pattern uses a single UPDATE ... WHERE ... subquery
    assert (
        "UPDATE" in source.upper()
    ), "backfill_agent_id must contain an UPDATE statement"

    # Strict check: no Python for-loop at all in the function body.
    # The tautology `"for " not in source or "for row" not in source` was always True.
    # This assertion is the real check.
    assert "for " not in source, (
        "backfill_agent_id must NOT use a Python for-loop over rows. "
        "Use a single correlated subquery UPDATE instead."
    )


async def test_backfill_agent_id_updates_all_null_rows(tmp_path: Path):
    """backfill_agent_id correctly fills all NULL agent_id rows from default agents."""
    from sqlalchemy.ext.asyncio import create_async_engine
    import uuid

    db_url = f"sqlite+aiosqlite:///{tmp_path}/backfill_result_test.db"
    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE call_sessions (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    agent_id TEXT
                )
                """
            )
        )
        # Seed agent + 3 sessions
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_default) "
                "VALUES ('agent-x', 'c1', 'agent-slug', 'Agent', 'v1', 1)"
            )
        )
        for _ in range(3):
            await conn.execute(
                sqlalchemy.text(
                    "INSERT INTO call_sessions (id, client_id) VALUES (:id, 'c1')"
                ),
                {"id": str(uuid.uuid4())},
            )

    await engine.dispose()

    from scripts.migrate_add_agent_id_fks import backfill_agent_id

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        await backfill_agent_id(conn, "call_sessions")
    await engine2.dispose()

    # Verify all 3 sessions now have agent_id = 'agent-x'
    engine3 = create_async_engine(db_url, echo=False)
    async with engine3.begin() as conn:
        result = await conn.execute(
            sqlalchemy.text("SELECT COUNT(*) FROM call_sessions WHERE agent_id IS NULL")
        )
        null_count = result.scalar()
        assert null_count == 0, f"Expected 0 NULL agent_id rows, got {null_count}"

        result2 = await conn.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM call_sessions WHERE agent_id='agent-x'"
            )
        )
        filled_count = result2.scalar()
        assert (
            filled_count == 3
        ), f"Expected 3 rows with agent_id='agent-x', got {filled_count}"
    await engine3.dispose()


# ---------------------------------------------------------------------------
# WARNING 5: FK migration must check agents table exists first
# ---------------------------------------------------------------------------


async def test_fk_migration_raises_when_agents_table_missing(tmp_path: Path):
    """migrate_add_agent_id_fks raises RuntimeError if agents table doesn't exist."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/no_agents_table_test.db"
    engine = create_async_engine(db_url, echo=False)

    # Create call_sessions but NO agents table
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE call_sessions (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'initiated'
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE scheduled_calls (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
        )
    await engine.dispose()

    # Running the FK migration without agents table must raise RuntimeError
    from scripts.migrate_add_agent_id_fks import run_migration

    with pytest.raises(RuntimeError, match="agents"):
        await run_migration(db_url)


async def test_fk_migration_succeeds_when_agents_table_exists(tmp_path: Path):
    """migrate_add_agent_id_fks succeeds when agents table exists."""
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/with_agents_table_test.db"
    engine = create_async_engine(db_url, echo=False)

    # Create all required tables including agents
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    UNIQUE(client_id, slug)
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE call_sessions (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'initiated'
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE scheduled_calls (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
        )
    await engine.dispose()

    # Must not raise
    from scripts.migrate_add_agent_id_fks import run_migration

    await run_migration(db_url)  # should succeed without RuntimeError


# ---------------------------------------------------------------------------
# FIX 1: backfill must ignore inactive agents (is_active = 0)
# ---------------------------------------------------------------------------


async def test_backfill_skips_inactive_agents(tmp_path: Path):
    """backfill_agent_id must NOT use agents where is_active = 0 as the default.

    A deactivated agent that has is_default=1 must be excluded from backfill.
    Only agents with is_active=1 AND is_default=1 should be used.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    import uuid

    db_url = f"sqlite+aiosqlite:///{tmp_path}/backfill_inactive_test.db"
    engine = create_async_engine(db_url, echo=False)

    inactive_agent_id = "inactive-default-agent"
    active_agent_id = "active-default-agent"

    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE agents (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE call_sessions (
                    id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    agent_id TEXT
                )
                """
            )
        )
        # Client c1: has an INACTIVE default agent — must NOT be backfilled
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_active, is_default) "
                "VALUES (:id, 'c1', 'inactive-agent', 'Inactive', 'v1', 0, 1)"
            ),
            {"id": inactive_agent_id},
        )
        # Client c2: has an ACTIVE default agent — MUST be backfilled
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO agents (id, client_id, slug, name, voice_id, is_active, is_default) "
                "VALUES (:id, 'c2', 'active-agent', 'Active', 'v2', 1, 1)"
            ),
            {"id": active_agent_id},
        )
        session_c1 = str(uuid.uuid4())
        session_c2 = str(uuid.uuid4())
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO call_sessions (id, client_id) VALUES (:id, 'c1')"
            ),
            {"id": session_c1},
        )
        await conn.execute(
            sqlalchemy.text(
                "INSERT INTO call_sessions (id, client_id) VALUES (:id, 'c2')"
            ),
            {"id": session_c2},
        )
    await engine.dispose()

    from scripts.migrate_add_agent_id_fks import backfill_agent_id

    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        await backfill_agent_id(conn, "call_sessions")
    await engine2.dispose()

    engine3 = create_async_engine(db_url, echo=False)
    async with engine3.begin() as conn:
        # c1's session must remain NULL — inactive agent must NOT be used
        result_c1 = await conn.execute(
            sqlalchemy.text("SELECT agent_id FROM call_sessions WHERE client_id='c1'")
        )
        c1_agent = result_c1.scalar()
        assert (
            c1_agent is None
        ), f"Deactivated agent must NOT be used for backfill, but got agent_id={c1_agent!r}"

        # c2's session must be filled with the active agent
        result_c2 = await conn.execute(
            sqlalchemy.text("SELECT agent_id FROM call_sessions WHERE client_id='c2'")
        )
        c2_agent = result_c2.scalar()
        assert (
            c2_agent == active_agent_id
        ), f"Active default agent must be used for backfill, but got agent_id={c2_agent!r}"
    await engine3.dispose()


# ---------------------------------------------------------------------------
# FIX 2: strict (non-tautological) assertion for N+1 check
# ---------------------------------------------------------------------------


def test_backfill_agent_id_no_python_for_loop():
    """backfill_agent_id source must NOT contain a Python for-loop over rows.

    The correct implementation uses a single correlated UPDATE (no Python loop).
    This replaces the tautological assertion that was always True.
    """
    import inspect
    from scripts.migrate_add_agent_id_fks import backfill_agent_id

    source = inspect.getsource(backfill_agent_id)

    # This is a strict (non-tautological) check: 'for ' must not appear at all
    assert "for " not in source, (
        "backfill_agent_id must NOT use a Python for-loop. "
        "Use a single correlated subquery UPDATE instead."
    )


# ---------------------------------------------------------------------------
# FIX 3: Migration idempotency — rerun adds missing UNIQUE constraint
# ---------------------------------------------------------------------------


async def test_agents_migration_repairs_missing_unique_index_on_rerun(tmp_path: Path):
    """migrate_add_agents must add UNIQUE index on (client_id, slug) even when
    the agents table was already created by an older migration that lacked it.

    Simulates the scenario: user ran old migration → table exists without UNIQUE →
    reruns new migration → UNIQUE constraint must now exist.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    db_url = f"sqlite+aiosqlite:///{tmp_path}/repair_unique_test.db"
    engine = create_async_engine(db_url, echo=False)

    # Simulate old (broken) migration: agents table WITHOUT UNIQUE constraint
    async with engine.begin() as conn:
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    broker_name TEXT NOT NULL,
                    agent_name TEXT NOT NULL DEFAULT 'Agent',
                    voice_id TEXT NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    model TEXT NOT NULL DEFAULT 'gpt-4o',
                    temperature REAL NOT NULL DEFAULT 0.7,
                    max_tokens INTEGER NOT NULL DEFAULT 300,
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    system_prompt_override TEXT,
                    knowledge_base TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        # agents table WITHOUT UNIQUE(client_id, slug)
        await conn.execute(
            sqlalchemy.text(
                """
                CREATE TABLE IF NOT EXISTS agents (
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
                    tools_enabled TEXT NOT NULL DEFAULT '[]',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    is_default BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    await engine.dispose()

    # Rerun new migration — table already exists but lacks UNIQUE
    from scripts.migrate_add_agents import run_migration

    await run_migration(db_url)

    # Verify that UNIQUE index now exists
    engine2 = create_async_engine(db_url, echo=False)
    async with engine2.begin() as conn:
        idx_result = await conn.execute(sqlalchemy.text("PRAGMA index_list(agents)"))
        indexes = idx_result.fetchall()
        found_unique = False
        for idx in indexes:
            is_unique = idx[2]
            idx_name = idx[1]
            if is_unique:
                col_result = await conn.execute(
                    sqlalchemy.text(f"PRAGMA index_info({idx_name!r})")
                )
                col_names = {row[2] for row in col_result.fetchall()}
                if "client_id" in col_names and "slug" in col_names:
                    found_unique = True
                    break
    await engine2.dispose()

    assert found_unique, (
        "After rerunning migrate_add_agents.py, agents table must have "
        "UNIQUE index on (client_id, slug) even if the table already existed."
    )
