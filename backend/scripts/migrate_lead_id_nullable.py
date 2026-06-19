# DEPRECATED — This script is superseded by Alembic migrations (phase-b-db-migration-foundation).
# All schema changes are now managed via: python scripts/migrate.py (alembic upgrade head).
# This file is kept for audit trail only. Do NOT run it against production databases.
# See docs/MIGRATIONS.md for the current migration workflow.

"""Migration: Relax NOT NULL constraint on call_sessions.lead_id.

SQLite doesn't support ALTER COLUMN, so we rebuild the table:
1. Rename existing table to _old
2. Create new table with lead_id nullable (matches current SQLAlchemy model)
3. Copy all data across
4. Drop _old

Idempotent: checks current schema first; exits early if lead_id is already nullable.

Background
----------
Historic drift: the SQLAlchemy model declares `lead_id` as `nullable=True`, but
the SQLite table was created with `NOT NULL`. This blocked legitimate use cases
where a call session is created before a lead is known (e.g. ElevenLabs custom-LLM
webhook fires without lead_id in the request body).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "qora.db"


def is_lead_id_nullable(conn: sqlite3.Connection) -> bool:
    """Return True if call_sessions.lead_id is already nullable."""
    cur = conn.execute("PRAGMA table_info(call_sessions)")
    for row in cur.fetchall():
        # row: (cid, name, type, notnull, dflt_value, pk)
        if row[1] == "lead_id":
            return row[3] == 0  # notnull == 0 means nullable
    raise RuntimeError("lead_id column not found in call_sessions")


def migrate(conn: sqlite3.Connection) -> None:
    """Rebuild call_sessions with lead_id nullable, preserving all data + FKs."""
    # Use transaction for atomicity
    conn.execute("BEGIN")
    try:
        # 1) Rename old table
        conn.execute("ALTER TABLE call_sessions RENAME TO call_sessions_old")

        # 2) Create new table — lead_id NULLABLE
        conn.execute(
            """
            CREATE TABLE call_sessions (
                id VARCHAR NOT NULL,
                client_id VARCHAR NOT NULL,
                lead_id VARCHAR,
                elevenlabs_conversation_id VARCHAR,
                status VARCHAR NOT NULL,
                started_at DATETIME NOT NULL,
                ended_at DATETIME,
                duration_seconds FLOAT,
                billable_minutes INTEGER,
                outcome VARCHAR,
                created_at DATETIME NOT NULL,
                summary TEXT,
                closed_reason VARCHAR,
                total_user_turns INTEGER NOT NULL DEFAULT 0,
                total_agent_turns INTEGER NOT NULL DEFAULT 0,
                extracted_facts TEXT,
                PRIMARY KEY (id),
                FOREIGN KEY (client_id) REFERENCES clients (id),
                FOREIGN KEY (lead_id) REFERENCES leads (id)
            )
            """
        )

        # 3) Copy data
        conn.execute(
            """
            INSERT INTO call_sessions
            SELECT
                id, client_id, lead_id, elevenlabs_conversation_id,
                status, started_at, ended_at, duration_seconds,
                billable_minutes, outcome, created_at,
                summary, closed_reason, total_user_turns, total_agent_turns,
                extracted_facts
            FROM call_sessions_old
            """
        )

        # 4) Recreate indexes (IF NOT EXISTS — SQLite sometimes auto-recreates)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_call_sessions_client_id ON call_sessions (client_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ix_call_sessions_lead_id ON call_sessions (lead_id)"
        )

        # 5) Drop old
        conn.execute("DROP TABLE call_sessions_old")

        conn.commit()
    except Exception:
        conn.rollback()
        raise


def main() -> int:
    if not DB_PATH.exists():
        print(f"[skip] DB not found at {DB_PATH}; nothing to migrate")
        return 0

    conn = sqlite3.connect(str(DB_PATH))
    try:
        if is_lead_id_nullable(conn):
            print("[skip] call_sessions.lead_id is already nullable")
            return 0

        print("[migrate] Relaxing NOT NULL on call_sessions.lead_id...")
        migrate(conn)

        # Verify
        if is_lead_id_nullable(conn):
            print("[ok] Migration complete — lead_id is now nullable")
            return 0
        else:
            print("[fail] Migration ran but lead_id is still NOT NULL")
            return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
