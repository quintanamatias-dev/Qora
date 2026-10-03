# Tasks: Qora Config Phase 4 — Skill Packages

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,900 total across 5 units |
| 800-line budget risk | High if combined; Low per-unit when kept separate |
| 400-line budget risk | Low — every unit estimated at or under ~400 lines |
| Chained PRs recommended | Yes — five review slices, strictly ordered |
| Suggested split | One PR per numbered task below; task 3 (runtime cutover) is never combined with any other task |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Models + schema migration 0024 + one-time import migration 0025 | PR 1 | Additive; seeds Quintana's existing registries. Rollback: `alembic downgrade -1` twice; remove new files. |
| 2 | Skills service + resolution + cache | PR 2 | Additive; depends on PR 1. Rollback: revert PR. |
| 3 | Runtime cutover of the full loader chain + `load_skill` tool | PR 3 | Behavioral cutover — never combined with another task. Depends on PR 1-2. Golden regression: Quintana `leads-agent` registry/content byte-identical to the files. Rollback: revert PR. |
| 4 | API: packages/skills CRUD, content write (new revision), revisions, rollback | PR 4 | Depends on PR 1-3. Rollback: revert PR. |
| 5 | Full suites + rollout notes | PR 5 | Depends on all prior tasks. Rollback: n/a — verification only. |

## Known Environmental Failures

None identified at the time of writing — this change's own test additions are the only expected RED states before implementation. If the base backend suite has pre-existing unrelated failures at apply time, they must be named explicitly here before any task reports `status: completed`.

## Phase 1: Models + Schema Migration 0024 + Import Migration 0025

- [ ] 1.1 Add `SkillPackage`, `Skill`, `SkillRevision` models to `backend/app/tenants/models.py` per design.md's Interfaces/Contracts section.
      RED: `test_skill_package_model_fields_exist`, `test_skill_model_fields_exist`, `test_skill_revision_model_fields_exist` (new file `backend/tests/unit/tenants/test_skill_package_models.py`) — fail (models don't exist).
      GREEN: all three models import successfully; `unique(package_id, slug, agent_id)` on `skills` is present via `PRAGMA index_list`/model metadata.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_skill_package_models.py`
      Rollback: delete the model classes; revert commit.

- [ ] 1.2 Create `backend/alembic/versions/20261003_0025_skill_packages_schema.py` (chained after `20261003_0024_analysis_profiles_schema.py`): `CREATE TABLE skill_packages`, `CREATE TABLE skills`, `CREATE TABLE skill_revisions`.
      RED: `test_skill_packages_schema_migration_creates_tables` — fails against a tmp DB at the current head (tables don't exist).
      GREEN: `alembic upgrade head` on a tmp DB creates all three tables with the expected columns and `unique(package_id, slug, agent_id)` constraint (`PRAGMA table_info`/`PRAGMA index_list`).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k skill_packages_schema`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

- [ ] 1.3 Create `backend/alembic/versions/20261003_0026_import_skill_registries.py`: for each `backend/clients/*/agents/*/skills/registry.yaml`, ensure a client package exists, insert one `skills` row per entry in the `agent` section for that agent, and seed revision 1 from the referenced `*.agent-skill.md` file's content plus the entry's `filler_text`/`trigger_hint`/`description`. No `app.*` import (house pattern — inline `yaml.safe_load` and plain file reads); idempotent via a `(package_id, slug, agent_id)` existence check before insert.
      RED: `test_import_skill_registries_creates_rows_from_fixture`, `test_import_skill_registries_is_idempotent_on_rerun` (new file in `backend/tests/unit/test_alembic_tooling.py` or a dedicated fixture module) — fail (migration doesn't exist); fixture uses a tmp `registry.yaml` + `*.agent-skill.md` pair matching Quintana's real `leads-agent` shape.
      GREEN: after `alembic upgrade head`, a `skills` row + revision 1 exists for each fixture entry with `content_md`/`filler_text`/`trigger_hint`/`description` matching the fixture files exactly; running the migration's import logic a second time against the same DB state creates zero additional rows.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k import_skill_registries`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

## Phase 2: Skills Service + Resolution + Cache

- [ ] 2.1 Create `backend/app/skills/service.py` with `create_skill_revision`, `get_revision`, `list_revisions`, `rollback_skill` built on `revisions_service.py`'s existing generic private helpers, parameterized for `SkillRevision` (the fourth owner table added to that reuse pattern after `analysis-profiles`' third).
      RED: `test_create_skill_revision_does_not_mutate_existing_rows`, `test_rollback_skill_creates_new_revision_not_resurrection` (new file `backend/tests/unit/skills/test_service.py`) — fail (module doesn't exist).
      GREEN: `create_skill_revision` produces sequential `revision_number`s with no `UPDATE`/`DELETE` against an existing row; `rollback_skill` to an older revision creates a new revision copying that content, with `active_revision_id` pointing at the new row, not the old one.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_service.py -k "revision or rollback"`
      Rollback: delete the file; revert commit.

- [ ] 2.2 Add `resolve_agent_skills(session, client_id, agent_slug) -> list[SkillRegistryEntry]` to `backend/app/skills/service.py` implementing the Qora-general + client-general + client-agent-section resolution with the agent > client-general > qora collision rule (P4-D2), logging a `WARNING` on each dropped lower-priority entry.
      RED: `test_resolve_agent_skills_returns_qora_general_skills`, `test_resolve_agent_skills_client_general_overrides_qora_on_slug_collision`, `test_resolve_agent_skills_agent_section_overrides_both`, `test_resolve_agent_skills_logs_warning_on_collision` — fail (function doesn't exist).
      GREEN: all four scenarios resolve exactly as named; the returned entries are `SkillRegistryEntry` instances with fields matching the winning source's active revision.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_service.py -k resolve_agent_skills`
      Rollback: delete the function; revert commit.

- [ ] 2.3 Create `backend/app/skills/cache.py` with `AgentSkillsCache`, keyed by `(agent_id, tuple of contributing active_revision_id values)` (P4-D3).
      RED: `test_agent_skills_cache_hit_skips_resolution`, `test_agent_skills_cache_key_changes_after_write` (new file `backend/tests/unit/skills/test_cache.py`) — fail (class doesn't exist, every `.get()` re-resolves).
      GREEN: a second `.get()` call with no intervening write does not re-invoke `resolve_agent_skills` (assert via a call-count mock); a write that changes a contributing skill's `active_revision_id` causes the next `.get()` to re-resolve and reflect the new content, with no explicit `.invalidate()` call required.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_cache.py`
      Rollback: delete the file; revert commit.

## Phase 3: Runtime Cutover (do not combine with other tasks)

- [ ] 3.1 Cut over `backend/app/prompts/skill_loader.py`'s `load_skill_registry()` to call `resolve_agent_skills()` via `AgentSkillsCache` instead of parsing `registry.yaml`; `SkillRegistryEntry` shape unchanged.
      RED: existing `backend/tests/.../test_skill_loader.py` tests asserting a `registry.yaml`-backed result — adjusted to seed `skill_packages`/`skills`/`skill_revisions` rows instead of a fixture file; these fail against the unmodified source (still reading the filesystem).
      GREEN: the same tests pass reading from the DB fixtures; a client with no row returns an empty list (same semantics as a missing `registry.yaml` today).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/prompts/test_skill_loader.py`
      Rollback: revert the file; `load_skill_registry()` reverts to parsing `registry.yaml`, untouched and still on disk.

- [ ] 3.2 Cut over `backend/app/prompts/loader.py`'s `load_agent_skills()` (line 138) and `load_skill_registry_entries()` (line 164) to the DB-backed resolver.
      RED/GREEN: same pattern as 3.1, against existing `test_loader.py` skills-related tests.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/prompts/test_loader.py -k skill`
      Rollback: same pattern as 3.1.

- [ ] 3.3 Cut over `backend/app/voice/context.py` (lines 242, 259) — index/allowlist injection sources the resolved DB skill set; confirm the "load_skill is injected unconditionally when the agent has registry entries" behavior (lines 366, 395-397) is unaffected by the data-source change.
      RED: existing `test_context.py` skill-index/allowlist assertions — fail once fixtures are switched to DB-seeded rows against the unmodified source.
      GREEN: same tests pass; the unconditional `load_skill` injection still fires exactly when the resolved entry list is non-empty, matching today's "registry.yaml present" trigger.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_context.py -k skill`
      Rollback: revert the file; reverts to reading via the unmodified `load_agent_skills`/`load_skill_registry_entries` (which themselves revert in 3.2's rollback).

- [ ] 3.4 Cut over `backend/app/tools/skill_loader.py`'s `handle_load_skill()` to look up `content_md` from the resolved allowlist's active revision (DB read) instead of reading a `*.agent-skill.md` file; preserve the allowlist-before-access check and the path-separator/`..` rejection exactly.
      RED: existing `test_skill_loader.py` (tools) tests — fail once fixtures are DB-seeded against the unmodified source; NEW `test_handle_load_skill_rejects_unsafe_skill_name_before_db_lookup` extends the existing path-separator test to confirm the check still runs before any DB query.
      GREEN: a skill name present in the resolved entry list returns its DB-sourced content; the security tests behave identically to today (rejection happens before any lookup, DB or filesystem).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tools/test_skill_loader.py`
      Rollback: revert the file; reverts to reading `*.agent-skill.md` files directly.

- [ ] 3.5 Confirm `backend/app/tools/dispatcher.py` (lines 231-246), `backend/app/tools/registry.py` (lines 27, 63, 81), `backend/app/voice/session.py` (lines 45-49), and `backend/app/voice/webhook.py` (lines 400-420) require no behavioral change — only verify their existing tests pass against the new `handle_load_skill()` implementation underneath.
      RED: n/a — verification task; existing `test_dispatcher.py`, `test_registry.py`, session-cache, and webhook short-circuit tests are the gate.
      GREEN: all four existing test files pass unmodified against the cutover from 3.1-3.4.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tools/test_dispatcher.py tests/unit/tools/test_registry.py tests/unit/voice/test_session.py tests/unit/voice/test_webhook.py -k skill`
      Rollback: n/a — verification only; a failure here is evidence for 3.1-3.4, not a separate revert.

- [ ] 3.6 Golden regression: Quintana's `leads-agent` resolved registry entries and skill contents are byte-identical to today's `registry.yaml` + `*.agent-skill.md` files.
      RED: `test_quintana_leads_agent_registry_and_content_are_byte_identical_to_files` (new file `backend/tests/regression/test_skill_packages_golden.py`) — fails until 3.1-3.4 land (no resolved DB path exists yet to compare against).
      GREEN: seed Quintana via migration 0025, call `resolve_agent_skills("quintana-seguros", "leads-agent")`, assert the two returned entries' `name`/`description`/`trigger_hint`/`filler_text` string-equal the current `registry.yaml` values exactly, and assert each resolved skill's content via `handle_load_skill` string-equals the corresponding `*.agent-skill.md` file's content exactly.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/regression/test_skill_packages_golden.py`
      Rollback: n/a — regression gate; a failure here blocks task 3 from being considered done, it does not require reverting unrelated code.

- [ ] 3.7 Static-import regression guard: no remaining filesystem read of `registry.yaml` or `*.agent-skill.md` anywhere under `backend/app/`.
      RED: `test_no_remaining_skill_registry_filesystem_reads` (new file `backend/tests/unit/test_skill_registry_filesystem_removed.py`) — fails until 3.1-3.4 are all complete.
      GREEN: a source-grep-based test over `backend/app/` finds zero matches for a direct `registry.yaml` or `*.agent-skill.md` filesystem open/read in any `app/` module (the import migration itself, under `backend/alembic/`, is explicitly excluded from this guard — it is expected to read the filesystem once).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_skill_registry_filesystem_removed.py`
      Rollback: n/a — verification-only guard; a failure means a reader was missed, not that this task needs reverting.

## Phase 4: API

- [ ] 4.1 Create `backend/app/skills/router.py` with package/skill CRUD: `GET/POST /clients/{client_id}/skill-packages`, `GET/POST/PUT/DELETE /clients/{client_id}/skill-packages/{package_id}/skills`; tenant-scoped via `require_client_access`.
      RED: `test_create_client_skill_package_and_skill`, `test_client_cannot_access_another_clients_package` (new file `backend/tests/unit/skills/test_router.py`) — fail (endpoints don't exist, 404).
      GREEN: a client can create/list/update/delete its own package's skills; a cross-client access attempt returns 404/403, matching every prior client-scoped router's tenant-isolation precedent.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_router.py -k "package or skill_crud"`
      Rollback: remove the route handlers; revert commit.

- [ ] 4.2 Add `PUT /clients/{client_id}/skill-packages/{package_id}/skills/{skill_id}/content` (creates a new revision, never mutates an existing one; activates the new revision on write, matching `create_agent_config_revision`'s activate-on-create pattern).
      RED: `test_put_skill_content_creates_new_revision_and_activates_it`, `test_put_skill_content_never_mutates_an_existing_revision` — fail (endpoint doesn't exist).
      GREEN: a content write creates revision N+1 and points `active_revision_id` at it; the prior revision's row is byte-unchanged afterward.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_router.py -k content`
      Rollback: remove the route handler; revert commit.

- [ ] 4.3 Add `GET /clients/{client_id}/skill-packages/{package_id}/skills/{skill_id}/revisions` and `POST .../rollback`.
      RED: `test_get_revisions_lists_all_in_order`, `test_post_rollback_requires_target_in_same_skill`, `test_post_rollback_creates_new_revision_not_resurrection` — fail (endpoints don't exist).
      GREEN: all three scenarios behave exactly as named; a rollback target belonging to a different skill returns 404.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_router.py -k "revisions or rollback"`
      Rollback: remove the route handlers; revert commit.

- [ ] 4.4 Gate the Qora package to superadmin-only for every write route added in 4.1-4.3.
      RED: `test_qora_package_write_requires_superadmin`, `test_qora_package_read_allowed_for_any_authenticated_client` — fail (no distinction made yet between Qora and client packages at the access-control layer).
      GREEN: a non-superadmin request to write a Qora-package skill is rejected; the same route against a client's own package succeeds without superadmin.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/skills/test_router.py -k qora_package`
      Rollback: remove the superadmin gate; revert commit — leaves the Qora package writable by any client, an explicit regression acceptable only as an emergency rollback.

## Phase 5: Full Suites + Rollout Notes

- [ ] 5.1 Run the full backend suite.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.

- [ ] 5.2 Re-run the golden regression test (task 3.6) one final time after tasks 4 lands, confirming Quintana's `leads-agent` equivalence still holds end-to-end.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/regression/test_skill_packages_golden.py`
      Rollback: n/a — verification gate.

- [ ] 5.3 Document the rollout: no production env var or manual operator action is required (migrations 0024/0025 are self-contained, additive, and idempotent); the admin UI for package/skill editing is explicitly deferred to the user's own later work, not this change; the filesystem `registry.yaml`/`*.agent-skill.md` files remain on disk, unread, until a later release deletes them.
      Check: rollout notes added to this file or a follow-up PR description — no executable check.
      Rollback: n/a — documentation only.
