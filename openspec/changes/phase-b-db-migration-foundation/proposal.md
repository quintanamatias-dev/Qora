# Proposal: Phase B — Database Migration Foundation

## Intent

Qora's schema evolution is managed by ~280 lines of raw SQL running on every startup (`_ensure_startup_schema_compat`) and 14 ad-hoc scripts in `backend/scripts/` with no version tracking, ordering guarantees, or rollback path. This has already caused column drift bugs, silent data-loss risks (table rebuild without column-set validation), and startup-as-migration coupling that makes safe rollout impossible. We replace both mechanisms with Alembic before Phase B adds more schema changes on top of an already-fragile foundation.

## Scope

### In Scope

- Add `alembic` dependency to `pyproject.toml`
- Initialize Alembic environment (`backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako`)
- Capture a baseline migration (`001_baseline.py`) representing the complete current schema
- Stamp existing DBs (`alembic stamp head`) without re-running DDL
- Verify fresh-DB creation path via `alembic upgrade head`
- Verify existing-DB stamp + startup path
- Remove `_ensure_startup_schema_compat()` from `main.py` after baseline verification
- Replace `create_all()` in `database.py:init_db()` with `alembic upgrade head`
- Add deprecation headers to all 14 scripts in `backend/scripts/migrate_*.py`
- Document the new workflow in `docs/MIGRATIONS.md`
- Schema comparison before/after to confirm zero drift
- Backup procedure documented and executed before any DB-touching step

### Out of Scope

- PostgreSQL migration (Phase B3, separate slice)
- Removing deprecated Client columns (`agent_name`, `voice_id`, etc.)
- Removing legacy `app/db/models.py` if it still exists
- Any new schema columns or data migrations (next slice after foundation is stable)
- Business behavior changes — no new features, no API surface changes
- Production deployment (local + staging verification only in this slice)

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `db-migration-tooling`: Alembic-based ordered migration system with version tracking, upgrade/downgrade paths, and developer workflow guide. Covers config, env, baseline, and verification procedure.

### Modified Capabilities

None — no existing openspec specs exist yet for database management.

## Approach

**Alembic with async SQLAlchemy + SQLite batch mode.** Alembic is the first-party migration companion for SQLAlchemy 2.0 (already in use). It auto-generates migration scripts by diffing ORM models against the DB, tracks history in an `alembic_version` table, and supports both fresh-DB creation and in-place upgrade of existing DBs with a single command.

**Rollout order** (safe-step ladder):

1. **Baseline safety**: snapshot current DB schema, document backup procedure, run pre-change verification
2. **Alembic init**: add dependency, generate config and env (additive only, no behavior change)
3. **Baseline migration**: generate `001_baseline.py` from ORM models, manually validate against actual schema
4. **Stamp existing DBs**: `alembic stamp head` records current state without re-running DDL
5. **Verify fresh path**: delete test DB, run `alembic upgrade head`, start app, confirm seeding works
6. **Remove startup compat**: delete `_ensure_startup_schema_compat()` and `create_all()` from init path, wire `alembic upgrade head` into startup
7. **Verify again**: both fresh and existing DB paths pass before any PR merge
8. **Deprecate scripts**: add `# DEPRECATED` headers; do not delete (audit trail)
9. **Document**: `docs/MIGRATIONS.md` with daily developer workflow

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/main.py` | Modified (deletion) | Remove `_ensure_startup_schema_compat()` (~280 lines) |
| `backend/app/core/database.py` | Modified | Replace `create_all()` with `alembic upgrade head` in `init_db()` |
| `backend/alembic.ini` | New | Alembic config (DB URL, script location, async engine) |
| `backend/alembic/env.py` | New | Migration runner with async SQLAlchemy + batch mode |
| `backend/alembic/script.py.mako` | New | Template for future migration files |
| `backend/alembic/versions/001_baseline.py` | New | Complete schema snapshot (~200 lines, generated) |
| `backend/scripts/migrate_*.py` (14 files) | Modified | Deprecation header added; files kept |
| `backend/pyproject.toml` | Modified | Add `alembic` dependency |
| `docs/MIGRATIONS.md` | New | Developer workflow guide |

## Safety Model

1. **Backup first** — copy `backend/qora.db` to `backend/qora.db.bak-{date}` before any step that touches the DB
2. **Schema comparison** — capture `PRAGMA table_info(*)` for all tables before and after; diff must show zero changes
3. **Core workflow smoke-test** — after stamp+start, manually verify: agent context assembly, inbound call routing, post-call analysis trigger, CRM sync endpoint, scheduler next-action, lead detail view load
4. **Rollback path** — if anything breaks after stamp, restore `qora.db.bak-{date}`, remove `alembic_version` table, revert code changes; old startup compat function is still present in git history and can be re-applied via revert commit

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Baseline migration doesn't match actual schema (stamp records false state) | Med | Generate from ORM, then diff against `PRAGMA table_info(*)` for all tables before stamp |
| SQLite batch mode generates unexpected code for complex table rebuilds | Low | Test on DB copy; review generated SQL before applying |
| Async engine config for Alembic requires non-obvious setup | Low | Follow SQLAlchemy async Alembic cookbook; covered in `docs/MIGRATIONS.md` |
| Removing startup compat breaks seeding on fresh DB | Med | Fresh-DB verification step (Step 5) gates Step 6 explicitly |
| Existing data corrupted during stamp | Low | Stamp is non-destructive — it only writes one row to `alembic_version` |

## Rollback Plan

At every stage, the previous state is recoverable:

- **Before Step 4 (stamp)**: restore `qora.db.bak`, no code changes needed
- **Before Step 6 (remove startup compat)**: `git revert` the deletion commit; startup compat is back
- **After any merged PR**: each PR is independently revertable; two-PR split ensures behavioral change is isolated in PR 2
- **Nuclear option**: restore `qora.db.bak`, `git revert` all commits in the change, restart — back to current state in under 5 minutes

## Dependencies

- `alembic` package (compatible with SQLAlchemy 2.0 async; no version conflicts anticipated)
- Existing `aiosqlite` driver (already installed)
- Current ORM models must accurately reflect intended schema before baseline generation

## Open Questions / Decisions Required Before Spec

1. **Startup wiring**: should `alembic upgrade head` run inside the FastAPI lifespan handler (current pattern), or as a separate pre-start command in Docker/Procfile? (Tradeoff: lifespan is simpler; pre-start is safer for multi-instance scenarios)
2. **Migration numbering**: sequential prefix (`001_`, `002_`) vs. Alembic default (hex revision IDs)? Sequential is human-readable; hex avoids renaming conflicts in parallel branches.
3. **Test DB isolation**: do integration tests spin up a fresh DB per run? If so, they must also run `alembic upgrade head` instead of `create_all()` — otherwise tests diverge from production schema management.
4. **Deprecation vs. deletion of old scripts**: keep as audit trail (proposed here) or move to `backend/scripts/archive/`? Affects repo cleanliness and whether CI might accidentally run them.

## Review / Deployment Strategy

**Two-PR split** (within 800-line budget):

| PR | Contents | Lines (est.) | Risk |
|----|----------|--------------|------|
| PR 1 | Alembic init, config, env, baseline migration, `pyproject.toml` | ~300 additions | Low (additive only; old mechanism still active) |
| PR 2 | Remove startup compat, replace `create_all`, wire `alembic upgrade head`, deprecate scripts, add `docs/MIGRATIONS.md` | ~380 additions / ~300 deletions | Medium (behavioral change; gated by PR 1 verification) |

PR 1 is safe to merge immediately — it adds Alembic without changing runtime behavior. PR 2 is the actual cutover and must not merge until both fresh-DB and existing-DB verification pass locally and on staging.

## Success Criteria

- [ ] `alembic upgrade head` on a clean environment creates all tables correctly and app starts without errors
- [ ] `alembic stamp head` on existing `qora.db` records current version; app starts with all existing data intact
- [ ] `PRAGMA table_info(*)` diff before/after shows zero changes
- [ ] Core workflow smoke-test passes: agent context, call routing, post-call analysis, CRM sync, scheduler, lead detail
- [ ] `_ensure_startup_schema_compat()` is removed from `main.py`
- [ ] `create_all()` is removed from `database.py:init_db()`
- [ ] All 14 scripts in `backend/scripts/` have deprecation headers
- [ ] `docs/MIGRATIONS.md` explains the daily developer workflow in under 5 minutes reading time
- [ ] `alembic history` shows a clean linear migration history starting at `001_baseline`
- [ ] Backup procedure is documented and has been executed at least once during this slice

## Next Recommended Phase

**sdd-spec** → write the `db-migration-tooling` spec covering: Alembic config contract, baseline migration requirements, startup integration contract, verification checklist, and rollback procedure. Then **sdd-tasks** to split into PR-aligned implementation tasks.
