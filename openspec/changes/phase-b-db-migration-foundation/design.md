# Design: Phase B — Database Migration Foundation

## Technical Approach

Replace Qora's two ad-hoc schema management mechanisms (~280-line startup DDL in `main.py` + 14 untracked scripts in `scripts/`) with Alembic. A single baseline migration captures the full current schema; existing DBs are stamped without re-running DDL; a pre-start script invokes `alembic upgrade head` before the FastAPI process. Tests switch from `create_all()` to migration-based schema creation via a shared fixture.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Migration tool | Alembic | Custom runner, Yoyo | First-party SQLAlchemy companion; autogenerate detects ORM drift; batch mode handles SQLite ALTER limitations; PostgreSQL-ready if needed later |
| Database engine | SQLite retained | PostgreSQL | User requirement — SQLite speed is a product advantage; Alembic supports both identically |
| Migration model | Pre-start command (`backend/scripts/migrate.py`) | FastAPI lifespan handler | Decouples migration from app process; safe for multi-instance; Docker `CMD` chains it before `uvicorn`; locally invoked via `python scripts/migrate.py` |
| Revision style | Alembic default (hex revision IDs) | Sequential `001_`, `002_` | Professional default; avoids renaming conflicts in parallel branches; `alembic history` provides human-readable ordering |
| Test DB creation | `alembic upgrade head` via shared fixture | `Base.metadata.create_all()` | Tests must use the production schema path to catch migration drift; fixture wraps the programmatic Alembic API |
| Legacy cleanup | Deprecation headers on 14 scripts; `_ensure_startup_schema_compat` removed after verification | Delete scripts immediately | Audit trail preserved; scripts are read-only history; deletion is a later cleanup slice |
| Schema inventory | Classify every element as `active`/`compatibility`/`candidate-unused` before baseline | Blindly snapshot ORM | Prevents fossilizing iteration dirt; deprecated Client columns (agent_name, voice_id on Client) classified as `compatibility` and included but documented |

## Data Flow

```
LOCAL DEV                             DOCKER / DEPLOY
───────────                           ────────────────
python scripts/migrate.py             CMD: python scripts/migrate.py && uvicorn ...
       │                                     │
       ▼                                     ▼
  alembic.config.command.upgrade("head")  (same programmatic call)
       │                                     │
       ▼                                     ▼
  env.py: async engine + SQLite batch mode
       │
       ▼
  alembic_version table updated
       │
       ▼
  uvicorn app.main:app (no DDL in lifespan)
       │
       ▼
  init_db(): engine + session factory + WAL pragmas (NO create_all)
       │
       ▼
  seed data (ORM queries safe — schema guaranteed by migration)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/alembic.ini` | Create | Alembic config: SQLite URL, script location `alembic`, async driver |
| `backend/alembic/env.py` | Create | Async migration runner with `run_async_migrations()`, SQLite batch mode via `render_as_batch=True`, imports all model modules |
| `backend/alembic/script.py.mako` | Create | Mako template for new revision files |
| `backend/alembic/versions/{rev}_baseline.py` | Create | Complete schema snapshot (~200 lines): all tables, columns, types, constraints, indexes from ORM models; `upgrade()` creates all; `downgrade()` drops all |
| `backend/scripts/migrate.py` | Create | Pre-start entry point: programmatic `alembic upgrade head`; exits non-zero on failure to block app start |
| `backend/app/core/database.py` | Modify | Remove `Base.metadata.create_all()` from `init_db()`; keep engine creation, model imports, WAL pragmas |
| `backend/app/main.py` | Modify | Remove `_ensure_startup_schema_compat()` definition (lines 53–333) and call (line 442); ~280 lines deleted |
| `backend/pyproject.toml` | Modify | Add `alembic>=1.13.0` to dependencies |
| `backend/tests/conftest.py` | Modify | Replace `init_db()` in `db_engine` fixture with programmatic Alembic upgrade; add `apply_migrations(db_url)` helper |
| `backend/tests/helpers/migrations.py` | Create | Shared `apply_migrations(db_url)` function for test fixtures — runs `alembic.command.upgrade(config, "head")` against a given URL |
| `backend/scripts/migrate_*.py` (14 files) | Modify | Add `# DEPRECATED` header block; files kept for audit trail |
| `docs/MIGRATIONS.md` | Create | Developer workflow guide: create migration, apply, downgrade, stamp, rollback, deprecated scripts reference |
| `backend/tests/unit/test_startup_schema_compat.py` | Modify | Tests become obsolete after removal; mark with skip/deprecation or delete in this slice |

## Interfaces / Contracts

```python
# backend/scripts/migrate.py — pre-start entry point
"""Run alembic upgrade head. Exit non-zero on failure."""
import sys
from alembic.config import Config
from alembic import command

def run_migrations():
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

if __name__ == "__main__":
    try:
        run_migrations()
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        sys.exit(1)
```

```python
# backend/alembic/env.py — key async pattern
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.database import Base

# Import all models to register metadata
import app.tenants.models; import app.leads.models
import app.calls.models; import app.scheduler.models

def run_migrations_online():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async def do_run():
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    # SQLite batch mode: context.configure(..., render_as_batch=True)
```

```python
# backend/tests/helpers/migrations.py — test fixture contract
def apply_migrations(database_url: str) -> None:
    """Run alembic upgrade head against the given URL (sync wrapper)."""
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `scripts/migrate.py` exits 0 on success, non-zero on failure | Mock alembic.command, verify exit codes |
| Integration | Fresh DB via migration matches ORM schema | `apply_migrations()` on tmp DB, query `PRAGMA table_info(*)` for all tables, assert column counts/types match |
| Integration | Stamped existing DB starts correctly | Create DB via old `create_all`, stamp, run app fixtures, verify seed queries succeed |
| Integration | Autogenerate detects drift | Add a test column to a model, run `autogenerate`, assert the revision contains `add_column` |
| Smoke | Six core workflows post-migration | Agent context, call routing, post-call analysis, CRM sync, scheduler, lead detail — verified on both fresh and stamped paths |
| Regression | Existing test suite passes unchanged | All ~71 test files that call `init_db()` must pass after fixture switch to migration-based schema |

## Migration / Rollout

**Schema inventory** (pre-baseline): Generate `PRAGMA table_info(*)` for all tables in current `qora.db`. Classify each element against ORM models. Document `compatibility` columns (deprecated Client agent fields). Baseline includes ALL classified elements.

**Staged rollout**:
1. PR 1 (additive, zero behavior change): `alembic.ini`, `env.py`, `script.py.mako`, baseline migration, `pyproject.toml`, `scripts/migrate.py`. Old startup compat still runs — safety net intact.
2. PR 2 (behavioral cutover, gated by PR 1 verification): Remove `_ensure_startup_schema_compat`, remove `create_all`, switch test fixtures, deprecate old scripts, add `docs/MIGRATIONS.md`.

**Existing DB safe path**: `alembic stamp head` records baseline as applied. Zero DDL executed. All data preserved. Verified via `PRAGMA table_info(*)` diff before/after.

**Backup**: `cp backend/qora.db backend/qora.db.bak-{YYYYMMDD}` before any DB-touching step. Verified readable via `sqlite3 ... ".tables"`.

## Rollback Plan

| Stage | Action | Time |
|-------|--------|------|
| Before stamp (PR 1 not merged) | Restore `qora.db.bak`; no code change | < 1 min |
| After stamp (PR 1 merged) | Restore `qora.db.bak`; `git revert` PR 1 | < 3 min |
| After cutover (PR 2 merged) | Restore `qora.db.bak`; `git revert` PR 2 | < 5 min |
| Nuclear | Restore backup + `git revert` all commits | < 5 min |

**Fast DB-file restore**: SQLite's single-file nature means `cp qora.db.bak qora.db` is the entire restore. No connection draining, no pg_restore. The `alembic_version` table disappears with the restored file, so the old startup compat path (still in git history) works immediately after revert.

## PR/Slice Boundary and Review Workload

| PR | Contents | Est. Lines | Risk |
|----|----------|-----------|------|
| PR 1 | Alembic init + config + env + baseline + migrate.py + pyproject.toml | ~300 add | Low (additive) |
| PR 2 | Remove startup compat + remove create_all + test fixture switch + deprecation headers + docs/MIGRATIONS.md | ~380 add / ~300 del | Medium (behavioral) |

**Total**: ~680 changed lines within the 800-line review budget. PR 1 is safe to merge immediately — no runtime behavior change. PR 2 merges only after fresh-DB and existing-DB verification pass on PR 1.

## Open Questions

- [x] Pre-start vs lifespan migration — **resolved**: pre-start command
- [x] Revision style — **resolved**: Alembic default hex IDs
- [x] Test DB alignment — **resolved**: tests use migration path
- [ ] Should `backend/tests/unit/test_startup_schema_compat.py` be deleted in PR 2 or kept with skip markers? (Low priority — does not block design)
