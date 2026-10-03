# Tasks: ElevenLabs Reconciler

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,200 total across 6 units |
| 800-line budget risk | Low — combined total is well under budget |
| 400-line budget risk | Low — every unit estimated at or under ~350 lines |
| Chained PRs recommended | Yes — six review slices |
| Suggested split | One PR per numbered task below |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Schema: `elevenlabs_reconciliation_reports` | PR 1 | Additive. Rollback: `alembic downgrade -1`. |
| 2 | Reconciliation logic (fetch-only, drift compute, upsert) | PR 2 | Depends on PR 1. Rollback: revert PR. |
| 3 | Background loop wired into `main.py` | PR 3 | Depends on PR 2. Rollback: revert PR. |
| 4 | Admin API (GET report, POST run-now) | PR 4 | Depends on PR 2-3. Rollback: revert PR. |
| 5 | `webhook.py` legacy DEPRECATED-column removal | PR 5 | Independent of 1-4. Rollback: revert PR. |
| 6 | `is_default` write-time enforcement + response exposure removal | PR 6 | Independent of 1-5. Rollback: revert PR. |

## Known Environmental Failures

None identified at the time of writing. If the base backend suite has pre-existing unrelated failures at apply time, they must be named explicitly here before any task reports `status: completed`.

## Phase 1: Schema

- [ ] 1.1 Add `ElevenLabsReconciliationReport` model to `backend/app/elevenlabs/models.py` (new file) per design.md's Interfaces/Contracts.
      RED: `test_reconciliation_report_model_fields_exist` (new file `backend/tests/unit/elevenlabs/test_reconciliation_models.py`) — fails (model doesn't exist).
      GREEN: model imports successfully; `unique(agent_id)` constraint present via model metadata.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_reconciliation_models.py`
      Rollback: delete the model; revert commit.

- [ ] 1.2 Create `backend/alembic/versions/20261003_0027_elevenlabs_reconciliation_reports_schema.py` (chained after skill-packages' `20261003_0026`).
      RED: `test_reconciliation_reports_schema_migration_creates_table` — fails against a tmp DB at the current head (table does not exist).
      GREEN: `alembic upgrade head` creates `elevenlabs_reconciliation_reports` with expected columns and the unique constraint (`PRAGMA table_info`/`PRAGMA index_list`).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k reconciliation_reports_schema`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

## Phase 2: Reconciliation Logic

- [ ] 2.1 Extract the config-payload-building helper `sync_agent_config` uses internally (`backend/app/elevenlabs/service.py`) into a shared, importable function so the reconciler never reimplements it.
      RED: `test_build_config_payload_is_importable_and_reused_by_save_path` (new file `backend/tests/unit/elevenlabs/test_reconciler.py`) — fails (helper is private/unexported).
      GREEN: the save path's own existing tests still pass unchanged (behavioral no-op extraction); the helper is importable from outside `service.py`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_service.py`
      Rollback: revert commit; helper stays private, reconciler would need its own copy (not implemented until this lands).

- [ ] 2.2 Create `backend/app/elevenlabs/reconciler.py` with `run_reconciliation_once(db, settings)`: for each active, ElevenLabs-linked agent, GET live config, build the projection payload (2.1's helper), compute drift via the existing `_compute_drift_fields`, upsert the report row.
      RED: `test_run_reconciliation_once_upserts_in_sync_report`, `test_run_reconciliation_once_upserts_drift_report`, `test_run_reconciliation_once_never_issues_patch` — fail (module doesn't exist).
      GREEN: all three scenarios resolve exactly as named; the never-patch test mocks the HTTP client and asserts zero PATCH/PUT/POST calls occur, GET-only.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_reconciler.py -k run_reconciliation_once`
      Rollback: delete the file; revert commit.

- [ ] 2.3 Per-agent error isolation: a fetch/compute failure for one agent must not stop the pass over the rest.
      RED: `test_one_agent_fetch_error_does_not_block_sibling_agent` — fails if an exception in one agent's try block propagates and halts the loop.
      GREEN: two agents, one with a mocked fetch failure and one healthy; assert the healthy agent's report is `in_sync` and the failing one's is `error`, both rows present after one pass.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_reconciler.py -k isolation`
      Rollback: n/a — regression guard; a failure here blocks closing task 2, it does not require reverting unrelated code.

## Phase 3: Background Loop

- [ ] 3.1 Add `reconciler_tick(settings)` to `reconciler.py`: interval loop (`elevenlabs_reconciler_interval_hours`, default 6), calls `run_reconciliation_once` each pass, wraps the pass in try/except so an unhandled exception never kills the loop (mirrors `scheduler_tick`).
      RED: `test_reconciler_tick_survives_unexpected_exception` — fails (loop doesn't exist / an unhandled exception would propagate and kill the task).
      GREEN: a mocked `run_reconciliation_once` that raises on its first call does not prevent a second call on the next simulated tick.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_reconciler.py -k tick`
      Rollback: delete the function; revert commit.

- [ ] 3.2 Add `Settings.elevenlabs_reconciler_interval_hours: int = 6` to `backend/app/core/config.py`; wire `reconciler_tick()` into `main.py`'s lifespan startup/shutdown alongside `scheduler_task`/`outbound_sweeper_task`.
      RED: `test_app_starts_reconciler_task_on_lifespan` (new file `backend/tests/unit/test_main_startup.py` extension or existing file) — fails (task not started).
      GREEN: `TestClient(app)` construction starts the reconciler task; shutdown cancels it cleanly (no dangling task warning).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_main_startup.py -k reconciler`
      Rollback: revert the `main.py`/`config.py` changes; reports simply stop updating, no other feature affected.

## Phase 4: Admin API

- [ ] 4.1 Add `GET /api/v1/admin/elevenlabs/reconciliation` (superadmin) returning every agent's latest report.
      RED: `test_get_reconciliation_requires_superadmin`, `test_get_reconciliation_returns_latest_reports` (new file `backend/tests/unit/elevenlabs/test_reconciliation_router.py`) — fail (endpoint doesn't exist, 404).
      GREEN: non-superadmin → 403; superadmin → 200 with the expected report list shape.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_reconciliation_router.py -k get_reconciliation`
      Rollback: remove the route handler; revert commit.

- [ ] 4.2 Add `POST /api/v1/admin/elevenlabs/reconciliation/run` (superadmin), running `run_reconciliation_once` synchronously and returning its result.
      RED: `test_post_run_requires_superadmin`, `test_post_run_returns_fresh_results` — fail (endpoint doesn't exist).
      GREEN: non-superadmin → 403; superadmin → 200, and an immediately following `GET .../reconciliation` reflects the just-triggered run, not a stale scheduled result.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_reconciliation_router.py -k post_run`
      Rollback: remove the route handler; revert commit.

## Phase 5: webhook.py Legacy Removal (independent of phases 1-4)

- [ ] 5.1 Remove the `client_orm.system_prompt_override` fallback (~1178-1192) and the `tools_enabled` read when `agent is None` (~1208-1210) from `backend/app/voice/webhook.py`.
      RED: `test_no_remaining_deprecated_column_read_in_webhook` (new file `backend/tests/unit/voice/test_webhook_legacy_removed.py`) — a source-grep-based test asserting zero matches for `system_prompt_override`/`tools_enabled` reads in `webhook.py`; fails against the unmodified source.
      GREEN: the grep-based test passes; existing webhook tests for an agent-having client are unaffected (no active client exercises the removed `agent is None` branch, confirmed via agent-routing's completed migration).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_webhook_legacy_removed.py tests/unit/voice/test_webhook.py`
      Rollback: revert the file; the two fallback reads are restored.

- [ ] 5.2 Remove `_has_static_prompt`'s legacy DEPRECATED-column branch (~1296-1299).
      RED: extends 5.1's grep-based test to cover `_has_static_prompt`; fails until this task lands.
      GREEN: grep-based test passes; existing `_has_static_prompt` tests (for the non-legacy branch) are unaffected.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_webhook_legacy_removed.py`
      Rollback: revert the file; the legacy branch is restored.

## Phase 6: is_default Removal (independent of phases 1-5)

- [ ] 6.1 Remove `is_default`'s write-time uniqueness enforcement from `backend/app/tenants/service.py`'s `create_agent`/`update_agent` (~622-634).
      RED: `test_create_agent_no_longer_enforces_is_default_uniqueness` (extends `backend/tests/unit/tenants/test_service.py`) — fails against the unmodified source (the current code still raises `ValueError` on a duplicate `is_default=True`).
      GREEN: creating two agents for the same client with `is_default=True` no longer raises; existing `resolve_single_active_agent` tests (which never read `is_default`, per design.md) continue to pass unchanged.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_service.py`
      Rollback: revert the file; the uniqueness check is restored.

- [ ] 6.2 Remove `AgentResponse.is_default` (`backend/app/agents/schemas.py:234`) and its serialization in `backend/app/agents/router.py:147`.
      RED: `test_agent_response_schema_no_longer_exposes_is_default` (new file `backend/tests/unit/agents/test_schemas_is_default_removed.py`) — fails (field still present).
      GREEN: `AgentResponse`'s field set no longer includes `is_default`; existing agent-router tests that previously asserted on the field's presence are updated to assert its absence.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/agents/test_schemas_is_default_removed.py tests/unit/agents/test_router.py`
      Rollback: revert both files; the field and its serialization are restored.

- [ ] 6.3 Run the full backend suite one final time before closing the change.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.
