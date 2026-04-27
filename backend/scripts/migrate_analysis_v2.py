"""QORA Analysis v2 — Idempotent migration: create analysis tables + populate from JSON.

Creates three new tables:
  - call_analyses    (1:1 with call_sessions)
  - lead_profile_facts   (N per lead, append-and-supersede)
  - lead_interest_history (append-only per lead)

Then migrates existing data:
  - Reads call_sessions.extracted_facts JSON → inserts call_analyses rows
  - If lead_id is set → inserts lead_profile_facts + lead_interest_history rows
  - Skips sessions already present in call_analyses (idempotent)
  - Logs + skips sessions with malformed JSON without aborting

Reports final counts: processed, skipped (already migrated), errored.

Safe to run multiple times.

Usage:
    python scripts/migrate_analysis_v2.py
    python scripts/migrate_analysis_v2.py --db-url sqlite+aiosqlite:///./qora.db
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Table + index DDL constants
# ---------------------------------------------------------------------------

_CREATE_CALL_ANALYSES = """
CREATE TABLE IF NOT EXISTS call_analyses (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE REFERENCES call_sessions(id),
    lead_id TEXT REFERENCES leads(id),
    client_id TEXT NOT NULL REFERENCES clients(id),
    summary TEXT,
    interest_level INTEGER,
    classification TEXT,
    engagement_quality TEXT,
    outcome_reason TEXT,
    urgency TEXT,
    primary_need TEXT,
    next_action_suggested TEXT,
    current_insurance TEXT,
    data_corrections TEXT NOT NULL DEFAULT '',
    misc_notes TEXT NOT NULL DEFAULT '',
    objections TEXT NOT NULL DEFAULT '[]',
    products TEXT NOT NULL DEFAULT '[]',
    specific_needs TEXT NOT NULL DEFAULT '[]',
    buying_signals TEXT NOT NULL DEFAULT '[]',
    pain_points TEXT NOT NULL DEFAULT '[]',
    analyzed_at DATETIME NOT NULL,
    analysis_status TEXT NOT NULL DEFAULT 'ok',
    analysis_error TEXT
)
"""

_CREATE_LEAD_PROFILE_FACTS = """
CREATE TABLE IF NOT EXISTS lead_profile_facts (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    fact_key TEXT NOT NULL,
    fact_value TEXT NOT NULL,
    source_call_id TEXT REFERENCES call_sessions(id),
    recorded_at DATETIME NOT NULL,
    superseded_at DATETIME
)
"""

_CREATE_LEAD_INTEREST_HISTORY = """
CREATE TABLE IF NOT EXISTS lead_interest_history (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    interest_level INTEGER NOT NULL,
    source_call_id TEXT REFERENCES call_sessions(id),
    recorded_at DATETIME NOT NULL
)
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_call_analyses_session_id ON call_analyses(session_id)",
    "CREATE INDEX IF NOT EXISTS ix_call_analyses_lead_id ON call_analyses(lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_call_analyses_client_id ON call_analyses(client_id)",
    "CREATE INDEX IF NOT EXISTS ix_call_analyses_classification ON call_analyses(classification)",
    "CREATE INDEX IF NOT EXISTS ix_lead_profile_facts_lead_key_active ON lead_profile_facts(lead_id, fact_key, superseded_at)",
    "CREATE INDEX IF NOT EXISTS ix_lead_profile_facts_lead_id ON lead_profile_facts(lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_profile_facts_source_call_id ON lead_profile_facts(source_call_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_interest_history_lead_id ON lead_interest_history(lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_lead_interest_history_lead_recorded_at ON lead_interest_history(lead_id, recorded_at)",
]


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


def _parse_facts_json(raw_value) -> dict | None:
    """Parse extracted_facts from DB (may be dict already or JSON string).

    Returns None if the value is absent or cannot be parsed.
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return None  # malformed


def _safe_json_list(value) -> str:
    """Serialize a list to JSON string; return '[]' if None or not a list."""
    if isinstance(value, list):
        return json.dumps(value)
    if isinstance(value, str):
        # Try to parse it as JSON already
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return json.dumps(parsed)
        except (json.JSONDecodeError, ValueError):
            pass
    return "[]"


def _utcnow_str() -> str:
    """Return current UTC datetime as ISO string for SQLite storage."""
    return datetime.now(timezone.utc).isoformat()


def _build_call_analysis_row(
    session_id: str, lead_id: str | None, client_id: str, facts: dict
) -> dict:
    """Build a dict of column values for a call_analyses INSERT from a facts dict."""
    call_outcome = facts.get("call_outcome") or {}
    detected_interests = facts.get("detected_interests") or {}
    identified_problem = facts.get("identified_problem") or {}

    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "lead_id": lead_id,
        "client_id": client_id,
        "summary": facts.get("summary") or "",
        "interest_level": facts.get("interest_level"),
        "classification": call_outcome.get("classification"),
        "engagement_quality": call_outcome.get("engagement_quality"),
        "outcome_reason": call_outcome.get("reason"),
        "urgency": identified_problem.get("urgency"),
        "primary_need": identified_problem.get("primary_need"),
        "next_action_suggested": facts.get("next_action_suggested"),
        "current_insurance": facts.get("current_insurance"),
        "data_corrections": facts.get("data_corrections") or "",
        "misc_notes": facts.get("misc_notes") or "",
        "objections": _safe_json_list(facts.get("objections")),
        "products": _safe_json_list(detected_interests.get("products")),
        "specific_needs": _safe_json_list(detected_interests.get("specific_needs")),
        "buying_signals": _safe_json_list(detected_interests.get("buying_signals")),
        "pain_points": _safe_json_list(identified_problem.get("pain_points")),
        "analyzed_at": _utcnow_str(),
        "analysis_status": "ok",
        "analysis_error": None,
    }


def _build_lead_profile_fact_rows(
    lead_id: str, session_id: str, facts: dict
) -> list[dict]:
    """Build LeadProfileFact rows from a facts dict.

    Returns a list of fact dicts (id, lead_id, fact_key, fact_value, source_call_id, recorded_at, superseded_at).
    Append-only facts (objections, products, etc.) are skipped during migration
    since they would create duplicates on re-migration of JSON blobs.
    Only singular (upsert-style) facts are migrated.
    """
    rows = []
    now = _utcnow_str()

    call_outcome = facts.get("call_outcome") or {}
    identified_problem = facts.get("identified_problem") or {}

    _singular_facts = {
        "interest_level": str(facts["interest_level"])
        if facts.get("interest_level") is not None
        else None,
        "current_insurance": facts.get("current_insurance"),
        "next_action": facts.get("next_action_suggested"),
        "primary_need": identified_problem.get("primary_need"),
        "classification": call_outcome.get("classification"),
    }

    for fact_key, fact_value in _singular_facts.items():
        if fact_value is None:
            continue
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "lead_id": lead_id,
                "fact_key": fact_key,
                "fact_value": str(fact_value),
                "source_call_id": session_id,
                "recorded_at": now,
                "superseded_at": None,
            }
        )

    return rows


def _build_interest_history_row(
    lead_id: str, session_id: str, facts: dict
) -> dict | None:
    """Build a LeadInterestHistory row from facts. Returns None if interest_level absent."""
    interest_level = facts.get("interest_level")
    if interest_level is None:
        return None
    return {
        "id": str(uuid.uuid4()),
        "lead_id": lead_id,
        "interest_level": int(interest_level),
        "source_call_id": session_id,
        "recorded_at": _utcnow_str(),
    }


# ---------------------------------------------------------------------------
# Core migration function
# ---------------------------------------------------------------------------


async def run_migration(database_url: str) -> dict:
    """Run the analysis v2 migration idempotently.

    Creates the 3 new tables + indexes if they don't exist, then migrates
    existing call_sessions.extracted_facts JSON data into the new tables.

    Args:
        database_url: SQLAlchemy async database URL.

    Returns:
        Dict with counts: {"processed": N, "skipped": N, "errored": N}
    """
    import sqlalchemy
    from sqlalchemy.ext.asyncio import create_async_engine

    print(f"Connecting to: {database_url}")
    engine = create_async_engine(database_url, echo=False)

    processed = 0
    skipped = 0
    errored = 0

    async with engine.begin() as conn:
        # ------------------------------------------------------------------
        # 1. Create tables (IF NOT EXISTS — idempotent)
        # ------------------------------------------------------------------
        print("\nCreating analysis tables (if not exists)...")
        await conn.execute(sqlalchemy.text(_CREATE_CALL_ANALYSES))
        print("  [ok] call_analyses")
        await conn.execute(sqlalchemy.text(_CREATE_LEAD_PROFILE_FACTS))
        print("  [ok] lead_profile_facts")
        await conn.execute(sqlalchemy.text(_CREATE_LEAD_INTEREST_HISTORY))
        print("  [ok] lead_interest_history")

        for idx_sql in _INDEXES:
            await conn.execute(sqlalchemy.text(idx_sql))
        print(f"  [ok] {len(_INDEXES)} indexes ensured")

        # ------------------------------------------------------------------
        # 2. Load all call_sessions with extracted_facts (not null)
        # ------------------------------------------------------------------
        print("\nLoading call sessions...")
        sessions_result = await conn.execute(
            sqlalchemy.text(
                "SELECT id, lead_id, client_id, extracted_facts "
                "FROM call_sessions "
                "WHERE extracted_facts IS NOT NULL"
            )
        )
        sessions = sessions_result.fetchall()
        print(f"  Found {len(sessions)} sessions with extracted_facts")

        # ------------------------------------------------------------------
        # 3. Process each session
        # ------------------------------------------------------------------
        print("\nMigrating sessions...")
        for row in sessions:
            session_id, lead_id, client_id, raw_facts = row

            # Skip if already migrated (idempotency guard)
            existing = await conn.execute(
                sqlalchemy.text("SELECT id FROM call_analyses WHERE session_id = :sid"),
                {"sid": session_id},
            )
            if existing.fetchone() is not None:
                skipped += 1
                print(f"  [skip] session={session_id!r} already in call_analyses")
                continue

            # Parse extracted_facts JSON (defensive)
            facts = _parse_facts_json(raw_facts)
            if facts is None:
                errored += 1
                print(
                    f"  [error] session={session_id!r} — malformed extracted_facts, skipping"
                )
                continue

            # Skip partial-analysis marker records
            if facts.get("_analysis_status") == "failed":
                errored += 1
                print(
                    f"  [error] session={session_id!r} — analysis_status=failed marker, skipping"
                )
                continue

            try:
                # Insert call_analyses row
                ca_row = _build_call_analysis_row(session_id, lead_id, client_id, facts)
                await conn.execute(
                    sqlalchemy.text(
                        """
                        INSERT INTO call_analyses
                            (id, session_id, lead_id, client_id, summary, interest_level,
                             classification, engagement_quality, outcome_reason, urgency,
                             primary_need, next_action_suggested, current_insurance,
                             data_corrections, misc_notes, objections, products,
                             specific_needs, buying_signals, pain_points,
                             analyzed_at, analysis_status, analysis_error)
                        VALUES
                            (:id, :session_id, :lead_id, :client_id, :summary, :interest_level,
                             :classification, :engagement_quality, :outcome_reason, :urgency,
                             :primary_need, :next_action_suggested, :current_insurance,
                             :data_corrections, :misc_notes, :objections, :products,
                             :specific_needs, :buying_signals, :pain_points,
                             :analyzed_at, :analysis_status, :analysis_error)
                        """
                    ),
                    ca_row,
                )

                # Insert lead tables only when lead_id is set
                if lead_id:
                    lpf_rows = _build_lead_profile_fact_rows(lead_id, session_id, facts)
                    for lpf_row in lpf_rows:
                        await conn.execute(
                            sqlalchemy.text(
                                """
                                INSERT INTO lead_profile_facts
                                    (id, lead_id, fact_key, fact_value, source_call_id,
                                     recorded_at, superseded_at)
                                VALUES
                                    (:id, :lead_id, :fact_key, :fact_value, :source_call_id,
                                     :recorded_at, :superseded_at)
                                """
                            ),
                            lpf_row,
                        )

                    lih_row = _build_interest_history_row(lead_id, session_id, facts)
                    if lih_row:
                        await conn.execute(
                            sqlalchemy.text(
                                """
                                INSERT INTO lead_interest_history
                                    (id, lead_id, interest_level, source_call_id, recorded_at)
                                VALUES
                                    (:id, :lead_id, :interest_level, :source_call_id, :recorded_at)
                                """
                            ),
                            lih_row,
                        )

                processed += 1
                print(f"  [ok] session={session_id!r} lead_id={lead_id!r}")

            except Exception as exc:
                errored += 1
                print(f"  [error] session={session_id!r} — {exc}")

    await engine.dispose()

    summary = {"processed": processed, "skipped": skipped, "errored": errored}
    print(
        f"\nMigration complete: processed={processed}, skipped={skipped}, errored={errored}"
    )
    return summary


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="QORA Analysis v2 — Create analysis tables and migrate existing data"
    )
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./qora.db",
        help="SQLAlchemy async database URL (default: sqlite+aiosqlite:///./qora.db)",
    )
    args = parser.parse_args()

    try:
        result = asyncio.run(run_migration(args.db_url))
        print(f"Result: {result}")
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
