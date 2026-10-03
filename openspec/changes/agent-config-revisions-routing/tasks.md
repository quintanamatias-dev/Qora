# Tasks: Qora Config Phase 1a — Agent Config Revisions & Routing

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,900 total across 8 units |
| 800-line budget risk | High if combined; Low per-unit when kept separate |
| 400-line budget risk | Medium — tasks 4a and 4b are the largest at ~300–350 est. lines each |
| Chained PRs recommended | Yes — eight review slices, strictly ordered |
| Suggested split | One PR per numbered task below; 4a and 4b are never combined with each other or with task 5 |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Medium (4a, 4b)

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Schema + migration + import | PR 1 | Additive; no runtime behavior change. Rollback: `alembic downgrade -1`. |
| 2 | Revision service + API | PR 2 | Additive; depends on PR 1. Rollback: revert PR 2, schema unused but intact. |
| 3 | Runtime reads active revision | PR 3 | Behavioral — prompt source cutover only. Depends on PR 1+2. Rollback: revert PR 3. |
| 4a | Live-call routes + initiation webhook | PR 4a | Highest risk — routing-correctness fix on live traffic. Depends on PR 3. Rollback: revert PR 4a only. |
| 4b | Scheduler + recontact + tool + outbound + calls + leads preview | PR 4b | Depends on PR 3 (not 4a). Rollback: revert PR 4b only; independent of 4a. |
| 5 | EL projection → agent-scoped route | PR 5 | Depends on PR 4a being live. Rollback: revert PR 5 + re-sync prod EL agents to legacy routes via API. |
| 6 | Minimal admin UI | PR 6 | Depends on PR 2. Rollback: revert PR 6, frontend-only. |
| 7 | Prod rollout + verification | PR 7 | Depends on all prior tasks. Rollback: re-sync prod EL agents via API; restore DB backup if needed. |

## Phase 0: Align New-Agent Defaults with the Production Standard

- [ ] 0.1 Change the `Agent.model` default to `gpt-4.1-mini` and `Agent.tts_model` to `eleven_v4_turbo` (model columns, `core/config.py` fallbacks, create-agent schema defaults), per agent-config-inheritance design.md D17. Existing rows are untouched.
      RED: `test_new_agent_defaults_match_production_standard` — fails (defaults are `gpt-4o` / `eleven_flash_v2_5`).
      GREEN: an agent created without `model` / `tts_model` gets `gpt-4.1-mini` / `eleven_v4_turbo`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/agents/ tests/unit/tenants/`
      Rollback: revert the commit.

## Phase 1: Schema + Migration + Import

- [ ] 1.1 Add `AgentConfigRevision` model (`backend/app/tenants/models.py`): id, agent_id FK, revision_number, config (Text/JSON), schema_version, source enum, created_by, created_at, note. Add `Agent.active_revision_id` FK column.
      RED: `test_agent_config_revision_model_fields_exist` (new file `backend/tests/unit/tenants/test_agent_config_revision_model.py`) — fails because `AgentConfigRevision` does not exist yet.
      GREEN: model added, import succeeds, columns present via `PRAGMA table_info`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_agent_config_revision_model.py`
      Rollback: delete the model class and column addition; revert commit.

- [ ] 1.2 Create `backend/alembic/versions/{rev}_agent_config_revisions_schema.py` chained after head `20260930_0013_multi_tenant_auth`: `CREATE TABLE agent_config_revisions`; `ALTER TABLE agents ADD COLUMN active_revision_id` (batch mode).
      RED: `test_agent_config_revisions_schema_migration_creates_table` — fails against a tmp DB at current head (table does not exist).
      GREEN: `alembic upgrade head` on a tmp DB creates the table and column; `PRAGMA table_info(agent_config_revisions)` matches the model.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k agent_config_revisions`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

- [ ] 1.3 Write the schema inventory for the import: for every existing agent, capture current `Agent.*` values, whether `system-prompt.md` exists on the filesystem, and the actual string `render_for_agent` currently produces. Document in a scratch note used only to validate task 1.4 — not a persisted artifact.
      RED: n/a (data-gathering task, no production code changes).
      GREEN: inventory covers all agents seeded by `seed_quintana` and `seed_qora_demo` (confirmed: `quintana-seguros` has `jaumpablo` + `leads-agent`).
      Check: manual review against `render_for_agent` output for each agent.
      Rollback: n/a — no DB writes.

- [ ] 1.4 Create `backend/alembic/versions/{rev}_import_agent_config_revision_1.py`: for every existing agent, create one `source=import` revision whose `system_prompt` equals the filesystem file content when present, else `Agent.system_prompt`; populate the rest of `AgentConfigV1` from current `Agent.*` columns; activate revision 1 for every agent (`agents.active_revision_id`).
      RED: `test_import_migration_creates_revision_1_per_agent` — fails (migration does not exist; `agent_config_revisions` empty after a pre-task-1.4 upgrade).
      GREEN: migration run against a tmp DB seeded with `seed_quintana` + `seed_qora_demo` produces exactly one revision per agent; each revision's `system_prompt` matches the task 1.3 inventory's "actual rendered output" value; `agents.active_revision_id` is non-null for every agent.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k import_agent_config_revision`
      Rollback: `alembic downgrade -1` removes the imported rows (schema from 1.2 stays); re-run import migration is idempotent-safe to retry (checked by RED test for duplicate-run safety).

- [ ] 1.5 Modify `seed_quintana.py` and `seed_qora_demo.py` to also seed+activate a revision 1 for every seeded agent, so fresh-DB (non-migrated) environments match the migrated-production invariant.
      RED: `test_seed_quintana_creates_active_revision_for_every_agent` — fails (seeders do not create revisions yet).
      GREEN: after seeding, both `jaumpablo` and `leads-agent` have a non-null `active_revision_id`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/ -k seed`
      Rollback: revert seeder changes; fresh DBs lose revision seeding (schema unaffected).

## Phase 2: Revision Service + API

- [ ] 2.1 Create `backend/app/tenants/agent_config_schema.py` with `AgentConfigV1` (schema_version="v1" pinned; `system_prompt`, `voice_id`, `tts_*`, `model`, `temperature`, `max_tokens`, `tools_enabled`, `first_message`, `language`, `turn_eagerness`, `soft_timeout_*`, `voicemail_detection_enabled`, `max_call_duration_seconds` required/optional per design.md D5; `goal` optional).
      RED: `test_agent_config_v1_requires_system_prompt_and_voice_id` — fails (schema doesn't exist).
      GREEN: validation error on missing `system_prompt`/`voice_id`; valid on a full payload; `goal` accepted as optional.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_agent_config_schema.py`
      Rollback: delete the schema file.

- [ ] 2.2 Create `backend/app/tenants/revisions_service.py`: `create_revision` (insert-only, monotonic `revision_number` per agent), `get_active_revision`, `get_revision`, `list_revisions`.
      RED: `test_create_revision_is_insert_only_and_monotonic` — fails (service doesn't exist).
      GREEN: two sequential `create_revision` calls for the same agent produce `revision_number` 1 then 2; no UPDATE/DELETE statement is ever issued (assert via a SQL-statement-capturing fixture or direct row-count check after calls).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_revisions_service.py -k monotonic`
      Rollback: delete the service module.

- [ ] 2.3 Add `activate_revision` and `rollback_to_revision` to `revisions_service.py`: rollback copies the target revision's config into a NEW row (`source="rollback"`), then activates it — never reactivates or mutates the old row.
      RED: `test_rollback_creates_new_revision_not_reactivation` — fails (function doesn't exist).
      GREEN: rollback to revision 1 while revision 3 is active produces revision 4 (new id, `revision_number=4`, `source="rollback"`) with revision 1's config; `active_revision_id` now points at revision 4; revision 1's row is untouched.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_revisions_service.py -k rollback`
      Rollback: delete the two functions; revert commit.

- [ ] 2.4 Add API endpoints: `PATCH /agents/{agent_id}/config` (validate → create_revision(source="api") → activate → enqueue EL sync), `GET /agents/{agent_id}/revisions`, `GET /agents/{agent_id}/revisions/{id}`, `POST /agents/{agent_id}/revisions/{id}/rollback`.
      RED: `test_patch_agent_config_creates_and_activates_revision`, `test_list_revisions_returns_ordered_history`, `test_rollback_endpoint_activates_new_revision` — all fail (routes don't exist, 404).
      GREEN: PATCH with a valid `AgentConfigV1` payload returns 200 and the agent's `active_revision_id` changes; GET list returns all revisions newest-first; rollback POST returns the new revision and updates `active_revision_id`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_revisions_router.py`
      Rollback: remove the route handlers; revert commit.

- [ ] 2.5 Wire the EL sync enqueue in the PATCH/rollback write paths, reusing `ElevenLabsService.sync_agent_config` / `_verify_synced_config` unchanged; record sync status on the revision row.
      RED: `test_patch_agent_config_enqueues_el_sync` — fails (sync not wired; mocked `sync_agent_config` not called).
      GREEN: PATCH triggers exactly one `sync_agent_config` call with the newly-activated revision's config; sync status recorded on the revision.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_revisions_router.py -k sync`
      Rollback: remove the sync-enqueue call from the write paths.

## Phase 3: Runtime Reads Active Revision

- [ ] 3.1 Modify `backend/app/prompts/loader.py`'s `render_for_agent` to read `agent.active_revision_id → agent_config_revisions.config.system_prompt` instead of calling `load_agent_system_prompt` (filesystem) at runtime. Keep `load_agent_system_prompt` as a helper used only by the import migration (task 1.4).
      RED: `test_render_for_agent_reads_active_revision_system_prompt` — fails (loader still reads filesystem at runtime).
      GREEN: an agent whose active revision's `system_prompt` differs from its filesystem `system-prompt.md` renders the REVISION's content, not the file's.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/prompts/test_loader.py -k render_for_agent`
      Rollback: revert the loader change; filesystem read restored (file was never deleted per D6, so this is a clean revert).

- [ ] 3.2 Verify no regression: existing `render_for_agent` tests covering the DB-column fallback and hardcoded-template fallback paths still pass unchanged (those fallback tiers are untouched by this task — only the top-priority filesystem tier is replaced).
      RED: n/a — regression check on existing tests.
      GREEN: `tests/unit/prompts/test_loader.py` full file passes with zero modifications to the fallback-tier tests.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/prompts/test_loader.py`
      Rollback: n/a (verification task).

## Phase 4a: Live-Call Routes + Initiation Webhook (highest risk — do not combine with other tasks)

- [ ] 4a.1 Add `/voice/{client_id}/agents/{agent_id}/custom-llm/chat/completions` route in `backend/app/voice/webhook.py`. Both `client_id` and `agent_id` resolved from the URL path; replace the per-turn `get_default_agent(db, client_id)` call (confirmed at `webhook.py:1026`) with the path-resolved agent.
      RED: `test_agent_scoped_custom_llm_route_reaches_non_default_agent` — fails (route doesn't exist; `quintana-seguros`'s `leads-agent` is unreachable).
      GREEN: POST to the new route with `leads-agent`'s id returns a response reflecting `leads-agent`'s config (e.g. its system prompt), not `jaumpablo`'s.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_webhook.py -k agent_scoped`
      Rollback: remove the new route; `_process_custom_llm_request` reverts to the pre-task-3 default-agent resolution only if task 3 is also reverted — otherwise it reverts to reading the (now-correct) active revision for whatever agent `get_default_agent` resolves.

- [ ] 4a.2 Gate the legacy routes (`/custom-llm`, `/{client_id}/custom-llm/chat/completions`) to succeed only when the resolved client has exactly one active agent; return an explicit error (not a silent pick) for 0 or >1 active agents. Emit the existing deprecation log (`custom_llm_legacy_route_used` pattern) on every successful legacy-route hit.
      RED: `test_legacy_route_fails_closed_for_multi_agent_client`, `test_legacy_route_succeeds_for_single_agent_client` — first fails because the legacy route currently always succeeds via `get_default_agent`; second is a regression guard.
      GREEN: `quintana-seguros` (2 active agents) → legacy route returns an explicit error; `qora-demo` (1 active agent) → legacy route succeeds with a deprecation log entry.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_webhook.py -k legacy_route`
      Rollback: remove the active-agent-count gate; legacy route reverts to `get_default_agent` for all clients.

- [ ] 4a.3 Modify `backend/app/voice/initiation.py` to resolve the Qora agent via `agents.elevenlabs_agent_id == resolved_agent_id_from_EL_payload` first, falling back to the D2 fail-closed single-active-agent path only when EL does not supply an `agent_id`.
      RED: `test_initiation_webhook_resolves_agent_from_elevenlabs_agent_id` — fails (handler currently ignores `body.agent_id`, confirmed in exploration.md).
      GREEN: a payload with a known EL `agent_id` resolves to the matching Qora agent, verified via `agent_name` in the response's `dynamic_variables` matching the non-default agent's name.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_initiation.py -k resolves_agent`
      Rollback: revert to unconditional `get_default_agent(session, resolved_client_id)`.

- [ ] 4a.4 Modify `backend/app/calls/service.py`'s `create_session` fallback: when `agent_id` is `None`, resolve via the D2 fail-closed single-active-agent path (not unconditional `get_default_agent`).
      RED: `test_create_session_without_agent_id_fails_closed_for_multi_agent_client` — fails (currently always resolves via `get_default_agent`, confirmed in `test_agent_propagation.py`).
      GREEN: `create_session` without `agent_id` raises an explicit error for a 2-active-agent client; still resolves automatically for a 1-active-agent client.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/calls/test_agent_propagation.py`
      Rollback: revert to unconditional `get_default_agent` fallback.

- [ ] 4a.5 Delete `get_default_agent` and `set_default_agent` from `backend/app/tenants/service.py`; redefine the `deactivate_agent` sole-guard to count active agents per client (D3) instead of filtering on `is_default`.
      RED: `test_deactivate_agent_blocks_last_active_agent_regardless_of_is_default` — fails (current guard only blocks deactivating the sole active `is_default` agent, not the sole active agent generally).
      GREEN: deactivating a client's only active agent is blocked even if that agent's `is_default` is False; deactivating one of two active agents succeeds.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_service.py -k deactivate`
      Rollback: restore `get_default_agent`/`set_default_agent`; restore the `is_default`-filtered guard. (Only safe to revert if no task-4a/4b call site has shipped yet; otherwise this is the point-of-no-return task in the chain — flagged explicitly in review_focus for task 4a's PR.)

- [ ] 4a.6 Full regression: `grep -rn "get_default_agent\|set_default_agent" backend/app` returns no results; full backend suite passes.
      Check: `grep -rn "get_default_agent\|set_default_agent" backend/app && cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification task; if it fails, fix remaining call sites before closing 4a.

## Phase 4b: Scheduler + Recontact + Tool + Outbound + Calls + Leads Preview

- [ ] 4b.1 Modify `backend/app/scheduler/router.py` (manual schedule creation, ~lines 150-152) and `backend/app/scheduler/service.py` (`auto_schedule`, retry/recontact, ~lines 524-526, 677-679, 1021, 1068) to require/propagate explicit `agent_id`, falling back to D2's fail-closed single-active-agent path only where no session/schedule already carries one.
      RED: `test_auto_schedule_inherits_source_session_agent_id`, `test_auto_schedule_fails_closed_without_agent_id_for_multi_agent_client` — first already partially covered by existing Phase 7 tests (extend, don't duplicate); second is new.
      GREEN: `auto_schedule` always inherits the source session's `agent_id` when present; raises an explicit error when it must fall back and the client has 0 or >1 active agents.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/scheduler/test_agent_propagation.py`
      Rollback: revert to unconditional `get_default_agent` fallback at each listed line.

- [ ] 4b.2 Modify `backend/app/tools/schedule_followup.py` (~lines 237-240) to resolve `agent_id` from the active call session instead of `get_default_agent`.
      RED: `test_schedule_followup_tool_uses_session_agent_id` — fails (tool currently resolves default agent unconditionally).
      GREEN: the tool's created `ScheduledCall.agent_id` matches the calling session's `agent_id`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tools/test_schedule_followup.py`
      Rollback: revert to `get_default_agent` fallback.

- [ ] 4b.3 Modify `backend/app/outbound/router.py` (~line 238) to require an explicit `agent_id` on the outbound trigger request — no silent default.
      RED: `test_outbound_trigger_requires_explicit_agent_id` — fails (endpoint currently resolves default agent when omitted).
      GREEN: request without `agent_id` returns a validation error; request with `agent_id` creates a session carrying that agent.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/outbound/test_router.py`
      Rollback: restore the default-agent fallback on the endpoint.

- [ ] 4b.4 Modify `backend/app/leads/router.py` (~lines 812-815) so the lead voice-context preview endpoint requires an explicit `agent_id` param instead of resolving default.
      RED: `test_lead_voice_context_preview_requires_agent_id` — fails (endpoint currently resolves default agent).
      GREEN: preview request without `agent_id` returns a validation error; with `agent_id` returns the matching agent's context preview, verified against a non-default agent.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/leads/test_router.py -k voice_context`
      Rollback: restore the default-agent resolution on the endpoint.

- [ ] 4b.5 Full regression for 4b: re-run all of `tests/unit/scheduler/`, `tests/unit/tools/`, `tests/unit/outbound/`, `tests/unit/leads/`, `tests/unit/calls/`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/scheduler/ tests/unit/tools/ tests/unit/outbound/ tests/unit/leads/ tests/unit/calls/`
      Rollback: n/a — verification task.

## Phase 5: ElevenLabs Projection → Agent-Scoped Route

- [ ] 5.1 Update `backend/app/elevenlabs/service.py`'s route/URL construction for the sync webhook target to the agent-scoped path (`/voice/{client_id}/agents/{agent_id}/custom-llm/chat/completions`); `_build_config_payload` itself stays unchanged (confirmed already agent-scoped and NULL-means-skip correct).
      RED: `test_sync_agent_config_sets_agent_scoped_custom_llm_url` — fails (current URL construction is client-scoped only).
      GREEN: `sync_agent_config` for a given agent PATCHes EL with the agent-scoped URL containing that agent's id.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_service.py -k custom_llm_url`
      Rollback: revert URL construction to client-scoped; legacy route (gated per 4a.2) continues to serve single-active-agent clients.

## Phase 6: Minimal Admin UI

- [ ] 6.1 Remove `useMakeAgentDefault` hook usage and "Make default"/"Default" badge from `frontend/src/features/admin/agents-section.tsx` and `agents-panel.tsx`.
      RED: `agents-panel.test.tsx` updated to assert no "Default" badge/button renders — fails against current component.
      GREEN: component renders without any default-related UI; existing `is_default` test fixtures updated or removed per the `AGENTS.md`-adjacent convention of not inventing new abstractions.
      Check: `cd frontend && npm test -- agents-panel`
      Rollback: revert component changes; restore the hook and badge.

- [ ] 6.2 Add a revisions list panel: active revision number, sync status, list of past revisions (source, created_by, created_at, note), rollback button per past revision.
      RED: `agents-panel.test.tsx` new test `renders revisions list and rollback action` — fails (panel doesn't exist).
      GREEN: panel renders revision rows from the task 2.4 list endpoint; clicking rollback calls the rollback endpoint and the active revision number updates.
      Check: `cd frontend && npm test -- agents-panel`
      Rollback: remove the new panel component; revisions remain accessible via API only.

## Phase 7: Prod Rollout + Verification

- [ ] 7.1 Confirm the schema + import migration runs automatically at the existing deploy entrypoint (no SSH); verify via API that every prod agent has a non-null `active_revision_id` and exactly one `source=import` revision.
      Check: API calls only — `GET /agents/{agent_id}/revisions` for both prod EL-mapped agents.
      Rollback: if the migration fails at deploy, the existing deploy entrypoint's failure behavior applies (deploy does not complete); no manual DB intervention needed since the migration is additive-only.

- [ ] 7.2 Re-sync the two prod EL agents (`agent_3001m3x8c6wfeqa8j7gz2qwysyg6` Quintana leads-agent, `agent_4701m3ynzr4jfb0tyj836t437rbh` qora-demo explainer) to agent-scoped routes via the ElevenLabs API.
      Check: `GET` the EL agent config via API post-sync; assert the custom-LLM URL field contains the agent-scoped path.
      Rollback: re-PATCH both EL agents back to the legacy client-scoped URL via the API.

- [ ] 7.3 Verify both re-synced prod EL agents using ElevenLabs `simulate-conversation` (Telnyx blocked — no real calls).
      Check: ElevenLabs `simulate-conversation` API call against both agent ids; assert a successful conversation turn is returned.
      Rollback: n/a — verification only; a failure here blocks closing task 7, not a rollback trigger by itself (re-sync to legacy routes per 7.2's rollback if simulation reveals a routing defect).

- [ ] 7.4 Run the full backend suite before closing the change.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.
