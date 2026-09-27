# Apply progress: multi-tenant-readiness

## Status and scope

Consumed native `gentle-ai.sdd-status` v2: OpenSpec, `applyState=ready`, `nextRecommended=apply`, no blockers; repo-local workspace `/Users/mati/Desktop/Qora`, allowed root `/Users/mati/Desktop/Qora`. Status noted a future `"/"` edit-root warning; no files outside the user's narrower allowed surfaces were edited. Session delivery: auto-chain, stacked-to-main, 400-line review budget. No commits, PRs, archive, or live providers in this reconciliation.

## Completed tasks and persisted checkboxes

All 18 implementation tasks (1.1–1.5, 2.1–2.7, 3.1–3.3, 4.1–4.2, 5.1) are marked `- [x]` in `tasks.md` and re-read after marking. Earlier work is in `540cb6e`, `15362ec`, `dda2800`, `130ae70`, `a25b7e6`, `f8e7c24`, `87927f0`; `d0f475b` is planning. Existing implementations were not rewritten. Auth record was read back before completing 5.1.

## TDD Cycle Evidence

| Scope | RED | GREEN | TRIANGULATE / REFACTOR |
|---|---|---|---|
| WU1–WU4 already committed | Historical RED/GREEN assertions in named tests and commits; no new RED run claimed in this session. | Focused 141 passed; backend full 3621 passed; frontend 819 passed and build succeeded. | No existing production code refactored. |
| Non-string persisted plan fails closed | RED: `TestResolution::test_non_string_persisted_plan_fails_closed_to_starter` asserted `starter` and failed against the prior implementation (`assert 'pilot' == 'starter'`). | GREEN: `resolve_entitlements` now treats any non-string, empty, or missing plan value as invalid and falls back to `FALLBACK_PLAN` (`starter`), logging `entitlements_invalid_plan_value`; the resolver test passed. | Triangulated with `test_missing_plan_attribute_fails_closed_to_starter` and `test_empty_string_plan_fails_closed_to_starter` (both updated to expect `starter`); `test_unknown_plan_falls_back_to_starter` already covered the unknown-string case and continues to pass. |
| Scheduler plan-block tick | Coverage gap identified: no tick-level plan test. New test passed on first run; no failing RED observed. | `test_scheduler_cycle_plan_block_fails_row_and_logs_code` passed using migrated SQLite and mocked provider seam. | Verified row is persisted as failed, failure code is logged, no session or provider call; no production change needed. |
| Superadmin plan cap | Existing `tests/unit/entitlements/test_feature_gates.py` covers superadmin agent creation denied at cap; no duplicate test added. | Included in focused/full runs. | Design/spec explicitly prohibit bypass. |

The two audit additions are characterization tests of already-working code, not newly implemented behavior; claiming a failing RED for them would be inaccurate.

## Commands and results

- RED: `cd backend && uv run pytest tests/unit/entitlements/test_catalog_and_resolution.py::TestResolution::test_non_string_persisted_plan_fails_closed_to_starter tests/unit/entitlements/test_catalog_and_resolution.py::TestResolution::test_missing_plan_attribute_fails_closed_to_starter tests/unit/entitlements/test_catalog_and_resolution.py::TestResolution::test_empty_string_plan_fails_closed_to_starter -q` → **3 failed** (`assert 'pilot' == 'starter'`) against the prior implementation.
- GREEN: same command after the `resolve_entitlements` fail-closed fix → **3 passed**.
- `cd backend && uv run pytest tests/integration/scheduler/test_plan_gate.py::test_scheduler_cycle_plan_block_fails_row_and_logs_code -q` → **1 passed**.
- `cd backend && uv run pytest tests/unit/core/test_access.py tests/unit/test_tenant_isolation_routes.py tests/unit/entitlements tests/integration/scheduler/test_plan_gate.py -q` → **141 passed**.
- `cd backend && uv run pytest tests/ -q` → **3621 passed, 4 warnings** (1 Starlette deprecation on `httpx`/`starlette.testclient`; 3 `AsyncMockMixin._execute_mock_call` coroutine-never-awaited warnings in `tests/unit/outbound/test_c6_outcome_reason.py`, pre-existing). Independent runtime verification observed this count: 3621 backend passed / 819 frontend passed.
- `cd frontend && npm test -- --run && npm run build` → **819 passed across 64 files; build succeeded**. jsdom canvas/MSW warnings and Vite chunk-size warning remain; no `act()` warnings observed.

## Files changed in this reconciliation

`openspec/changes/multi-tenant-readiness/{tasks.md,apply-progress.md,auth-decision.md,design.md,specs/plan-entitlements/spec.md}`;
`backend/tests/unit/entitlements/test_catalog_and_resolution.py`;
`backend/tests/integration/scheduler/test_plan_gate.py`;
`docs/running-locally.md`;
`docs/api-reference.md`.

### Remediation of independent verifier findings (this session)

`backend/app/entitlements/service.py` (fail-closed plan resolution, drop unused `DEFAULT_PLAN` import); `backend/tests/unit/entitlements/test_catalog_and_resolution.py` (updated non-string/missing test expectations, added empty-string case); `backend/tests/unit/entitlements/test_usage_and_dial_gate.py` (removed unused `pytest` import); candidate-added lines passed Ruff check with no new violations versus `main` (Ruff format is not a repository gate and no version/config is pinned); `openspec/changes/multi-tenant-readiness/{tasks.md,design.md,apply-progress.md}` (drift fixes: Guard 1b naming, current test commands, Importar/CSV nav accuracy, act-warning claim, this evidence).

### Final verifier blocker closure (this session)

- `backend/app/outbound/router.py`: removed the unused `require_api_key` import (the route depends on `require_client_access`; `require_api_key` was only referenced in a docstring comment).
- `backend/tests/unit/outbound/test_final_rereview_blockers.py`: reformatted the four `app.dependency_overrides[require_api_key] = lambda: CallerIdentity(api_key_hash="test")` lines added by prior work to the Ruff-format wrapping (`lambda: CallerIdentity(\n    api_key_hash="test"\n)`); no other lines in this legacy file were reformatted.
- Pre-existing uncommitted work already in the tree (not newly added this session, verified in place): `client.plan = "pilot"` fixture fields across the outbound unit tests so mocked valid clients resolve entitlements without falling back to `starter`; the fail-closed `resolve_entitlements` production change in `backend/app/entitlements/service.py`; and the `feature-gate.test.tsx` fix wrapping the post-render timer assertion in `act()`.
- `openspec/changes/multi-tenant-readiness/design.md`: corrected the product boundary claim. `crm_integration` gates `crm_router` (CRM import) only; `crm_config_router` (CRM connection/configuration) remains a superadmin control-plane operation, not feature-gated, by design — so an integration can be prepared before a plan upgrade. Verified in code: only `crm_router` carries `Depends(require_feature("crm_integration"))`; `crm_config_router` carries no feature dependency. Background post-call sync enforcement was not implemented in this change; it is now named explicitly as follow-up/non-goal rather than left implied as gated. The no-superadmin-bypass rule for feature-consuming runtime operations and usage limits is unchanged.
- `openspec/changes/multi-tenant-readiness/specs/plan-entitlements/spec.md`: reviewed for the same CRM claim; it contains no CRM-specific wording, so no change was needed there.

## Deviations, risks, and PR boundary

This session's remediation slice changed one production file, `backend/app/entitlements/service.py`, to fail closed on non-valid stored plan values (see RED/GREEN evidence above); no other production code changed. The scheduler **persists terminal `failed` status and logs `failure_code`**; it does not store failure code on the scheduled-call row. A non-string, missing, or empty plan value now resolves to `starter`, consistent with an unknown nonempty string; the spec does not distinguish missing from corrupt values, so all non-valid stored plan values fail closed the same way. The global API key remains browser-visible until follow-up `multi-tenant-auth`; `QORA_ENV` guards do not solve that risk. Auth provider prices were recorded from user-supplied official-source facts dated 2026-09-27, not independently fetched here.

Prior delivery units: WU1+WU4 backend → WU2 → WU3+WU4 frontend. This documentation/test reconciliation is the final independent WU5 review slice (no PR opened). Remaining tasks: none. Backend and frontend full suites ran locally; optional independent SDD verification remains for `sdd-verify`.
