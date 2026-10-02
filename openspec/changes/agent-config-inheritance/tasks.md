# Tasks: Qora Config Phase 1b — Standard/Client/Agent Inheritance

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,850 total across 7 units |
| 800-line budget risk | High if combined; Low per-unit when kept separate |
| 400-line budget risk | Low — every unit estimated at or under ~350 lines |
| Chained PRs recommended | Yes — seven review slices, strictly ordered, mirroring 1a's precedent |
| Suggested split | One PR per numbered task below; task 5 (behavioral cutover) is never combined with any other task |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Field-policy registry + Qora standard module | PR 1 | Additive; depends on 1a's `AgentConfigV1` field list. Rollback: revert PR, pure code. |
| 2 | Resolver + provenance | PR 2 | Additive; depends on PR 1. Rollback: revert PR, pure function. |
| 3 | Client revisions schema/migration/API | PR 3 | Additive; depends on 1a's revision mechanics being reusable. Rollback: `alembic downgrade -1`. |
| 4 | AgentConfigV2 overrides + write validation + grandfathering | PR 4 | Additive (new revisions only); depends on PR 1–2. Rollback: revert PR, 1a's V1 write path untouched. |
| 5 | Runtime + EL projection consume effective config, client-change propagation | PR 5 | Highest risk — behavioral cutover, gated on the equivalence test. Depends on PR 1–4. Rollback: revert PR only. |
| 6 | Admin API effective config + minimal UI badges/locks | PR 6 | Depends on PR 2–3. Rollback: revert PR, frontend-mostly. |
| 7 | Prod rollout via API + EL simulate-conversation verification | PR 7 | Depends on all prior tasks. Rollback: standard resync to prior version; DB rollback only if no client revisions created since deploy. |

## Phase 1: Field-Policy Registry + Qora Standard Module

- [ ] 1.1 Create `backend/app/tenants/field_policy.py` with the `FIELD_POLICY` registry (every `AgentConfigV1` field from 1a, mapped per design.md's field-policy table, plus every new locked standard enumerated in design.md).
      RED: `test_field_policy_registry_is_exhaustive_for_agent_config_v1` (new file `backend/tests/unit/tenants/test_field_policy.py`) — fails because the registry does not exist yet.
      GREEN: every field name in 1a's `AgentConfigV1` model fields is present in `FIELD_POLICY` with exactly one of the four policy values; test asserts via introspection against `AgentConfigV1.model_fields`, not a hardcoded field list, so it fails loudly if 1a's schema gains a field this registry does not know about.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_field_policy.py`
      Rollback: delete the file; revert commit.

- [ ] 1.2 Create `backend/app/tenants/config_standard.py` with `AgentConfigStandard` (every `locked` field's value per design.md) and `STANDARD_VERSION: str`.
      RED: `test_agent_config_standard_has_value_for_every_locked_field` — fails (module doesn't exist).
      GREEN: every field whose `FIELD_POLICY` entry is `locked` has a non-null value in `AgentConfigStandard`; `STANDARD_VERSION` is a non-empty string.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_config_standard.py`
      Rollback: delete the file; revert commit.

- [x] 1.3 Production values confirmed on 2026-10-02 (design.md D17): standard `model = gpt-4.1-mini`, `tts_model = eleven_v4_turbo`.
      Follow-up in 1b rollout (task 7): new revisions for `qora-explainer` and `jaumpablo` that drop their `gpt-4o` / `eleven_flash_v2_5` overrides so they inherit the standard; verify with simulate-conversation.
      Rollback: rollback endpoint restores the previous agent revision.

## Phase 2: Resolver + Provenance

- [ ] 2.1 Create `backend/app/tenants/config_resolver.py` with `EffectiveField`, `EffectiveConfig`, and `resolve_effective_config(standard, client_overrides, agent_overrides)`.
      RED: `test_resolve_locked_field_always_returns_standard`, `test_resolve_agent_required_field_returns_agent_value`, `test_resolve_client_only_field_prefers_client_over_standard`, `test_resolve_overridable_field_prefers_agent_then_client_then_standard` (new file `backend/tests/unit/tenants/test_config_resolver.py`) — all fail (resolver doesn't exist).
      GREEN: each policy type resolves to the correct value AND correct provenance across every override-present/absent combination in the test matrix.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_config_resolver.py`
      Rollback: delete the file; revert commit.

- [ ] 2.2 Add a purity/determinism regression test: calling `resolve_effective_config` twice with identical inputs produces identical output, and no DB session or HTTP client is importable from the module.
      RED: `test_resolver_module_has_no_db_or_io_imports` — fails only if a future edit accidentally introduces an import; currently a guard, not a RED-first behavior test.
      GREEN: static import check passes; two calls with identical inputs produce `==` results.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_config_resolver.py -k purity`
      Rollback: delete the test; no production code to revert.

## Phase 3: Client Revisions Schema + Migration + API

- [ ] 3.1 Add `ClientConfigRevision` model (`backend/app/tenants/models.py`): id, client_id FK, revision_number, config (Text/JSON, sparse), schema_version, source enum, created_by, created_at, note. Add `Client.active_config_revision_id` FK column. Add `CallSession.standard_version`, `CallSession.client_config_revision_id` columns.
      RED: `test_client_config_revision_model_fields_exist` (new file `backend/tests/unit/tenants/test_client_config_revision_model.py`) — fails (model doesn't exist).
      GREEN: model added, import succeeds, columns present via `PRAGMA table_info`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_client_config_revision_model.py`
      Rollback: delete the model class and column additions; revert commit.

- [ ] 3.2 Create `backend/alembic/versions/{rev}_client_config_revisions_schema.py` chained after 1a's head: `CREATE TABLE client_config_revisions`; `ALTER TABLE clients ADD COLUMN active_config_revision_id`; `ALTER TABLE call_sessions ADD COLUMN standard_version, client_config_revision_id` (batch mode).
      RED: `test_client_config_revisions_schema_migration_creates_table` — fails against a tmp DB at 1a's head (table does not exist).
      GREEN: `alembic upgrade head` on a tmp DB creates the table and columns; `PRAGMA table_info` matches the model.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/test_alembic_tooling.py -k client_config_revisions`
      Rollback: `alembic downgrade -1` on the tmp DB; remove the revision file.

- [ ] 3.3 Generalize 1a's `revisions_service.py` helpers (`create_revision`, `activate_revision`, `rollback_to_revision`) to accept a table/model parameter, and add client-level convenience wrappers (`create_client_revision`, `activate_client_revision`, `rollback_client_revision`) that reuse the same generic functions.
      RED: `test_create_client_revision_is_insert_only_and_monotonic`, `test_client_rollback_creates_new_revision_not_reactivation` (extends `backend/tests/unit/tenants/test_revisions_service.py`) — fail (client-level functions don't exist).
      GREEN: two sequential client revision creates produce `revision_number` 1 then 2; rollback produces a new row and activates it without mutating the target row; 1a's existing agent-level tests in the same file still pass unmodified (generalization did not change agent-level behavior).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_revisions_service.py`
      Rollback: revert the generalization; restore the agent-only versions of the three functions.

- [ ] 3.4 Add API endpoints: `PATCH /clients/{client_id}/config`, `GET /clients/{client_id}/revisions`, `GET /clients/{client_id}/revisions/{id}`, `POST /clients/{client_id}/revisions/{id}/rollback`.
      RED: `test_patch_client_config_creates_and_activates_revision`, `test_list_client_revisions_returns_ordered_history`, `test_client_rollback_endpoint_activates_new_revision` (new file `backend/tests/unit/tenants/test_client_revisions_router.py`) — all fail (routes don't exist, 404).
      GREEN: PATCH with a valid sparse-override payload returns 200 and the client's `active_config_revision_id` changes; GET list returns all revisions newest-first; rollback POST returns the new revision and updates `active_config_revision_id`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_client_revisions_router.py`
      Rollback: remove the route handlers; revert commit.

## Phase 4: AgentConfigV2 Overrides + Write Validation + Grandfathering

- [ ] 4.1 Add `AgentConfigV2` (`schema_version=2`, sparse — every field optional, no inherited defaults baked in) to `backend/app/tenants/agent_config_schema.py`, alongside unchanged `AgentConfigV1`.
      RED: `test_agent_config_v2_accepts_sparse_payload` (new file `backend/tests/unit/tenants/test_agent_config_schema_v2.py`) — fails (schema doesn't exist).
      GREEN: a payload containing only `system_prompt` and `voice_id` validates successfully as `AgentConfigV2`; `AgentConfigV1`'s existing tests (1a) still pass unmodified.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_agent_config_schema_v2.py tests/unit/tenants/test_agent_config_schema.py`
      Rollback: delete `AgentConfigV2`; revert commit.

- [ ] 4.2 Add write-path validation to `create_revision` (both client and agent paths): reject any payload containing a value for a `locked` field (422, exact field list); reject a NEW agent revision missing an `agent_required` field UNLESS the agent is grandfathered for that field.
      RED: `test_create_revision_rejects_locked_field_write`, `test_create_agent_revision_rejects_missing_required_field`, `test_grandfathered_agent_existing_revision_still_resolves`, `test_grandfathered_agent_new_revision_still_requires_goal` — all fail (validation doesn't exist yet).
      GREEN: writing a `locked` field returns an explicit error listing it; a new agent revision missing `goal` is rejected for a non-grandfathered agent; a grandfathered agent's CURRENT active revision keeps resolving successfully; that same grandfathered agent's NEXT new revision is still rejected if it omits `goal`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_revisions_service.py -k "locked or required or grandfather"`
      Rollback: remove the validation calls from `create_revision`; revert commit.

- [ ] 4.3 Add brand-new-agent creation validation: creating a new agent (not a revision on an existing one) always requires every `agent_required` field, with no grandfathering exception.
      RED: `test_create_new_agent_without_voice_id_is_rejected` — fails (agent creation currently allows a missing `voice_id` to pass through to 1a's optional-`goal` path, confirmed in 1a's design.md D5/D6).
      GREEN: creating a new agent without `voice_id`, `system_prompt`, or `goal` is rejected with the missing field named; creating one with all three succeeds.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_service.py -k create_agent`
      Rollback: revert the agent-creation validation; restore 1a's optional-`goal` creation path.

- [ ] 4.4 Add the admin-visible `"incomplete"` marker for grandfathered agents (API field + UI badge placeholder, UI itself lands in task 6).
      RED: `test_grandfathered_agent_marked_incomplete_in_api_response` — fails (field doesn't exist).
      GREEN: an agent lacking `goal` on its active revision returns `incomplete: true` from the agent detail API; a complete agent returns `incomplete: false`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_router.py -k incomplete`
      Rollback: remove the field from the response schema; revert commit.

## Phase 5: Runtime + EL Projection Cutover + Client Propagation (highest risk — do not combine with other tasks)

- [ ] 5.1 **Equivalence test (hard acceptance criterion)**: for every agent seeded by 1a's seeders, compute `resolve_effective_config` using empty client overrides and the agent's existing 1a `AgentConfigV1` values as agent overrides; assert every field's resolved VALUE AND PROVENANCE matches what 1a's flat revision produced before this change, for every field 1a already resolved.
      RED: `test_effective_config_unchanged_for_every_existing_agent` (new file `backend/tests/unit/tenants/test_config_equivalence.py`) — fails until tasks 1–4 are complete and correctly wired.
      GREEN: zero diffs across every seeded agent's resolved fields, both value and provenance (provenance for a V1-sourced field is always `agent`, since V1 has no inheritance awareness).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_config_equivalence.py`
      Rollback: n/a — this is a gating verification task; a failure blocks task 5.2 from proceeding, it is not reverted.

- [ ] 5.2 Modify `backend/app/voice/context.py`'s `build_voice_context` to call `resolve_effective_config` (via the client's and agent's active revisions + the standard) instead of reading `Agent.*` columns directly.
      RED: `test_build_voice_context_uses_resolved_effective_config` — fails (context builder still reads `Agent.*` directly).
      GREEN: an agent whose client has overridden `tts_speed` produces a `VoiceSessionContext.tts_speed` matching the CLIENT'S override, not the agent's raw column value, when the agent itself has not overridden it.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/voice/test_context.py`
      Rollback: revert the loader change; `build_voice_context` reverts to reading `Agent.*` directly (task 5.1's equivalence test guarantees this revert is safe — behavior was unchanged going in).

- [ ] 5.3 Modify `backend/app/elevenlabs/service.py`'s `_build_config_payload` to read from `EffectiveConfig` instead of `Agent.*`.
      RED: `test_build_config_payload_uses_resolved_effective_config` — fails (payload builder still reads `Agent.*` directly).
      GREEN: the EL PATCH payload reflects a client-level override when the agent has not set its own value for that field.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/elevenlabs/test_service.py -k effective_config`
      Rollback: revert the payload builder change; restore direct `Agent.*` reads.

- [ ] 5.4 Modify `backend/app/calls/service.py`'s `create_session` to record `standard_version` and `client_config_revision_id` alongside 1a's existing `agent_config_revision_id`.
      RED: `test_create_session_records_standard_version_and_client_revision` — fails (columns exist from task 3.1 but are never populated).
      GREEN: a new session's `standard_version`, `client_config_revision_id`, and `agent_config_revision_id` all match what was active at creation time.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/calls/test_agent_propagation.py -k standard_version`
      Rollback: revert the population logic; columns stay present but unused (additive).

- [ ] 5.5 Add client-revision activation propagation: activating a new client config revision re-resolves and enqueues an EL projection sync for every active agent of that client, reusing 1a's per-agent sync mechanism.
      RED: `test_activate_client_revision_syncs_every_active_agent` — fails (propagation doesn't exist).
      GREEN: activating a client revision for a client with 2 active agents enqueues exactly 2 sync calls, one per agent, each using that agent's freshly re-resolved effective config.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_client_revisions_router.py -k propagation`
      Rollback: remove the propagation call from `activate_client_revision`; client revisions stay activatable but inert until a future agent-level write triggers its own sync.

- [ ] 5.6 Add the standard-version explicit resync endpoint with drift detection: `POST /admin/standards/resync` re-resolves every active agent platform-wide and enqueues a sync ONLY for agents whose resolved config actually changed.
      RED: `test_standard_resync_does_not_auto_trigger_on_version_bump`, `test_standard_resync_only_syncs_drifted_agents` — fail (endpoint and drift check don't exist).
      GREEN: bumping `STANDARD_VERSION` in a test fixture enqueues zero syncs until the endpoint is explicitly called; calling it syncs only agents whose effective config differs from their last-synced config, confirmed via a fixture with one drifted and one non-drifted agent.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_standards_resync.py`
      Rollback: remove the endpoint; standard version changes have zero runtime effect until a future deploy adds a sync trigger.

## Phase 6: Admin API Effective Config + Minimal UI

- [ ] 6.1 Add `GET /agents/{agent_id}/effective-config` returning every field's resolved value and provenance.
      RED: `test_effective_config_endpoint_returns_value_and_provenance_per_field` — fails (endpoint doesn't exist, 404).
      GREEN: response includes every `FIELD_POLICY` field with its resolved value and provenance (`standard`/`client`/`agent`), matching what the task 5.1 equivalence test and task 2 resolver tests independently verify.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/tenants/test_router.py -k effective_config`
      Rollback: remove the route handler; revert commit.

- [ ] 6.2 Add provenance badge per field and read-only rendering for locked fields to `frontend/src/features/admin/agents-section.tsx` (or the agent config form component).
      RED: `agents-panel.test.tsx` new tests `renders provenance badge per field` and `renders locked fields as read-only` — fail (badges/locks don't exist in the component).
      GREEN: each field in the rendered form shows a "Qora standard" / "Client" / "Agent" badge matching the API response's provenance; fields with provenance `standard` AND policy `locked` render with no editable input, not merely a disabled one.
      Check: `cd frontend && npm test -- agents-panel`
      Rollback: remove the badge/lock rendering; form reverts to editable-for-everything (task 6.1's backend validation still rejects invalid writes server-side, so this is a UX-only regression, not a data-safety one).

## Phase 7: Prod Rollout + Verification

- [ ] 7.1 Confirm the client-revisions schema migration runs automatically at the existing deploy entrypoint (no SSH); verify via API that every prod client has a non-null `active_config_revision_id` (or null is acceptable if no client-level overrides exist yet — sparse by design) and that `resolve_effective_config` output for both 1a's prod EL-mapped agents matches their pre-1b behavior.
      Check: API calls only — `GET /agents/{agent_id}/effective-config` for both prod EL-mapped agents from 1a's success criteria.
      Rollback: migration is additive-only; deploy entrypoint's own failure behavior applies if it fails.

- [ ] 7.2 Re-sync both prod EL-mapped agents via the EL projection path now reading from `EffectiveConfig`; verify via the ElevenLabs API that the synced config matches the resolved effective config exactly.
      Check: `GET` the EL agent config via API post-sync; compare field-by-field against `GET /agents/{agent_id}/effective-config`.
      Rollback: re-activate the agents' prior revisions via the rollback endpoint (1a mechanics); re-sync.

- [ ] 7.3 Verify both re-synced prod EL agents using ElevenLabs `simulate-conversation` (Telnyx blocked — no real calls), matching 1a's verification pattern.
      Check: ElevenLabs `simulate-conversation` API call against both agent ids; assert a successful conversation turn is returned.
      Rollback: n/a — verification only; a failure here blocks closing task 7, triggering 7.2's rollback if it reveals a resolution defect.

- [ ] 7.4 Run the full backend suite before closing the change.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.
