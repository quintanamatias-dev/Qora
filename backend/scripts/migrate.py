"""Pre-start migration entry point for Qora backend.

Runs `alembic upgrade head` before the FastAPI application process starts.
Exits non-zero on failure to block the application from starting with a
mismatched or incomplete schema.

Usage:
    # Local development:
    python scripts/migrate.py

    # Docker / deploy:
    CMD: python scripts/migrate.py && uvicorn app.main:app ...

Design: phase-b-db-migration-foundation/design.md — Migration model decision.

Existing-DB Safety (PR1 scope):
    PR1 is ADDITIVE only — it must not run DDL on a DB that already has the
    schema. Before running upgrade head, this script detects whether the target
    DB has existing tables but no valid alembic_version row (the "unstamped
    legacy" state). In that case it validates the schema is Qora-compatible
    before stamping, preserving all data and avoiding duplicate-table errors.

    Detection logic (applied to the EFFECTIVE DB, honoring DATABASE_URL):
      1. No DB file → fresh path: run upgrade head normally.
      2. DB exists, alembic_version has a valid row → already managed:
         run upgrade head (idempotent no-op when at head, or applies
         pending migrations).
      3. DB exists, no valid alembic_version row but has Qora-compatible
         tables → unstamped legacy DB: stamp head so Alembic knows this
         schema is at baseline; do NOT run DDL.
      4. DB exists, has tables but schema is NOT Qora-compatible (partial
         or unrelated DB) → fail safely with clear error. Never stamp an
         unrelated or partial DB.
      5. DB exists, empty (no user tables) → treat as fresh: run upgrade head.

DATABASE_URL handling:
    When the DATABASE_URL environment variable is set, it overrides the
    sqlalchemy.url in alembic.ini — exactly as alembic/env.py does at
    runtime. This script applies the override to the Config object BEFORE
    calling _get_db_path(), so safety checks and the upgrade/stamp command
    always operate on the SAME effective database.

Qora schema compatibility:
    A DB is considered Qora-compatible if ALL of the following hold:
    (1) All 10 Phase B baseline tables are present (clients, agents, leads,
        lead_profile_facts, lead_custom_fields, lead_interest_history,
        call_sessions, transcript_turns, call_analyses, scheduled_calls).
    (2) Every required baseline table has its required baseline columns
        (see _BASELINE_SCHEMA_CONTRACT). A DB with all 10 table names but
        only stub columns (e.g. just `id`) is rejected.
    (3) clients.broker_name is NOT NULL (PRAGMA table_info notnull=1).
    (4) ix_call_analyses_session_id index exists on call_analyses.
    A DB with only clients/agents/leads + broker_name is a PARTIAL schema and
    is rejected. Partial or unrelated databases are rejected with a clear
    RuntimeError to prevent accidental stamping.

Zero-drift note:
    The baseline migration targets the schema present in production qora.db
    at Phase B foundation. Known compatibility columns (e.g. broker_name) are
    included. However, exact byte-for-byte schema fidelity for EVERY column
    is NOT guaranteed for all edge-case server_default values. Tests verify
    the critical constraints that matter for correctness (NOT NULL, critical
    indexes). Overclaiming exact fidelity is explicitly avoided — see tests
    for what IS verified.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alembic.config import Config

# ---------------------------------------------------------------------------
# Full set of tables that must exist for the DB to be considered compatible
# with the Qora Phase B baseline migration. These are ALL 10 tables created
# by 20241201_0001_baseline.py — presence of ALL is required before stamp.
# Absence of ANY means the DB is partial or unrelated — do not stamp.
# ---------------------------------------------------------------------------
_QORA_REQUIRED_TABLES = frozenset({
    "clients",
    "agents",
    "leads",
    "lead_profile_facts",
    "lead_custom_fields",
    "lead_interest_history",
    "call_sessions",
    "transcript_turns",
    "call_analyses",
    "scheduled_calls",
})

# Critical index that must exist on call_analyses to confirm the DB has the
# full baseline schema (not a pre-baseline snapshot). This index was created
# explicitly in the baseline migration to match production qora.db.
_QORA_REQUIRED_INDEX = "ix_call_analyses_session_id"

# ---------------------------------------------------------------------------
# Baseline schema contract — required columns per table.
#
# Derived from the baseline migration (20241201_0001_baseline.py). A DB that
# has all 10 table names but is missing required columns (e.g. stub tables
# with only `id`) is NOT compatible with the baseline and must not be stamped.
#
# Only the columns that are critical identifiers, FK links, and key business
# fields are included here — we do NOT enumerate every column, which would be
# fragile. The goal is to reject stub/partial schemas while staying maintainable.
# ---------------------------------------------------------------------------
_BASELINE_SCHEMA_CONTRACT: dict[str, frozenset[str]] = {
    "clients": frozenset({"id", "name", "broker_name", "is_active", "voice_id"}),
    "agents": frozenset({"id", "client_id", "slug", "name", "voice_id", "is_active"}),
    "leads": frozenset({"id", "client_id", "name", "phone", "status"}),
    "lead_profile_facts": frozenset(
        {"id", "lead_id", "fact_key", "fact_value", "recorded_at"}
    ),
    "lead_custom_fields": frozenset(
        {"id", "lead_id", "client_id", "field_key", "field_type"}
    ),
    "lead_interest_history": frozenset(
        {"id", "lead_id", "interest_level", "recorded_at"}
    ),
    "call_sessions": frozenset({"id", "client_id", "status", "started_at", "created_at"}),
    "transcript_turns": frozenset({"id", "session_id", "role", "content", "timestamp"}),
    "call_analyses": frozenset(
        {"id", "session_id", "client_id", "analyzed_at", "analysis_status"}
    ),
    "scheduled_calls": frozenset(
        {"id", "client_id", "lead_id", "status", "scheduled_at", "trigger_reason"}
    ),
}


def _is_stamped(db_path: Path) -> bool:
    """Return True if the SQLite DB at db_path has a valid alembic_version row.

    Table existence alone is not enough — an empty alembic_version table
    means Alembic started writing but was interrupted. Treat it as not
    stamped to avoid proceeding to a raw upgrade head on an existing schema.
    """
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        # Check table presence first (avoids SQL error if table doesn't exist)
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        if cur.fetchone() is None:
            conn.close()
            return False
        # Require at least one valid version_num row — empty table is NOT stamped
        cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
        result = cur.fetchone()
        conn.close()
        return result is not None and bool(result[0])
    except Exception:
        return False


def _is_qora_compatible(db_path: Path) -> bool:
    """Return True if the SQLite DB is compatible with the full Qora Phase B baseline.

    Compatibility requires ALL of the following (fail-safe: any missing → False):

    1. ALL 10 baseline tables from 20241201_0001_baseline.py are present:
       clients, agents, leads, lead_profile_facts, lead_custom_fields,
       lead_interest_history, call_sessions, transcript_turns, call_analyses,
       scheduled_calls.
       A DB with only clients/agents/leads is a PARTIAL schema — not compatible.

    2. Every required table has its required baseline columns per
       _BASELINE_SCHEMA_CONTRACT. A DB with all 10 table names but stub columns
       (e.g. only `id`) is rejected — missing baseline columns means the schema
       is not at the Phase B baseline and must not be stamped.

    3. clients.broker_name column is NOT NULL (PRAGMA table_info notnull=1).
       Production qora.db has broker_name NOT NULL; a nullable column means
       schema drift or a different version — do not stamp.

    4. ix_call_analyses_session_id index exists on call_analyses.
       This critical index was created by the baseline migration; its absence
       means the DB predates or diverges from the baseline — do not stamp.

    Design: fail-safe. Any missing check returns False immediately. Only a DB
    that passes ALL checks may receive the baseline stamp.
    """
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # 1. Require ALL baseline tables to be present (not just a subset)
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT IN ('alembic_version', 'sqlite_sequence')"
        )
        present_tables = {row[0] for row in cur.fetchall()}

        if not _QORA_REQUIRED_TABLES.issubset(present_tables):
            conn.close()
            return False

        # 2. Validate baseline column contract: each required table must have
        #    its required baseline columns. Stub tables (only id) are rejected.
        for table, required_cols in _BASELINE_SCHEMA_CONTRACT.items():
            cur.execute(f"PRAGMA table_info({table})")  # noqa: S608 — table names are our own constants
            # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
            present_cols = {row[1] for row in cur.fetchall()}
            if not required_cols.issubset(present_cols):
                conn.close()
                return False

        # 3. Verify clients.broker_name is NOT NULL (nullability check via PRAGMA)
        cur.execute("PRAGMA table_info(clients)")
        # PRAGMA table_info returns: (cid, name, type, notnull, dflt_value, pk)
        broker_col = next(
            (row for row in cur.fetchall() if row[1] == "broker_name"), None
        )
        if broker_col is None:
            # Column does not exist at all
            conn.close()
            return False
        if broker_col[3] != 1:
            # notnull=0 means NULLABLE — does not match production schema
            conn.close()
            return False

        # 4. Verify critical index ix_call_analyses_session_id exists
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (_QORA_REQUIRED_INDEX,),
        )
        if cur.fetchone() is None:
            conn.close()
            return False

        conn.close()
        return True
    except Exception:
        return False


def _has_existing_schema(db_path: Path) -> bool:
    """Return True if the SQLite DB at db_path has any user tables (not alembic_version).

    Used only to distinguish between a truly empty DB and one that has
    tables. For stamp decisions, use _is_qora_compatible() to validate
    that the schema is safe to stamp.
    """
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT IN ('alembic_version', 'sqlite_sequence')"
        )
        result = cur.fetchone()
        conn.close()
        return result is not None
    except Exception:
        return False


def _get_db_path(alembic_cfg: Config) -> Path:
    """Extract the SQLite file path from the alembic Config URL.

    The URL on the Config object is the EFFECTIVE URL after any DATABASE_URL
    override has been applied. Always call this after setting the URL override.
    """
    url = alembic_cfg.get_main_option("sqlalchemy.url") or ""
    # sqlite+aiosqlite:///%(here)s/qora.db  →  strip driver prefix and ///
    # After interpolation: sqlite+aiosqlite:////abs/path/qora.db
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if url.startswith(prefix):
            path_str = url[len(prefix):]
            # Absolute path starts with /
            if path_str.startswith("/"):
                return Path(path_str)
            # Relative path — resolve relative to backend dir (ini location)
            ini_dir = Path(alembic_cfg.config_file_name).parent
            return (ini_dir / path_str).resolve()
    return Path(url)  # fallback — may not be a file path


def _check_backup_exists(db_path: Path) -> bool:
    """Return True if a readable today's backup exists for the given DB file.

    Spec ref: db-migration-tooling/spec.md — Requirement: Baseline Backup and Verification.
    Pattern: {db_dir}/{db_stem}.db.bak-{YYYYMMDD}  (e.g. qora.db.bak-20241201)

    A backup is considered readable when:
      - The file exists
      - Its size is non-zero
      - It can be opened as a SQLite database (readable)

    Args:
        db_path: The effective database file path (not a URL).

    Returns:
        True if a valid today's backup exists, False otherwise.
    """
    today = datetime.date.today().strftime("%Y%m%d")
    # Support both *.db.bak-DATE and *-DATE patterns for naming flexibility
    stem = db_path.stem  # e.g. "qora" from "qora.db"
    parent = db_path.parent
    candidates = [
        parent / f"{db_path.name}.bak-{today}",  # qora.db.bak-20241201
        parent / f"{stem}.bak-{today}",           # qora.bak-20241201
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            try:
                with sqlite3.connect(str(candidate)) as conn:
                    conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
                return True
            except sqlite3.Error:
                continue
    return False


def _require_backup(db_path: Path) -> None:
    """Block execution if no readable today's backup exists for the DB.

    Spec ref: db-migration-tooling/spec.md — Scenario: Backup absent — work blocked.
    Only enforced when QORA_SKIP_BACKUP_CHECK is not set. Set that variable in
    development or test environments where the DB is ephemeral (tmp paths, new DBs).

    This guard applies ONLY to existing non-empty databases. Fresh DBs (no file)
    do not require a backup since there is no data to protect.

    Raises:
        SystemExit(1): If no backup is found and QORA_SKIP_BACKUP_CHECK is unset.
    """
    if os.environ.get("QORA_SKIP_BACKUP_CHECK"):
        return  # dev / test / CI environments opt out explicitly

    if not _check_backup_exists(db_path):
        today = datetime.date.today().strftime("%Y%m%d")
        backup_name = f"{db_path.name}.bak-{today}"
        print(
            f"ERROR: No readable backup found for {db_path}.\n"
            f"Before running any migration step on an existing database, you MUST\n"
            f"create a timestamped backup:\n\n"
            f"    cp {db_path} {db_path.parent / backup_name}\n\n"
            f"Set QORA_SKIP_BACKUP_CHECK=1 to bypass this check in dev/test environments\n"
            f"where the database is ephemeral and does not need a backup.",
            file=sys.stderr,
        )
        sys.exit(1)


def run_migrations() -> None:
    """Run alembic upgrade head programmatically, with existing-DB safety.

    Loads alembic.ini from the backend/ directory (parent of this script's
    parent). The path is resolved from __file__ so it is deterministic
    regardless of the process cwd.

    DATABASE_URL env var is applied to the Config BEFORE safety checks so
    that _get_db_path() returns the effective database path — not the
    ini-file default.

    Decision tree (all checks use the effective DB from DATABASE_URL or ini):
      - No DB file       → upgrade head (fresh path)
      - Stamped DB       → upgrade head (idempotent, applies pending migrations)
      - Unstamped, Qora-compatible schema → stamp head (no DDL)
      - Unstamped, incompatible/partial/unrelated schema → RuntimeError (fail safe)
      - No user tables (empty file) → upgrade head (fresh path)

    Raises on failure — caller (main block) handles sys.exit.
    """
    from alembic.config import Config
    from alembic import command

    # Resolve alembic.ini relative to this script: backend/scripts/migrate.py
    # → backend/alembic.ini
    # Using Path(__file__).resolve() makes this cwd-independent.
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_ini = backend_dir / "alembic.ini"

    alembic_cfg = Config(str(alembic_ini))
    # Override script_location to absolute path so it resolves correctly
    # regardless of process cwd (alembic.ini-relative 'alembic' only works
    # when cwd == backend/).
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    # --- Apply DATABASE_URL override BEFORE any safety checks ---
    # This mirrors what alembic/env.py does at runtime. Applying the override
    # here ensures that _get_db_path() returns the effective database path
    # (the one Alembic will actually connect to), not the ini-file default.
    # Safety checks and the upgrade/stamp command must operate on the same DB.
    _db_url = os.environ.get("DATABASE_URL")
    if _db_url:
        alembic_cfg.set_main_option("sqlalchemy.url", _db_url)

    # --- Existing-DB safety check (PR1 additive scope) ---
    # _get_db_path is called AFTER DATABASE_URL override is applied.
    db_path = _get_db_path(alembic_cfg)

    # --- Backup gate (spec: Baseline Backup and Verification) ---
    # Require a readable today's backup before touching any existing DB.
    # Set QORA_SKIP_BACKUP_CHECK=1 to bypass in dev/test environments with ephemeral DBs.
    if db_path.exists() and _has_existing_schema(db_path):
        _require_backup(db_path)

    if db_path.exists() and not _is_stamped(db_path) and _has_existing_schema(db_path):
        # DB has user tables but no valid alembic_version row.
        # Determine whether it's safe to stamp (Qora-compatible) or not.
        if _is_qora_compatible(db_path):
            # Qora-compatible schema: stamp head so Alembic knows this schema
            # is at baseline. No DDL will run — schema is already present.
            print(
                f"Detected existing unstamped Qora-compatible DB at {db_path}. "
                "Stamping head (no DDL will run — schema already present).",
                file=sys.stdout,
            )
            command.stamp(alembic_cfg, "head")
            return
        else:
            # Incompatible, partial, or unrelated DB — fail safely.
            # Do NOT stamp and do NOT run upgrade DDL on an unknown schema.
            raise RuntimeError(
                f"Existing database at {db_path} has user tables but is NOT "
                "compatible with the Qora Phase B baseline schema. "
                "All 10 baseline tables must be present (clients, agents, leads, "
                "lead_profile_facts, lead_custom_fields, lead_interest_history, "
                "call_sessions, transcript_turns, call_analyses, scheduled_calls), "
                "clients.broker_name must be NOT NULL, and the "
                "ix_call_analyses_session_id index must exist. "
                "This database appears to be a partial schema, a pre-baseline "
                "snapshot, or an unrelated database — it cannot be safely stamped. "
                "Manual intervention required: verify the database schema or provide "
                "an empty/correct DATABASE_URL to start fresh."
            )

    # Fresh DB or already-managed DB: upgrade head is safe (idempotent at head)
    command.upgrade(alembic_cfg, "head")


if __name__ == "__main__":
    try:
        run_migrations()
        print("Migration complete: alembic upgrade head succeeded.", file=sys.stdout)
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)
