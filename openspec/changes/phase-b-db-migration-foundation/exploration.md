# Exploration: Phase B Database Migration Foundation

## Current State

Qora manages schema evolution through **two parallel mechanisms**, neither of which provides version tracking, ordering guarantees, or rollback:

### Mechanism 1: Startup DDL Patches (`_ensure_startup_schema_compat`)

**File**: `backend/app/main.py` (lines 53–333, ~280 lines of raw SQL)

On every application startup, the lifespan handler calls `_ensure_startup_schema_compat()`, which:

1. Reads `PRAGMA table_info(...)` for `clients`, `agents`, and `leads` tables.
2. Checks if each expected column exists.
3. Runs `ALTER TABLE ... ADD COLUMN` for any missing column.
4. Creates the `lead_custom_fields` table via `CREATE TABLE IF NOT EXISTS`.
5. Runs a one-time data migration from legacy lead columns to `lead_custom_fields` (guarded by a sentinel marker row).

**Current column count managed by startup patches**: ~16 ALTER TABLEs + 1 CREATE TABLE + 1 data migration.

This function has grown from 2 columns (Phase 7) to 16+ columns across multiple features. It is effectively a "migration system" that runs on every startup, with no ordering, no version record, and no way to know which patches have been applied except by re-inspecting the schema each time.

### Mechanism 2: Standalone Migration Scripts (`backend/scripts/`)

**Path**: `backend/scripts/migrate_*.py` (14 scripts)

Each script is an independently runnable Python file that uses either `aiosqlite` (async) or raw `sqlite3` to apply schema changes. Scripts are:

| Script | Method | Rollback | Ordering |
|--------|--------|----------|----------|
| `migrate_phase2.py` | async SQLAlchemy | No | None |
| `migrate_session_reconciliation.py` | async SQLAlchemy | No | None |
| `migrate_lead_id_nullable.py` | raw sqlite3 (table rebuild) | No | None |
| `migrate_analysis_v2.py` | async SQLAlchemy | No | None |
| `migrate_extraction_v2.py` | async SQLAlchemy | No | None |
| `migrate_call_scheduler.py` | async SQLAlchemy | No | None |
| `migrate_add_agents.py` | async SQLAlchemy + seed | No | Depends on clients |
| `migrate_add_agent_id_fks.py` | async SQLAlchemy | No | Depends on agents |
| `migrate_analysis_language.py` | async SQLAlchemy | No | None |
| `migrate_bi_columns.py` | async SQLAlchemy + backfill | No | Depends on call_analyses |
| `migrate_data_corrections.py` | async SQLAlchemy | No | None |
| `migrate_drop_engagement_quality.py` | async SQLAlchemy | No | None |
| `migrate_next_action_engine.py` | async SQLAlchemy | No | None |
| `migrate_abandonment_to_outcome.py` | async SQLAlchemy | No | None |

Scripts share common patterns (column_exists check, add_column_if_missing) but each re-implements them locally. No script records that it has run. Idempotency is achieved by checking schema state, not by tracking migration history.

### Mechanism 3: `Base.metadata.create_all`

**File**: `backend/app/core/database.py` (line 78)

Called during `init_db()` before the startup compat patches. Creates any **entirely missing tables** (e.g., if a new model module is added). Does NOT alter existing tables — if a column is added to a model, `create_all` silently ignores the mismatch.

### How They Interact (Startup Sequence)

```
1. init_db(settings)
   └── import all model modules (registers with Base.metadata)
   └── create_all()  ← creates missing TABLES only
   └── PRAGMA journal_mode=WAL, busy_timeout=5000

2. _ensure_startup_schema_compat()
   └── PRAGMA table_info() for each table
   └── ALTER TABLE ADD COLUMN for each missing column
   └── CREATE TABLE IF NOT EXISTS for lead_custom_fields
   └── Data migration for legacy lead columns

3. seed_quintana / seed_qora_demo / seed_leads
   └── ORM queries that depend on ALL columns existing
```

The seed step (3) will crash if a column declared in the ORM model is not present in the actual database — which is why `_ensure_startup_schema_compat` exists as a safety net.

### What's NOT in the Startup Path

The 14 scripts in `backend/scripts/` are **never called automatically**. A developer must know which scripts to run, in what order, after pulling new code. There is no documentation of which scripts are needed for a given version, and no tracking of which have been applied.

## Affected Areas

- `backend/app/main.py` — The 280-line `_ensure_startup_schema_compat()` function grows with every schema change and mixes DDL with data migration logic.
- `backend/app/core/database.py` — `init_db()` calls `create_all()` which creates tables for fresh DBs but cannot handle schema drift for existing DBs.
- `backend/scripts/migrate_*.py` (14 files) — Ad-hoc migration scripts with no ordering, no version tracking, no shared utilities.
- `backend/app/tenants/models.py` — ORM model declarations (Agent: 22 columns, Client: 19 columns) that must stay in sync with the actual schema.
- `backend/app/leads/models.py` — Lead model (20+ columns), LeadProfileFact, LeadCustomField, LeadInterestHistory.
- `backend/app/calls/models.py` — CallSession (16 columns), TranscriptTurn, CallAnalysis (28 columns).
- `backend/app/scheduler/models.py` — ScheduledCall (12 columns).
- `backend/qora.db` — The actual SQLite database file (736K).

## Why the Current Approach Is Risky for Production

### Risk 1: Silent Schema Drift

`create_all()` creates tables from the ORM model, but existing tables are never altered. If a developer adds a column to the model and forgets to update `_ensure_startup_schema_compat`, the app starts fine on a fresh DB but crashes on an existing one. This has already happened multiple times (hence the 16+ patches in the startup function).

### Risk 2: No Migration History

There is no record of which migrations have been applied to a given database. A developer cannot look at a DB and know its schema version. The only way to check is to inspect every column of every table — which is exactly what the startup function does on every boot.

### Risk 3: Ordering Dependencies Are Implicit

`migrate_add_agent_id_fks.py` depends on `migrate_add_agents.py` having run first (it references the agents table). This dependency is not encoded anywhere. Running scripts in the wrong order causes failures that look like bugs.

### Risk 4: No Rollback Path

All 14 scripts and all startup patches are forward-only. If a migration corrupts data or introduces a bug, the only option is to restore from a backup (if one exists) or manually reverse the changes.

### Risk 5: Startup Function Is a Deployment Landmine

`_ensure_startup_schema_compat` runs on every startup, including production restarts, health-check containers, and test runs. It does raw DDL in a single transaction. If it fails mid-way, the database may be left in a partially migrated state. The function is 280+ lines with no test coverage.

### Risk 6: Two Conflicting Migration Styles

Some changes go into the startup function (because they're needed before seeding), others go into standalone scripts (because they're too complex or include backfills). There's no rule for which approach to use, leading to a growing split-brain problem.

### Risk 7: Table Rebuilds Are Data-Loss Risks

`migrate_lead_id_nullable.py` does a table rebuild (rename → create → copy → drop) using raw `sqlite3`. If the column list in the script doesn't match the actual table (because another migration added columns), data is silently lost. This rebuild pattern has no column-set validation.

## Approaches

### 1. Alembic (SQLAlchemy's Migration Tool) — Recommended

Alembic is the standard migration tool for SQLAlchemy. It auto-generates migration scripts by comparing the ORM model to the database schema, tracks applied migrations in a `alembic_version` table, and supports rollback (downgrade).

- **Pros**:
  - Auto-detects schema differences between ORM models and the DB.
  - Built-in version tracking (`alembic_version` table).
  - Supports SQLite (with some caveats around ALTER TABLE — uses batch mode for table rebuilds).
  - Well-documented, large community, first-party SQLAlchemy integration.
  - `alembic upgrade head` is a single command for any DB state.
  - Plays well with both SQLite and PostgreSQL (when/if that transition happens later).
  - Can wrap the existing 14 scripts into a baseline migration.
  - Supports offline mode (generate SQL without running it).
  - Supports branching/merging for parallel development.
- **Cons**:
  - New dependency (`alembic`).
  - SQLite batch mode requires extra configuration for ALTER TABLE operations.
  - Learning curve for the team (but the tool is standard Python/SQLAlchemy).
  - Need to create a baseline migration from the current schema.
- **Effort**: Medium

### 2. Lightweight Custom Migration Runner

Build a minimal migration system: numbered SQL/Python files in a directory, a `_migrations` table tracking applied versions, and a `migrate` CLI command that applies pending migrations in order.

- **Pros**:
  - Zero external dependencies.
  - Full control over behavior.
  - Simple to understand.
  - Could be done in ~200 lines of Python.
- **Cons**:
  - Reinvents the wheel (Alembic already does this, better).
  - No auto-generation from ORM models — all migrations are hand-written.
  - No downgrade/rollback support unless built manually.
  - No community support or documentation.
  - Must handle SQLite ALTER TABLE limitations manually.
  - Will need to be extended as requirements grow (branching, data migrations, etc.).
- **Effort**: Medium (initial), High (ongoing maintenance)

### 3. Yoyo Migrations

A lightweight Python migration tool that runs numbered SQL or Python scripts with up/down support.

- **Pros**:
  - Lighter than Alembic.
  - Supports rollback.
  - Works with raw SQL (no ORM coupling).
- **Cons**:
  - No ORM model auto-detection (all migrations are manual).
  - Smaller community than Alembic.
  - No SQLAlchemy-specific features (batch mode, type reflection).
  - Would still need manual work to sync with the ORM models.
  - Adds a dependency with less ecosystem support.
- **Effort**: Medium

## Recommendation

**Alembic** is the clear choice. Reasons:

1. **It's the standard tool for SQLAlchemy projects.** Qora already uses SQLAlchemy 2.0 async — Alembic is the first-party migration companion. Every tutorial, blog post, and Stack Overflow answer for SQLAlchemy migrations uses Alembic.

2. **Auto-generation eliminates drift.** Running `alembic revision --autogenerate` compares the ORM models to the DB and generates migration scripts for any differences. This eliminates the entire class of "forgot to update the startup function" bugs.

3. **SQLite is fully supported.** Alembic's batch mode handles SQLite's ALTER TABLE limitations (no DROP COLUMN, no ALTER COLUMN) by doing the rename-copy-drop pattern automatically and safely.

4. **Future-proof for PostgreSQL.** When Phase B eventually considers PostgreSQL (not in this slice), Alembic migrations work identically across both databases. The same migration files apply to both.

5. **Baseline migration is straightforward.** We create a single baseline migration that represents the current schema state, mark it as applied on existing DBs, and all new changes go through Alembic from that point on.

## File Organization Recommendation

```
backend/
├── alembic.ini                  ← Alembic config (DB URL, script location)
├── alembic/                     ← Alembic migration environment
│   ├── env.py                   ← Migration runner (async engine config)
│   ├── script.py.mako           ← Template for new migration files
│   └── versions/                ← Ordered migration scripts
│       ├── 001_baseline.py      ← Snapshot of current schema (all tables)
│       └── 002_*.py             ← Future migrations
├── scripts/                     ← KEEP existing scripts (read-only archive)
│   └── migrate_*.py             ← Mark as deprecated, do not delete yet
└── app/
    ├── core/
    │   └── database.py          ← Remove create_all() from init_db()
    └── main.py                  ← Remove _ensure_startup_schema_compat()
```

**Key decisions:**

| Decision | Choice | Why |
|----------|--------|-----|
| Config location | `backend/alembic.ini` | Same level as `pyproject.toml`, standard placement |
| Migrations directory | `backend/alembic/versions/` | Alembic convention; inside backend since that's the Python package |
| Old scripts | Keep in `backend/scripts/`, add deprecation header | Audit trail; deletion can happen in a later cleanup slice |
| `create_all()` | Replace with `alembic upgrade head` | Alembic handles both fresh and existing DBs |
| Startup compat function | Remove entirely after baseline | Alembic's version tracking eliminates the need for runtime schema inspection |

## Safe Local-First Rollout Plan

### Step 1: Baseline Migration (Fresh + Existing DBs)

1. Initialize Alembic: `alembic init alembic` (generates `alembic.ini`, `alembic/env.py`, etc.)
2. Configure `env.py` for async SQLAlchemy + SQLite batch mode.
3. Generate a baseline migration that captures the **current complete schema** (all 10 tables, all columns, all indexes, all constraints).
4. For **existing DBs**: stamp the baseline as applied without running it (`alembic stamp head`). The schema is already correct — we're just recording that fact.
5. For **fresh DBs**: `alembic upgrade head` creates everything from scratch. No more `create_all()`.

### Step 2: Verification Checks

| Check | How | Passes when |
|-------|-----|-------------|
| Fresh DB works | Delete `qora.db`, run `alembic upgrade head`, start app | App starts, seeds run, health check passes |
| Existing DB works | Keep current `qora.db`, run `alembic stamp head`, start app | App starts with all existing data intact |
| Schema match | Compare `PRAGMA table_info(*)` before and after | All columns, types, and constraints match |
| Seed data intact | Query clients, agents, leads after stamp+start | All existing records present |

### Step 3: Remove Startup Compat Function

After the baseline migration is verified:
1. Remove `_ensure_startup_schema_compat()` from `main.py`.
2. Remove `create_all()` from `database.py:init_db()`.
3. Add `alembic upgrade head` to the startup sequence (or make it a pre-start command in Docker).
4. Verify the app still starts correctly on both fresh and existing DBs.

### Step 4: First Real Migration

Create a small, low-risk migration to prove the system works end-to-end:
- Candidate: add `broker_name` column to `clients` (it exists in the model but may be handled by startup compat) or add a missing index.
- Run `alembic revision --autogenerate -m "add_missing_index"`.
- Review the generated migration.
- Apply with `alembic upgrade head`.
- Verify.

### Step 5: Deprecate Old Scripts

Add a deprecation header to each file in `backend/scripts/migrate_*.py`:
```python
# DEPRECATED: This script pre-dates Alembic. Schema changes now go through
# alembic/versions/. This file is kept for audit/history only. Do not run.
```

## Risks

- **Baseline schema capture must be exact.** If the baseline migration doesn't match the actual schema of existing DBs, `alembic stamp head` will record a false state. Mitigation: generate the baseline from the ORM models (which match the startup compat function's intended end state), then verify against the actual DB schema.
- **SQLite batch mode complexity.** Some existing migrations (like `migrate_lead_id_nullable.py`) do table rebuilds. Alembic's batch mode handles this, but the generated code is more complex than simple `ALTER TABLE`. Mitigation: test table rebuild migrations on a copy of the production DB.
- **Async engine configuration.** Alembic's `env.py` needs to be configured for `aiosqlite` async engine. This is well-documented but requires careful setup. Mitigation: follow the SQLAlchemy async Alembic cookbook.
- **Team learning curve.** Developers need to learn `alembic revision --autogenerate`, `alembic upgrade head`, and how to review generated migrations. Mitigation: include a `docs/MIGRATIONS.md` guide with the implementation.
- **Data migration in Alembic.** Some existing scripts do data backfills (e.g., `migrate_bi_columns.py` parses JSON and writes derived columns). Alembic supports data migrations, but they require more care than DDL-only migrations. Mitigation: separate DDL and data migration steps within each revision.

## Non-Goals

- **PostgreSQL migration.** This slice introduces the migration framework while keeping SQLite as the primary database. PostgreSQL is a separate Phase B item (B3).
- **Removing deprecated Client columns.** The deprecated agent-config columns on Client (agent_name, voice_id, model, etc.) are a cleanup task, not a migration framework task.
- **Removing legacy V1 models.** `app/db/models.py` (if it still exists) is a separate cleanup.
- **Background job durability.** Phase B item B10, not related to schema migration.
- **Authentication or CORS.** Phase B items B5/B7, separate slices.

## Review Workload Forecast

| Work unit | Estimated lines changed | Notes |
|-----------|------------------------|-------|
| Alembic init + config (`alembic.ini`, `env.py`, `script.py.mako`) | ~80 | Boilerplate, mostly generated |
| Baseline migration (`001_baseline.py`) | ~200 | All 10 tables, generated from ORM models |
| Update `database.py` (remove `create_all`) | ~15 | Small deletion + add `alembic upgrade head` |
| Update `main.py` (remove startup compat) | ~-280 (deletion) | Large deletion, net negative lines |
| Deprecation headers on `scripts/migrate_*.py` | ~14 × 3 = ~42 | Comment additions only |
| `docs/MIGRATIONS.md` helper guide | ~60 | Developer guide for the new workflow |
| `pyproject.toml` dependency addition | ~2 | Add `alembic` |

**Total estimated**: ~400 additions, ~280 deletions = ~680 changed lines.

**800-line budget risk**: **Medium**. The raw line count is within the 800-line review budget, but the baseline migration file will be large (schema snapshot). The deletion of `_ensure_startup_schema_compat` is a large but simple removal.

**Split recommendation**: This can be delivered as a **single PR** if the baseline migration is treated as generated/reviewed-lightly (schema snapshot). If the team prefers smaller PRs:

- **PR 1** (~200 lines): Alembic init + baseline migration + `alembic stamp head` support. No behavior change — the old startup compat function still runs.
- **PR 2** (~400 lines): Remove `_ensure_startup_schema_compat`, remove `create_all`, add `alembic upgrade head` to startup, deprecate old scripts, add docs.

A two-PR split is safer because PR 1 is purely additive (no risk) and PR 2 is the behavioral change (higher risk but well-tested by that point).

## Ready for Proposal

Yes. The exploration is complete with clear recommendation (Alembic), concrete file organization, safe rollout plan, and workload estimate. The orchestrator should proceed to the proposal phase for `phase-b-db-migration-foundation`.
