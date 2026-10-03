# Tasks: Data MCP + Onboarding Harness

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~1,800 total across 6 units |
| 800-line budget risk | Low — combined total is well under budget |
| 400-line budget risk | Low — every unit estimated at or under ~380 lines |
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
| 1 | MCP scaffold + client tools (`list_clients`, `get_client`) | PR 1 | New dependency + new entrypoint. Rollback: revert PR. |
| 2 | MCP agent tools (`list_agents`, `get_agent` with provenance) | PR 2 | Depends on PR 1. Rollback: revert PR. |
| 3 | MCP lead/call tools (`list_leads`, `get_lead`, `list_calls`, `get_call`) | PR 3 | Depends on PR 1. Rollback: revert PR. |
| 4 | Harness scaffold + spec schema + dry-run | PR 4 | New entrypoint + router. Rollback: revert PR. |
| 5 | Harness provisioning + verification checklist | PR 5 | Depends on PR 4. Rollback: revert PR. |
| 6 | Docs: README + skill pointer update | PR 6 | Depends on PR 1-5 existing to document. Rollback: revert PR. |

## Known Environmental Failures

None identified at the time of writing. If the base backend suite has pre-existing unrelated failures at apply time, they must be named explicitly here before any task reports `status: completed`.

## Phase 1: MCP Scaffold + Client Tools

- [ ] 1.1 Add the `mcp` dependency to `backend/pyproject.toml`; create `backend/app/mcp/server.py` (server instance, empty tool registry) and `backend/app/mcp/__main__.py` (`python -m app.mcp` entrypoint, stdio transport).
      RED: `test_mcp_module_is_importable_and_starts` (new file `backend/tests/unit/mcp/test_server.py`) — fails (package not installed / module doesn't exist).
      GREEN: `python -m app.mcp --help`-equivalent (or a test harness constructing the server object) succeeds without starting a long-running process in the test.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_server.py`
      Rollback: remove the dependency line and the new module; revert commit.

- [ ] 1.2 Add `backend/app/mcp/schemas.py` with the client tool I/O shapes; add `backend/app/mcp/tools/clients.py` with `list_clients`/`get_client`, calling the existing `app/clients/service.py` (or `tenants/service.py`, whichever owns client reads) in-process.
      RED: `test_list_clients_returns_identity_and_config_shape`, `test_get_client_returns_none_for_unknown_id` (new file `backend/tests/unit/mcp/test_tools_clients.py`) — fail (module doesn't exist).
      GREEN: both tools return the documented shape against a seeded tmp DB; `get_client` for an unknown id returns an explicit absence, not an exception.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_tools_clients.py`
      Rollback: delete the files; revert commit.

- [ ] 1.3 Never-secrets schema guard, established now so later tool additions inherit it: a test enumerating every registered tool's output Pydantic model and asserting no field name/type matches a forbidden secret-shape pattern (`ciphertext`, `api_key`, `secret`, `token`).
      RED: `test_no_registered_tool_output_contains_secret_shaped_field` (new file `backend/tests/unit/mcp/test_no_secrets_leak.py`) — fails if the test itself is wrong (no tools registered yet) or passes vacuously; written to fail loudly (not vacuously) once any tool is registered with a violating field, verified by a temporary intentionally-bad fixture model in the test file itself.
      GREEN: the guard passes against the real registered tools from 1.2; the temporary bad-fixture assertion (if added for self-verification) is removed before merge.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_no_secrets_leak.py`
      Rollback: delete the file; revert commit. (Re-run this guard, not just the file's own removal, for every subsequent task that registers a new tool.)

## Phase 2: MCP Agent Tools

- [ ] 2.1 Add `backend/app/mcp/tools/agents.py` with `list_agents`/`get_agent`, the latter returning effective config with per-field provenance (which layer — agent override, client default, Qora standard — each value resolved from).
      RED: `test_get_agent_returns_provenance_per_field`, `test_list_agents_returns_identity_shape` (new file `backend/tests/unit/mcp/test_tools_agents.py`) — fail (module doesn't exist).
      GREEN: a seeded agent with one overridden field and one inherited field returns correct provenance for each; `list_agents` returns identity/config shape for every agent of a given client.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_tools_agents.py`
      Rollback: delete the file; revert commit.

- [ ] 2.2 Re-run 1.3's never-secrets guard against the newly registered agent tools.
      RED: n/a — guard already exists; confirms it still passes with the new tools registered.
      GREEN: `test_no_registered_tool_output_contains_secret_shaped_field` passes with `get_agent`/`list_agents` included.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_no_secrets_leak.py`
      Rollback: n/a — regression guard; a failure here blocks closing task 2.

## Phase 3: MCP Lead/Call Tools

- [ ] 3.1 Add `backend/app/mcp/tools/leads.py` with `list_leads` (client_id required, filters, pagination) and `get_lead`.
      RED: `test_list_leads_requires_client_id`, `test_list_leads_paginates_with_hard_max`, `test_get_lead_requires_client_id` (new file `backend/tests/unit/mcp/test_tools_leads.py`) — fail (module doesn't exist).
      GREEN: a call missing `client_id` is rejected before any DB query; pagination caps at the documented hard max page size even when a larger size is requested.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_tools_leads.py`
      Rollback: delete the file; revert commit.

- [ ] 3.2 Add `backend/app/mcp/tools/calls.py` with `list_calls` (client_id required) and `get_call` (includes post-call analysis).
      RED: `test_list_calls_requires_client_id`, `test_get_call_includes_analysis` (new file `backend/tests/unit/mcp/test_tools_calls.py`) — fail (module doesn't exist).
      GREEN: `list_calls` without `client_id` is rejected; `get_call` for a seeded call with analysis returns the analysis payload.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_tools_calls.py`
      Rollback: delete the file; revert commit.

- [ ] 3.3 Re-run 1.3's never-secrets guard against the full tool set; confirm all eight tools are registered.
      RED: n/a — guard already exists.
      GREEN: `test_no_registered_tool_output_contains_secret_shaped_field` passes with all eight tools; a new assertion confirms exactly eight tools are registered (catches an accidental omission or duplicate).
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/mcp/test_no_secrets_leak.py`
      Rollback: n/a — regression guard; a failure here blocks closing task 3.

## Phase 4: Harness Scaffold + Spec Schema + Dry-Run

- [ ] 4.1 Create `backend/app/onboarding/spec.py` (`OnboardingSpec`, `CrmIntegrationSpec` with `extra="forbid"` and no secret-shaped field) and `backend/app/onboarding/__main__.py` (CLI entrypoint parsing a spec file).
      RED: `test_onboarding_spec_rejects_unknown_field`, `test_crm_integration_spec_has_no_secret_field` (new file `backend/tests/unit/onboarding/test_spec.py`) — fail (module doesn't exist).
      GREEN: constructing `CrmIntegrationSpec` with an extra `api_key`/`secret` field raises a Pydantic validation error; the spec's field set contains no credential-shaped field by inspection.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_spec.py`
      Rollback: delete the files; revert commit.

- [ ] 4.2 Create `backend/app/onboarding/service.py`'s dry-run path: validates spec shape, vertical existence (if given), and client_id/agent-slug conflicts, without writing any row.
      RED: `test_dry_run_validates_without_writing`, `test_dry_run_detects_existing_client_id_conflict` (new file `backend/tests/unit/onboarding/test_service.py`) — fail (function doesn't exist).
      GREEN: `run_onboarding(spec, dry_run=True)` against a clean DB writes zero rows; against a DB with a pre-existing client of the same id, the dry-run report names the conflict.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_service.py -k dry_run`
      Rollback: delete the dry-run path; revert commit.

- [ ] 4.3 Create `backend/app/onboarding/router.py` (`POST /api/v1/admin/onboarding`, superadmin-gated) calling the same `dry_run`-capable service function; mount it in `backend/app/main.py`.
      RED: `test_post_onboarding_requires_superadmin`, `test_post_onboarding_dry_run_via_endpoint` (new file `backend/tests/unit/onboarding/test_router.py`) — fail (endpoint doesn't exist, 404).
      GREEN: non-superadmin → 403; superadmin dry-run request → 200, zero rows written, matching the CLI's dry-run result for the same spec.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_router.py`
      Rollback: remove the route and the `main.py` mount; revert commit.

## Phase 5: Harness Provisioning + Verification Checklist

- [ ] 5.1 Implement the real-run provisioning path in `onboarding/service.py`: create client (revision 1), create agent (revision 1), idempotent per entity (an existing entity is reported, not re-created or erroring).
      RED: `test_real_run_creates_client_and_agent`, `test_real_run_is_idempotent_on_rerun` — fail (real-run path doesn't exist, only dry-run does).
      GREEN: a first run creates both entities with active revisions; a second identical run reports `"already exists"` for both, creates no duplicates.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_service.py -k real_run`
      Rollback: revert commit; dry-run path (task 4) remains functional.

- [ ] 5.2 Add analysis-profile attachment (when `analysis_vertical` given) and `client_integrations` row creation (when `crm_integration` given, non-secret fields only) to the provisioning path.
      RED: `test_real_run_attaches_analysis_profile_from_vertical`, `test_real_run_creates_integration_row_without_secret` — fail (not implemented).
      GREEN: a spec with `analysis_vertical` results in an attached profile matching the vertical; a spec with `crm_integration` results in a `client_integrations` row with matching non-secret fields and zero `client_secrets` rows created.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_service.py -k "profile or integration"`
      Rollback: revert commit; client/agent creation (5.1) remains functional without these optional steps.

- [ ] 5.3 Add the EL-sync trigger (only when the agent's `elevenlabs_agent_id` is set) and the verification checklist builder (active revisions, effective-config completeness, profile/integration/sync status, plus the printed manual dashboard steps from the skill).
      RED: `test_real_run_triggers_el_sync_only_when_agent_id_set`, `test_verification_checklist_names_every_automated_and_manual_step` — fail (not implemented).
      GREEN: a spec without `elevenlabs_agent_id` triggers no sync call; a spec with it set calls the existing `sync_agent_config` entrypoint; the checklist's output names every automated step's outcome and every manual Phase 1/5 step from `skills/qora-client-agent-setup/SKILL.md`.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_service.py -k "sync or checklist"`
      Rollback: revert commit; 5.1-5.2's provisioning remains functional without the sync trigger or full checklist.

- [ ] 5.4 CLI/endpoint parity: assert the CLI and `POST /api/v1/admin/onboarding` produce identical checklist output for the same spec against the same tmp DB.
      RED: `test_cli_and_endpoint_produce_identical_results` — fails if either entrypoint diverges from the shared service function.
      GREEN: byte-identical (or structurally-identical, field for field) checklist output from both entrypoints.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider tests/unit/onboarding/test_router.py -k parity`
      Rollback: n/a — regression guard; a failure here indicates one entrypoint diverged from the shared service, not a separate revert target.

## Phase 6: Docs

- [ ] 6.1 Add a README section describing `python -m app.mcp` and `python -m app.onboarding` / `POST /api/v1/admin/onboarding` — what each does, how to invoke it, and the never-secrets / client_id-required guarantees.
      Check: manual review — README renders correctly, both tools are discoverable from the top-level README.
      Rollback: revert the README section.

- [ ] 6.2 Update `skills/qora-client-agent-setup/SKILL.md`'s Decision Gates / Phase 3-4 content to point at the onboarding harness for the DB-and-filesystem steps it now automates, keeping Phase 1/2/5 (dashboard, env vars, verification) unchanged.
      Check: manual review — the skill still reads coherently end-to-end; Phase 1/2/5 content is untouched; Phase 3-4 references the harness as the primary path, with the prior manual steps kept as the fallback/reference for what the harness does under the hood.
      Rollback: revert the skill file; prior content restored from git history.

- [ ] 6.3 Run the full backend suite one final time before closing the change.
      Check: `cd backend && uv run pytest -q -p no:cacheprovider`
      Rollback: n/a — verification gate; any failure blocks closing the change until fixed or explicitly triaged as pre-existing/unrelated.
