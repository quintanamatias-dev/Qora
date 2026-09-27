"""Alembic migration 20260927_0012 — client plan + entitlement overrides.

Existing clients must land on the unrestricted ``pilot`` plan so the upgrade
changes no behaviour (spec: plan-entitlements "Existing clients keep current
behaviour").
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config


def _config(db_path: Path) -> Config:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path}")
    return cfg


def _columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(clients)")}


def test_existing_clients_get_pilot_plan_and_downgrade_removes_columns(tmp_path: Path):
    db_path = tmp_path / "plan_migration.db"
    cfg = _config(db_path)

    command.upgrade(cfg, "20260727_0011")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO clients (id, name, voice_id, is_active, created_at) VALUES (?, ?, ?, 1, ?)",
            ("legacy", "Legacy Client", "voice-1", datetime.now(timezone.utc).isoformat()),
        )

    command.upgrade(cfg, "20260927_0012")
    with sqlite3.connect(db_path) as conn:
        plan, overrides = conn.execute(
            "SELECT plan, entitlement_overrides FROM clients WHERE id = 'legacy'"
        ).fetchone()
    assert plan == "pilot"
    assert overrides is None

    command.downgrade(cfg, "20260727_0011")
    assert {"plan", "entitlement_overrides"}.isdisjoint(_columns(db_path))
