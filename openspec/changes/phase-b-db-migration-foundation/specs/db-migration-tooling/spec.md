# db-migration-tooling Specification

## Purpose

Define the behavioral contract for replacing Qora's ad-hoc schema management (startup DDL patches + 14 ad-hoc scripts) with Alembic-based ordered migration tooling. This spec covers backup safety, schema inventory, migration infrastructure, startup integration, test alignment, core workflow protection, and rollback.

---

## Requirements

### Requirement: Baseline Backup and Verification

Before any step that touches the database, the system MUST produce a timestamped backup and verify its integrity.

The operator MUST copy `backend/qora.db` to `backend/qora.db.bak-{YYYYMMDD}` before the first DB-touching step. The backup MUST be verified as readable (non-zero size, openable with `sqlite3`). No migration step SHALL proceed if a readable backup does not exist.

#### Scenario: Backup created successfully

- GIVEN the operator is about to run schema work for the first time
- WHEN they execute the backup procedure
- THEN a file `backend/qora.db.bak-{YYYYMMDD}` exists with the same byte count as `backend/qora.db`
- AND the file opens cleanly via `sqlite3 backend/qora.db.bak-{YYYYMMDD} ".tables"`

#### Scenario: Backup absent — work blocked

- GIVEN no `backend/qora.db.bak-*` file exists for the current date
- WHEN a developer attempts any DB-touching step (stamp, upgrade, DDL removal)
- THEN the step is blocked and the error identifies the missing backup

---

### Requirement: Schema Inventory and Classification

Before removing or omitting any schema element, the system MUST produce a classified inventory of all current tables and columns. No schema element SHALL be removed without proof of non-use and safe migration.

Each schema element MUST be classified as one of:

| Class | Meaning |
|-------|---------|
| `active` | Used by at least one core Qora workflow |
| `compatibility` | Present for backward compatibility; deprecated but not yet provably unused |
| `candidate-unused` | No active reference found; safe for removal only after verification |

The baseline migration MUST include ALL `active` and `compatibility` elements. `candidate-unused` elements MUST NOT be omitted without an explicit removal migration with documented justification.

#### Scenario: Active schema preserved in baseline

- GIVEN the schema inventory classifies a column as `active`
- WHEN the baseline migration is generated and applied to a fresh DB
- THEN that column exists in the fresh DB with the same type and constraints as the source DB

#### Scenario: Compatibility schema preserved in baseline

- GIVEN a column is classified as `compatibility` (e.g., deprecated Client columns)
- WHEN the baseline migration is generated
- THEN that column is included in the baseline — not omitted, not renamed

#### Scenario: Candidate-unused element not silently dropped

- GIVEN a column is classified as `candidate-unused`
- WHEN preparing the baseline migration
- THEN the column is either included in the baseline OR a separate, justified removal migration is authored — never silently dropped

---

### Requirement: Alembic Migration Tooling Setup

The system MUST provide an Alembic environment configured for async SQLAlchemy with SQLite batch mode.

Required artifacts: `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`, and `backend/alembic/versions/`. The environment MUST support `alembic upgrade head`, `alembic downgrade`, `alembic revision --autogenerate`, and `alembic stamp`.

#### Scenario: Alembic commands execute without error

- GIVEN Alembic is initialized and `alembic.ini` points to the correct DB URL
- WHEN `alembic history` is run
- THEN it exits 0 and lists at least `001_baseline` in the revision chain

#### Scenario: Autogenerate detects ORM drift

- GIVEN a column is added to an ORM model but not yet in the DB
- WHEN `alembic revision --autogenerate -m "test"` runs
- THEN the generated script contains an `add_column` operation for that column

---

### Requirement: Baseline Migration Captures Full Schema

The system MUST provide a baseline migration (`001_baseline.py`) that captures the complete current schema with zero drift from the actual database.

The baseline MUST cover all tables, columns, types, nullable constraints, defaults, foreign keys, unique constraints, and indexes present in `qora.db`. Before stamping, the operator MUST verify the baseline via `PRAGMA table_info(*)` diff: all counts and types for all tables MUST match.

#### Scenario: Fresh DB from baseline matches production schema

- GIVEN a clean environment with no `qora.db`
- WHEN `alembic upgrade head` runs
- THEN all tables exist with the correct columns, types, and constraints
- AND `PRAGMA table_info(*) `output is identical to that of the backed-up production DB

#### Scenario: Baseline drift detected and blocked

- GIVEN `PRAGMA table_info(*)` comparison reveals a column present in production but absent from the baseline
- WHEN the reviewer inspects the diff
- THEN the baseline is corrected before any stamp or PR merge proceeds

---

### Requirement: Existing DB Stamp Path (No Data Loss)

The system MUST provide a path to record the baseline migration as applied on existing databases without re-running DDL, preserving all existing data.

`alembic stamp head` MUST write exactly one row to the `alembic_version` table. After stamping, `alembic current` MUST report `001_baseline (head)`. No existing table, column, row, or index SHALL be modified by the stamp operation.

#### Scenario: Stamp succeeds on populated database

- GIVEN `backend/qora.db` contains production data (clients, agents, leads, calls)
- WHEN `alembic stamp head` runs
- THEN `alembic_version` contains the `001_baseline` revision ID
- AND all existing rows are intact when queried after the stamp

#### Scenario: Stamp is idempotent

- GIVEN `alembic_version` already records `001_baseline`
- WHEN `alembic stamp head` is run again
- THEN it completes without error and no data is modified

---

### Requirement: Pre-Start Migration Execution

The system MUST execute `alembic upgrade head` before the FastAPI application accepts requests, using the pre-start command model (not inside the FastAPI lifespan event handler).

`alembic upgrade head` MUST be the sole migration entry point. `Base.metadata.create_all()` MUST NOT be called in `init_db()`. `_ensure_startup_schema_compat()` MUST NOT be called in the startup path. A pre-start script or Procfile/Docker entry point MUST invoke `alembic upgrade head` before the application process starts.

#### Scenario: Fresh DB created end-to-end via pre-start

- GIVEN no `qora.db` exists
- WHEN the pre-start command runs followed by the application process
- THEN all tables are created, seeders execute successfully, and the application health check passes

#### Scenario: Pre-start on already-current DB is a no-op

- GIVEN `alembic_version` records `head`
- WHEN the pre-start command runs
- THEN `alembic upgrade head` exits 0 with no DDL executed, and the application starts normally

---

### Requirement: Removal of Legacy Schema Management Code

`_ensure_startup_schema_compat()` and `Base.metadata.create_all()` MUST be removed from the active codebase only after both the fresh-DB path and the existing-DB stamp path have been verified green.

Removal MUST be a separate commit or PR from Alembic initialization (PR 2 after PR 1 is verified). The 14 scripts in `backend/scripts/migrate_*.py` MUST receive a `# DEPRECATED` header but MUST NOT be deleted in this slice.

#### Scenario: Startup compat removed after verification gate

- GIVEN both fresh-DB and existing-DB verification have passed
- WHEN `_ensure_startup_schema_compat()` is removed from `main.py`
- THEN no import or call to the function exists in the active codebase
- AND `grep -r "_ensure_startup_schema_compat" backend/app` returns no results

#### Scenario: Deprecated scripts are marked, not deleted

- GIVEN the 14 migration scripts in `backend/scripts/`
- WHEN this slice is complete
- THEN each file begins with a `# DEPRECATED` comment block
- AND no script file is absent from the repository

---

### Requirement: Test Path Alignment with Migrations

Integration tests that create or interact with the database MUST use `alembic upgrade head` to build the schema, not `Base.metadata.create_all()`. Tests MUST NOT diverge from the production schema management path.

Each test run MUST create a fresh isolated DB and apply `alembic upgrade head` before any ORM query. Test teardown MUST drop or delete the test DB so runs are independent.

#### Scenario: Integration test DB matches production schema

- GIVEN the test suite runs against a fresh test DB created via `alembic upgrade head`
- WHEN ORM queries execute
- THEN no `OperationalError: no such column` errors occur for any column defined in the ORM models

#### Scenario: Test DB isolation prevents cross-run contamination

- GIVEN two integration test runs executed sequentially
- WHEN the second run starts
- THEN it operates on a fresh DB with no data from the first run

---

### Requirement: Core Workflow Smoke Verification

After completing the migration and pre-start wiring, the system MUST pass a smoke-test covering all critical Qora workflow areas before any PR 2 merge.

The smoke-test MUST verify the following six areas on the migrated DB:

| Area | Verification |
|------|-------------|
| Agent context assembly | Agent and client records load; dynamic tools resolve without error |
| Live call / ElevenLabs webhook | Inbound call routing creates a `CallSession`; webhook path returns 200 |
| Post-call analysis | Analysis trigger fires; `CallAnalysis` record is created with non-null fields |
| CRM import/sync/custom fields | CRM sync endpoint completes; `LeadCustomField` records are present |
| Scheduler / scheduled calls | `ScheduledCall` records are queryable; next-action scheduler executes |
| Lead detail / facts / dimensions | Lead detail view loads; `LeadProfileFact` and dimension rollup columns are present |

Each area MUST pass on both the fresh-DB path and the stamped-existing-DB path.

#### Scenario: All six areas pass on stamped existing DB

- GIVEN production `qora.db` has been stamped and the app started via pre-start
- WHEN each of the six workflow smoke checks is executed
- THEN all six return expected results with no schema-related errors

#### Scenario: All six areas pass on fresh DB

- GIVEN `qora.db` does not exist and `alembic upgrade head` has been run
- WHEN seeders execute and each smoke check runs
- THEN all six return expected results with no missing-column or missing-table errors

---

### Requirement: Rollback Procedure

The system MUST support full rollback to the pre-migration state within five minutes using a documented procedure.

| Stage | Rollback Action |
|-------|----------------|
| Before stamp (any pre-PR-1 step) | Restore `qora.db.bak-{date}`; no code change needed |
| After stamp, before legacy removal (PR 1 merged) | Restore `qora.db.bak-{date}`; `git revert` Alembic init commit |
| After legacy removal (PR 2 merged) | Restore `qora.db.bak-{date}`; `git revert` PR 2 commit range |
| Nuclear option | Restore backup + `git revert` all change commits; estimated time < 5 min |

The rollback procedure MUST be documented in `docs/MIGRATIONS.md`. Restoring the backup MUST return the application to its pre-change behavior without manual SQL.

#### Scenario: Rollback from post-stamp state

- GIVEN PR 1 is merged and `qora.db` has been stamped
- WHEN a defect is detected and the operator runs the pre-stamp rollback procedure
- THEN `qora.db.bak-{date}` is restored, the `alembic_version` table does not exist, and the app starts using the legacy startup compat path

#### Scenario: Nuclear rollback completes under five minutes

- GIVEN a defect is detected after PR 2 merge
- WHEN the operator executes the nuclear rollback procedure
- THEN the application is running its pre-change behavior in under five minutes with all pre-change data intact

---

### Requirement: Developer Workflow Documentation

The system MUST include `docs/MIGRATIONS.md` documenting the daily developer workflow for schema changes using Alembic.

The guide MUST cover: creating a new migration (`alembic revision --autogenerate`), applying migrations locally (`alembic upgrade head`), downgrading (`alembic downgrade -1`), stamping an existing DB, the deprecation status of scripts in `backend/scripts/`, and the rollback procedure table. The guide MUST be readable in under five minutes.

#### Scenario: Developer creates and applies a new migration

- GIVEN a developer adds a column to an ORM model
- WHEN they follow the guide steps for creating and applying a migration
- THEN a new revision file exists in `backend/alembic/versions/`, `alembic upgrade head` applies it, and the column is present in the DB

#### Scenario: Guide explains deprecated scripts clearly

- GIVEN a developer encounters a file in `backend/scripts/migrate_*.py`
- WHEN they read the deprecation header and the guide
- THEN they understand the file is read-only history and that all new migrations go through Alembic
