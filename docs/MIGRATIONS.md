# QORA — Database Migration Guide

Qora uses [Alembic](https://alembic.sqlalchemy.org/) for all schema management.
This guide covers the everyday migration workflow for developers.

**Estimated reading time: ~3 minutes.**

---

## Quick Reference

```bash
# Before starting the app (done automatically by `./Qora`):
cd backend && python scripts/migrate.py

# Create a new migration:
cd backend && alembic revision --autogenerate -m "add column foo to leads"

# Apply pending migrations:
cd backend && alembic upgrade head

# Check current version:
cd backend && alembic current

# Show migration history:
cd backend && alembic history

# Roll back one migration:
cd backend && alembic downgrade -1
```

---

## How It Works

The pre-start migration command runs **before** the FastAPI process:

```
python scripts/migrate.py   →   alembic upgrade head   →   uvicorn app.main:app
```

`scripts/migrate.py` handles all three cases safely:

| DB state | Action taken |
|---|---|
| No DB file | `alembic upgrade head` — creates full schema from scratch |
| Existing, already stamped | `alembic upgrade head` — idempotent no-op at head, or applies pending migrations |
| Existing, not stamped, Qora-compatible | `alembic stamp head` — records baseline without running DDL (preserves all data) |
| Existing, not stamped, incompatible schema | `RuntimeError` — fails safely; manual intervention required |

The local launcher (`./Qora` script) calls `python scripts/migrate.py` automatically before starting uvicorn.

---

## Backup Before Any Migration

Always back up the SQLite DB before running new migrations against production data:

```bash
cp backend/qora.db backend/qora.db.bak-$(date +%Y%m%d)
```

Restore from backup (if anything goes wrong):

```bash
cp backend/qora.db.bak-YYYYMMDD backend/qora.db
```

SQLite's single-file format means `cp` is the entire restore operation. No pg_restore needed.

---

## Creating a New Migration

1. **Update the ORM model** — add or change columns in `backend/app/*/models.py`
2. **Generate the migration** with autogenerate:
   ```bash
   cd backend
   alembic revision --autogenerate -m "add foo_column to leads"
   ```
3. **Review the generated file** in `backend/alembic/versions/`. Check:
   - Columns match the ORM model exactly (type, nullable, default)
   - `downgrade()` reverses the `upgrade()` correctly
   - No unintended table drops or data changes
4. **Test locally** on a fresh DB:
   ```bash
   cd backend
   python scripts/migrate.py    # applies the new migration
   alembic current              # verify: shows new revision
   ```
5. **Run the test suite** to confirm no regressions:
   ```bash
   cd backend && python3 -m pytest tests/ -q
   ```

### SQLite ALTER TABLE Limitation

SQLite does not support `DROP COLUMN` or `ALTER COLUMN`. Alembic handles this automatically via **batch mode** (`render_as_batch=True` in `alembic/env.py`), which rebuilds the table behind the scenes.

---

## Applying Migrations (Upgrade)

```bash
cd backend
alembic upgrade head        # apply all pending migrations to head
alembic upgrade +1          # apply exactly one migration forward
alembic upgrade 20241201    # apply up to a specific revision
```

The `./Qora` launcher runs `python scripts/migrate.py` (equivalent to `alembic upgrade head`) before starting uvicorn.

---

## Rolling Back (Downgrade)

```bash
cd backend
alembic downgrade -1        # revert the most recent migration
alembic downgrade base      # revert all migrations (empty DB — destructive!)
```

> **Warning**: `downgrade base` drops all Qora tables. Always have a backup.

Rollback plan per stage:

| Stage | Action | Time |
|---|---|---|
| Before stamp (PR 1 not merged) | Restore `qora.db.bak`; no code change | < 1 min |
| After stamp (PR 1 merged) | Restore `qora.db.bak`; `git revert` PR 1 | < 3 min |
| After cutover (PR 2 merged) | Restore `qora.db.bak`; `git revert` PR 2 | < 5 min |
| Nuclear | Restore backup + `git revert` all migration commits | < 5 min |

---

## Stamping an Existing Database

If you have an existing `qora.db` that predates Alembic (produced by the old `create_all` path), `scripts/migrate.py` detects and stamps it automatically:

```bash
cd backend && python scripts/migrate.py
# Output: "Detected existing unstamped Qora-compatible DB at ... Stamping head (no DDL will run)."
```

If the DB is not Qora-compatible (partial or unrelated schema), the script fails safely with a clear error. Fix the schema or point to an empty DB before running again.

To stamp manually:
```bash
cd backend && alembic stamp head
```

---

## Checking for Schema Drift (Autogenerate)

After updating ORM models, verify the migration captures all changes:

```bash
cd backend
alembic revision --autogenerate -m "check drift"
# Review the generated file — empty upgrade() means no drift
```

---

## Deprecated Migration Scripts

The `backend/scripts/migrate_*.py` files (14 total) are **deprecated**. They were the previous schema management approach (individual idempotent ALTER TABLE scripts). They are kept for audit trail only.

**Do NOT run them against production databases.** All schema changes are now managed via:

```bash
python scripts/migrate.py   # or: alembic upgrade head
```

The deprecated scripts:

| Script | What it did |
|---|---|
| `migrate_phase2.py` | Added Phase 2 columns to `call_sessions` and `leads` |
| `migrate_lead_id_nullable.py` | Made `call_sessions.lead_id` nullable |
| `migrate_session_reconciliation.py` | Added `merged_into_session_id` to `call_sessions` |
| `migrate_call_scheduler.py` | Created `scheduled_calls` table (Phase 6) |
| `migrate_analysis_v2.py` | Created `call_analyses` and `transcript_turns` tables |
| `migrate_extraction_v2.py` | Added extraction axes columns to `call_analyses` and `clients` |
| `migrate_add_agents.py` | Created `agents` table + seeded default agents |
| `migrate_add_agent_id_fks.py` | Added `agent_id` FK columns and backfilled data |
| `migrate_data_corrections.py` | Added `email` and `age` to `leads` |
| `migrate_drop_engagement_quality.py` | Dropped `engagement_quality` from `call_analyses` |
| `migrate_abandonment_to_outcome.py` | Added `was_abrupt` and `abandonment_trigger` columns |
| `migrate_next_action_engine.py` | Added next-action columns to `clients` |
| `migrate_analysis_language.py` | Added `analysis_language` to `clients` |
| `migrate_bi_columns.py` | Added BI denormalization columns to `call_analyses` |

All of these are now superseded by the Alembic baseline migration (`backend/alembic/versions/20241201_0001_baseline.py`) which captures the full schema at Phase B foundation.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///%(here)s/qora.db` | Override the DB location. Applied by both `scripts/migrate.py` and `alembic/env.py` before any operations. |

Example for a custom test DB:
```bash
DATABASE_URL="sqlite+aiosqlite:////tmp/test.db" python scripts/migrate.py
```
