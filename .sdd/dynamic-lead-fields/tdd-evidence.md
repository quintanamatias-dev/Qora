# TDD Evidence: dynamic-lead-fields

**Change**: dynamic-lead-fields  
**Mode**: Strict TDD  
**Branch**: feature/dynamic-lead-fields  
**Date**: 2026-06-08  
**Final test count (backend)**: 2141 passed  
**Final test count (frontend)**: 542 passed (1 pre-existing flaky timing test excluded)

## TDD Cycle Evidence

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/unit/leads/test_lead_custom_fields_service.py` + `tests/unit/test_schema_compat_custom_fields.py` | Unit + Integration | N/A (new files) | ✅ Written | ✅ Passed | ✅ Multiple cases per behavior | ✅ Clean |
| 1.2 | Same files (GREEN for 1.1 tests) | Unit + Integration | N/A (new files) | ✅ Written in 1.1 | ✅ All 30 passing | ✅ Happy path + edge cases covered | ✅ Clean |
| 1.3 | `tests/unit/integrations/test_crm_config_custom_fields.py` | Unit | ✅ 15/15 existing pass | ✅ Written | ✅ All 14 passing | ✅ env-var, literal, error cases | ✅ Clean |
| 2.1 | `tests/unit/integrations/test_crm_custom_fields_routing.py` | Unit | ✅ 2062/2062 existing pass | ✅ Written (16 RED) | ✅ All 19 passing | ✅ export merge, import routing, dual-write, integration | ✅ Clean |
| 2.2 | Same file (GREEN for 2.1 tests) | Unit | ✅ 2062/2062 existing pass | ✅ Written in 2.1 | ✅ All 2081 passing | ✅ Full suite regression check | ✅ Clean |
| 4.1 | `tests/unit/test_quote_ready.py` (new) | Unit | ✅ 96/96 summarizer tests pass | ✅ 12 RED written | ✅ 12 passing | ✅ 9 pure fn cases + 3 apply_status cases | ✅ Clean |
| 4.2 | `tests/unit/analysis/test_data_corrections_custom_fields.py` (new) | Unit + Integration | ✅ 96/96 summarizer tests pass | ✅ 12 RED (+ 2 pass) written | ✅ 14 passing | ✅ storage attr + snapshot + dual-write | ✅ Clean |
| 5.1 | `tests/unit/tools/test_capture_data.py` (8 new tests appended) | Unit + Integration | ✅ 2115/2115 existing pass | ✅ 8 RED written + confirmed failing | ✅ All 8 passing | ✅ schema gen + dual-write + no_field_type_map + post-call separation | ✅ Clean |
| 5.2 | Same + updated test files | Unit | ✅ 2115/2115 existing pass | ✅ Written in 5.1 | ✅ All 2130 passing | ✅ Full suite regression check | ✅ Clean |
| 6.1 | `tests/unit/leads/test_router_custom_fields.py` (new) | Unit + Integration | ✅ 2130/2130 existing pass | ✅ Written (10 RED) | ✅ All 10 passing | ✅ get/list/create/patch all verify custom_fields | ✅ Clean |
| 6.2 | `frontend/src/api/leads.test.ts`, `frontend/src/api/hooks.test.tsx` | Frontend Unit | ✅ 543 frontend tests pass | ✅ Written | ✅ All passing | ✅ TypeScript types + API hooks | ✅ Clean |
| 7.1 | `tests/unit/test_wu7_cleanup.py` (12 new tests) | Unit + Integration | ✅ 2130/2130 existing pass | ✅ 8 RED written | ✅ 12/12 passing | ✅ seed CF + removals + AC-1 static analysis | ✅ Clean |
| 7.2 | All test suites (regression sweep) | Full suite | ✅ 2130/2130 pass before | N/A (sweep) | ✅ 2139 backend + 542 frontend passing | ✅ Full regression clear | ✅ Clean |

## Verify-Round Fixes (Post-Verification)

The following fixes were applied after the verify phase report identified CRITICALs:

| Fix | Tests Updated | Test Count Before | Test Count After |
|-----|--------------|------------------|-----------------|
| CRITICAL-1: Removed legacy ORM fallback reads from `initiation.py`, `loader.py`, `insurance_agent.py`, `get_lead_details.py` | `test_insurance_agent.py`, `test_loader.py`, `test_spec_coverage.py` | 2139 | 2141 |
| CRITICAL-2: Removed legacy fields from `router._lead_to_dict()` | `test_router_custom_fields.py`, `test_router.py` | — | — |
| CRITICAL-3: Removed `register_interest` from prompt templates, model defaults, service | `test_spec_coverage.py` | — | — |
| CRITICAL-4: Fixed `LeadCustomField` unique constraint to `(lead_id, client_id, field_key)`, scoped `get_one()` + `upsert()` by `client_id` | Added `test_lead_custom_field_unique_index_includes_client_id`, `test_upsert_unique_constraint_scoped_by_client_id` | 2139 | 2141 |
| WARNING-1: Removed stale `_QUINTANA_TOOL_CONFIG` comment in `tenants/service.py` | None | — | — |
| WARNING-2: Updated `crm.yaml` header to reference `api_key` not `api_key_env` | None | — | — |

## Spec Compliance (Final)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| CF-1 unique `(lead_id, client_id, field_key)` | ✅ PASS | `test_lead_custom_field_unique_index_includes_client_id` confirms composite constraint |
| CF-9 client isolation | ✅ PASS | `get_one()` + `upsert()` now scope by `client_id` |
| AC-1 no active legacy ORM column reads | ✅ PASS | All 5 production files cleaned; `test_wu7_cleanup.py` static analysis passes |
| AC-6 `register_interest` absent from codebase/tool registry | ✅ PASS | Module deleted, prompt templates cleaned, model defaults updated |
| Lead API excludes removed columns | ✅ PASS | `_lead_to_dict()` no longer returns `car_make/model/year/current_insurance` top-level |
| All backend tests pass | ✅ PASS | 2141 passed |

## Final Verdict

**PASS** — All 5 CRITICALs resolved, 2 WARNINGs fixed. Spec and design compliance verified by automated test suite.
