# Verification Report: dynamic-lead-fields

Change: `dynamic-lead-fields`  
Mode: Hybrid persistence (`.sdd` + Engram)  
Strict TDD: ACTIVE  
Date: 2026-06-08  
Verdict: **FAIL**

## Runtime Evidence

| Command | Result | Evidence |
|---|---:|---|
| `cd backend && python3 -m pytest tests/ -q` | PASS | `2139 passed, 3 warnings in 49.37s` |
| `cd frontend && npx vitest run` | PASS | `44 passed`, `543 passed`, duration `5.44s` |

## Completeness Table

| Area | Result | Notes |
|---|---|---|
| Tasks | PASS | All 14 tasks in `tasks.md` are checked `[x]`. |
| Backend tests | PASS | Full backend suite passed. |
| Frontend tests | PASS | Full frontend suite passed. |
| Spec compliance | FAIL | Several MUST requirements are contradicted by production code. |
| Design coherence | FAIL | WU-7 cleanup claim conflicts with active legacy reads. |
| Archive readiness | FAIL | Critical findings block archive/merge. |

## Spec Compliance Matrix

| Requirement / Scenario | Status | Runtime test evidence | Source inspection evidence |
|---|---|---|---|
| CF-1 unique `(lead_id, client_id, field_key)` | CRITICAL | No exact composite unique-constraint test found. | `LeadCustomField` has unique `Index("ix_lcf_lead_key", "lead_id", "field_key", unique=True)` only; `client_id` is missing from the DB uniqueness constraint. |
| CF-2 valid `field_type` enum | PASS | `test_valid_field_types_constant`, CRM config custom-field type tests. | `VALID_FIELD_TYPES = {"string", "integer", "boolean", "date", "phone"}`. |
| CF-3/CF-4 write-time coercion and typed error | PASS | `test_coerce_value_*`, `test_upsert_coercion_failure_rejects_write`. | `coerce_value()` raises `FieldTypeError` before write. |
| CF-5/CF-6 upsert + TEXT storage | PASS | `test_upsert_creates_new_field`, `test_upsert_updates_existing_field`. | `upsert()` coerces to string and inserts/updates. |
| CF-7/CF-8 batch reads | PASS | `test_get_all_returns_all_fields_for_lead`, `test_batch_get_returns_fields_for_multiple_leads`. | `get_all()` and `batch_get()` exist; `batch_get()` uses `IN`. |
| CF-9 client isolation | WARNING | `test_get_all_isolates_by_client_id` covers reads only. | `get_all()`/`batch_get()` scope by `client_id`; `get_one()` and `upsert()` lookup by `(lead_id, field_key)` without `client_id`. |
| CF-10/CF-11 startup migration | PASS | `test_schema_compat_custom_fields.py` has 8 migration/idempotency tests. | Migration tests passed in full suite. |
| QR-1..QR-5 quote-ready config | PASS | `test_quote_ready.py` (12), `test_quote_ready_status.py` dynamic status tests. | `is_quote_ready(custom_fields, quote_ready_fields)` returns false for empty/missing config. |
| CRM export/import custom fields | PASS | `test_crm_custom_fields_routing.py` (19). | `_lead_to_dict` and import routing tests passed. |
| Prompt rendering custom fields | FAIL | `test_loader.py` custom-field tests pass, but do not catch WU-7 fallback reads. | `backend/app/prompts/loader.py:475-480` still reads `lead.car_make`, `lead.car_model`, `lead.car_year`, `lead.current_insurance` as fallbacks. |
| Dynamic `capture_data` schema | PASS | `test_capture_data.py` schema tests passed. | `_QUINTANA_TOOL_CONFIG` constant appears removed; only a comment remains. |
| `capture_data` writes custom fields | PASS | `test_capture_data_writes_to_lead_custom_fields`, dual-write test. | Tool tests passed. |
| `register_interest` absent | CRITICAL | `test_register_interest_module_does_not_exist` passes for module deletion only. | No imports found, but production prompt/default config strings still mention `register_interest`. |
| Data corrections custom fields | PASS WITH WARNING | `test_data_corrections_custom_fields.py` tests passed. | Some tests intentionally assert dual-write to legacy ORM, which conflicts with final AC-1 if still active. |
| Lead API excludes removed columns | CRITICAL | Existing tests assert legacy fields still exist: `test_get_lead_still_has_legacy_car_fields`, `test_list_leads_still_has_legacy_car_fields`. | `backend/app/leads/router.py:155-159` returns top-level `car_make`, `car_model`, `car_year`, `current_insurance`. |
| Frontend Lead type excludes legacy fields | PASS | Frontend suite passed. | `frontend/src/api/types.ts` should be reviewed with API contract after backend fix. |
| AC-1 no active legacy reads | CRITICAL | Grep found active production reads. | 20 matches in `backend/app/` for `lead.car_make`, `lead.car_model`, `lead.car_year`, `lead.current_insurance`, etc. |
| AC-6 no `register_interest` in codebase/tool registry | CRITICAL | No imports found. | 18 production-code mentions remain, including prompt instructions and tenant model defaults. |
| AC-12 backend tests pass | PASS | `2139 passed`. | Runtime verified. |

## Required Grep Checks

| Check | Result | Details |
|---|---|---|
| Legacy reads in `backend/app/` | FAIL | Found active reads in `voice/initiation.py`, `tools/get_lead_details.py`, `leads/router.py`, `prompts/loader.py`, `prompts/insurance_agent.py`. |
| `register_interest` imports in `backend/app/` | PASS | No `import ...register_interest` or `from ...register_interest` matches. |
| `register_interest` remaining mentions | FAIL | Found production prompt/default/tool-deprecation mentions in `tenants/service.py`, `tools/registry.py`, `agents/schemas.py`, `voice/context.py`, `tenants/models.py`, `prompts/insurance_agent.py`, `tools/dispatcher.py`. |
| `_QUINTANA_TOOL_CONFIG` in `backend/app/` | WARNING | Only a stale comment remains: `backend/app/tenants/service.py:165`. No constant definition found. |
| `crm.yaml` hardcoded PAT tokens | PASS | No Airtable PAT token found. The `pat...` regex hit only the word `path` in a comment. `api_key: QUINTANA_AIRTABLE_API_KEY` is an env-var-style reference. |

## Design Coherence

| Design decision | Status | Evidence |
|---|---|---|
| Separate `lead_custom_fields` table | PASS | Model/service exist and tests pass. |
| Type enforcement at write time | PASS | `coerce_value()` + service tests. |
| `api_key` resolver heuristic | PASS | CRM config tests pass; `crm.yaml` uses `api_key`. |
| Quote-ready via `crm.yaml` | PASS | Runtime tests pass. |
| Tool schema from config | PASS | Capture-data schema tests pass. |
| Delete `register_interest` entirely | FAIL | Module/import is gone, but prompt/default references remain. |
| WU-7 cleanup: no hardcoded column reads | FAIL | Active legacy reads remain in multiple production paths. |

## TDD Compliance

| Check | Result | Details |
|---|---|---|
| TDD Evidence reported | ❌ | No `apply-progress` artifact or `TDD Cycle Evidence` table found under `.sdd/dynamic-lead-fields/`. Strict TDD verify rules make this CRITICAL. |
| All tasks have tests | ✅ | Task file lists test requirements; relevant tests exist for all work units. |
| RED confirmed (tests exist) | ✅ | Relevant backend test files exist. |
| GREEN confirmed (tests pass) | ✅ | Full backend and frontend suites passed. |
| Triangulation adequate | ⚠️ | Most areas have multiple scenarios; CF-1 exact composite unique constraint and API legacy-field absence lack coverage. |
| Safety net for modified files | ⚠️ | Cannot verify from missing apply-progress evidence. |

**TDD Compliance**: FAIL due to missing strict TDD evidence artifact, despite passing test execution.

## Test Layer Distribution

| Layer | Tests | Files | Notes |
|---|---:|---:|---|
| Unit | 143 relevant backend tests | 10 | Counted across custom-field, config, CRM routing, prompt, quote-ready, data-correction, capture-data, and router custom-field test files. |
| Integration-ish frontend/API behavior | 14 relevant frontend tests | 2 | `frontend/src/api/leads.test.ts`, `frontend/src/api/hooks.test.tsx`. |
| E2E | 0 | 0 | Not required by artifact. |
| Total runtime suite | 2682 tests | 88 files | Backend 2139 + frontend 543. |

## Changed File Coverage

Coverage analysis skipped — no coverage command was requested/provided for this verification slice.

## Assertion Quality

**Assertion quality**: PASS WITH WARNINGS. No tautology assertions were found in the relevant dynamic-lead-field test files during pattern scan. Some empty-result assertions exist, but they generally pair with non-empty companion scenarios. Two substantive quality gaps remain:

| File | Issue | Severity |
|---|---|---|
| `backend/tests/unit/leads/test_lead_custom_fields_service.py` | CF-1 tests validate columns but not the required composite unique constraint `(lead_id, client_id, field_key)`. | WARNING |
| `backend/tests/unit/leads/test_router_custom_fields.py` | Tests assert legacy top-level API fields remain, directly contradicting final spec requirement that removed columns be absent. | CRITICAL |

## Issues

### CRITICAL

1. **Legacy lead column reads remain in active production code.**  
   Evidence: grep found 20 matches in `backend/app/`, including `voice/initiation.py:160-164`, `tools/get_lead_details.py:79-82`, `leads/router.py:156-159`, `prompts/loader.py:475-480`, and `prompts/insurance_agent.py:185-188`. This violates AC-1 and WU-7.

2. **Lead API still returns removed fields as top-level response properties.**  
   Evidence: `backend/app/leads/router.py:155-159`; tests `test_get_lead_still_has_legacy_car_fields` and `test_list_leads_still_has_legacy_car_fields` lock in the wrong final behavior. This violates the API requirement and AC-11/Lead API contract.

3. **`register_interest` is not fully absent from production code.**  
   Evidence: no imports remain, but production prompts and default `tools_enabled` values still mention it (`prompts/insurance_agent.py`, `tenants/models.py`, `tenants/service.py`, registry/dispatcher comments). This violates AC-6 and can still instruct agents toward a removed tool.

4. **`LeadCustomField` unique constraint does not match the spec.**  
   Evidence: production model uses unique `(lead_id, field_key)` instead of required `(lead_id, client_id, field_key)`. The test suite does not cover the exact composite constraint.

5. **Strict TDD evidence artifact is missing.**  
   Evidence: no `apply-progress` or `TDD Cycle Evidence` table found in `.sdd/dynamic-lead-fields/`. Strict TDD verify rules classify this as CRITICAL.

### WARNING

1. **`_QUINTANA_TOOL_CONFIG` grep still finds a stale comment.**  
   The constant appears removed, but the stale comment creates verification noise.

2. **`crm.yaml` comments still mention `api_key_env`.**  
   The actual key is `api_key`, but comments at the top still describe the old name.

3. **`get_one()` and `upsert()` are not fully client-scoped in lookup predicates.**  
   Reads through `get_all()`/`batch_get()` are scoped, but these helpers use `(lead_id, field_key)` only.

### SUGGESTION

1. Add explicit regression tests that fail on any top-level legacy lead fields in API responses.
2. Add an exact schema test for unique `(lead_id, client_id, field_key)`.
3. Add a grep-based cleanup test for `register_interest` prompt/default references, not just module existence.

## Final Verdict

**FAIL** — Runtime suites pass, but the implementation is not merge/archive-ready. The biggest issue is not test execution; it is contract drift: tests currently preserve some transitional behavior that the final spec explicitly forbids.
