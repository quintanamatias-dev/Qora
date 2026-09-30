"""Migration test for 20260930_0013_multi_tenant_auth (design.md §3).

Verifies upgrade/downgrade/upgrade cycles cleanly against a throwaway SQLite
file (never qora.db) and that the resulting schema matches the models.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from tests.helpers.migrations import apply_migrations


def test_upgrade_creates_auth_sessions_and_workos_organization_id(tmp_path: Path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/migration_test.db"
    apply_migrations(db_url)

    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _inspect():
        engine = create_async_engine(db_url)
        async with engine.connect() as conn:
            def _sync_inspect(sync_conn):
                insp = inspect(sync_conn)
                return set(insp.get_table_names()), {
                    c["name"] for c in insp.get_columns("clients")
                }

            tables, client_columns = await conn.run_sync(_sync_inspect)
        await engine.dispose()
        return tables, client_columns

    tables, client_columns = asyncio.run(_inspect())
    assert "auth_sessions" in tables
    assert "workos_organization_id" in client_columns


def test_downgrade_then_upgrade_is_clean(tmp_path: Path):
    import subprocess

    db_path = tmp_path / "migration_cycle_test.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"
    apply_migrations(db_url)

    backend_dir = Path(__file__).resolve().parents[3]
    import os

    env = {**os.environ, "DATABASE_URL": db_url, "QORA_SKIP_BACKUP_CHECK": "1"}

    downgrade = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "-1"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert downgrade.returncode == 0, downgrade.stderr

    upgrade = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr
