# Tasks: Dynamic Lead Fields

## Review Workload Forecast

| Field | Value |
|---|---|
| Review budget | 800 changed lines |
| Total estimated changed lines | 1,250-1,650 |
| Chained PRs recommended | Yes |
| 800-line budget risk | High |
| Suggested split | WU-1 → WU-2/3 → WU-4/5 → WU-6/7 |
| Delivery strategy | auto-forecast / auto decide by size |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High
800-line budget risk: High

## Dependency Graph

`1.1 → 1.2 → 1.3 → 2.1 → 2.2 → 3.1 → 4.1 → 4.2 → 5.1 → 5.2 → 6.1 → 6.2 → 7.1 → 7.2`

## WU-1: Schema + Model + CRUD Service

### [x] 1.1 LeadCustomField model and migration tests
- Description: RED tests for model constraints, type validation, startup table creation, one-time copy marker.
- Files: `backend/tests/unit/leads/test_lead_custom_fields_service.py`, `backend/tests/unit/test_schema_compat_custom_fields.py`.
- Dependencies: none.
- Test requirements: CF-1..CF-11 migration/idempotency scenarios.
- Estimated lines changed: 180-240.
- Status: DONE — 30 tests written and passing.

### [x] 1.2 Implement model, service, and startup migration
- Description: Add `LeadCustomField`, CRUD/upsert/batch service, write-time coercion, idempotent copy from legacy columns.
- Files: `backend/app/leads/models.py`, `backend/app/leads/lead_custom_fields_service.py`, `backend/app/main.py`.
- Dependencies: 1.1.
- Test requirements: make 1.1 pass; run `cd backend && python3 -m pytest tests/ -q`.
- Estimated lines changed: 260-340.
- Status: DONE — all 30 task 1.1 tests passing; 2062 total suite tests passing.

### [x] 1.3 Update CRM config schema for custom fields
- Description: Add `CustomFieldDef`, `custom_fields`, `quote_ready_fields`, `api_key` resolver; update Quintana config.
- Files: `backend/app/integrations/crm_config.py`, `backend/clients/quintana-seguros/crm.yaml`, config tests.
- Dependencies: 1.2.
- Test requirements: QR-3, QR-4, duplicate field rejection.
- Estimated lines changed: 120-170.
- Status: DONE — 14 new tests passing; all 15 existing CRM config tests passing.

## WU-2: CRM Import/Export Adaptation

### [x] 2.1 Test CRM export/import custom field routing
- Description: RED tests for `_lead_to_dict` merge and import base-vs-custom classification.
- Files: `backend/tests/unit/integrations/test_crm_custom_fields_routing.py` (new).
- Dependencies: 1.3.
- Test requirements: CRM export/import scenarios, no custom fields safe path.
- Estimated lines changed: 140-190.
- Status: DONE — 19 new tests written and passing.

### [x] 2.2 Implement CRM custom field read/write paths
- Description: Export loads custom fields; import upserts non-base fields through service with configured types.
- Files: `backend/app/integrations/crm_sync_service.py`, `backend/app/integrations/crm_import_service.py`.
- Dependencies: 2.1.
- Test requirements: make 2.1 pass.
- Estimated lines changed: 150-220.
- Status: DONE — all 2081 tests passing (19 new).

## WU-3: Prompt Rendering Adaptation

### [x] 3.1 Test and implement prompt variable merge
- Description: RED/GREEN `_build_variables` so templates resolve `{{car_make}}` from custom fields; missing fields render empty.
- Files: `backend/tests/prompts/test_loader.py`, `backend/app/prompts/loader.py`.
- Dependencies: 1.3.
- Test requirements: prompt-rendering scenarios; base Lead keys win collisions.
- Estimated lines changed: 100-150.

## WU-4: Post-Call Pipeline Adaptation

### [x] 4.1 Test and implement quote-ready config
- Description: RED/GREEN pure `is_quote_ready(custom_fields, quote_ready_fields)` and summarizer status transition using CRM config.
- Files: `backend/tests/unit/test_quote_ready.py` (new), `backend/app/summarizer.py`.
- Dependencies: 1.3.
- Test requirements: QR-1, QR-2, QR-5, missing `crm.yaml` never quoted.
- Estimated lines changed: 120-180.
- Status: DONE — 12 new tests (test_quote_ready.py) + updated test_quote_ready_status.py; _merge_facts_into_lead loads CRM config + custom fields via CRMConfigLoader.

### [x] 4.2 Test and implement custom-field data corrections
- Description: Merge base Lead + custom fields into `current_lead_data`; route correction writes to custom fields.
- Files: `backend/tests/unit/analysis/test_data_corrections_custom_fields.py` (new), `backend/app/analysis/universal/data_corrections.py`, `backend/app/summarizer.py`.
- Dependencies: 4.1.
- Test requirements: correction applies to `lead_custom_fields`; no `lead.car_year` writes.
- Estimated lines changed: 170-240.
- Status: DONE — 14 new tests; CorrectableField gains storage attr; dual-write via _apply_custom_field_corrections; snapshot merges custom fields on top of base Lead fields.

## WU-5: Tools Adaptation

### [x] 5.1 Test dynamic capture_data schema and writes
- Description: RED tests for schema from `custom_fields` and `capture_data` writing business data only to `lead_custom_fields`.
- Files: `backend/tests/unit/tools/test_capture_data.py` (8 new WU-5 tests appended).
- Dependencies: 1.3.
- Test requirements: no `captured:` LeadProfileFact write for business data; post-call facts remain separate pipeline.
- Estimated lines changed: 140-200.
- Status: DONE — 8 RED tests written and confirmed failing before implementation.

### [x] 5.2 Implement dynamic tools and remove register_interest
- Description: Generate `capture_data` schema from config, upsert custom fields, strip/delete legacy `register_interest`.
- Files: `backend/app/tools/registry.py`, `backend/app/tools/capture_data.py`, `backend/app/tenants/service.py`, `backend/app/tools/register_interest.py` (DELETED).
- Dependencies: 5.1.
- Test requirements: AC-5, AC-6; no active imports of `register_interest`.
- Estimated lines changed: 180-260.
- Status: DONE — 2130 tests passing (8 new + 15 updated tests).

## WU-6: API + Frontend

### [x] 6.1 Test and implement Lead API custom_fields contract
- Description: RED/GREEN `custom_fields` in create/detail/list responses; keep top-level legacy fields during transition.
- Files: `backend/tests/unit/leads/test_router_custom_fields.py` (new, 10 tests), `backend/app/leads/router.py`.
- Dependencies: 1.2.
- Test requirements: API scenarios for GET and POST custom fields.
- Estimated lines changed: 160-230.
- Status: DONE — 10 new RED tests written and passing GREEN; 2130 total suite tests passing.

### [x] 6.2 Update frontend types and fixtures
- Description: Add `custom_fields` to Lead type; keep legacy fields during transition; update mocks and test fixtures.
- Files: `frontend/src/api/types.ts`, `frontend/tests/mocks/handlers.ts`, `frontend/src/api/leads.test.ts`, `frontend/src/api/hooks.test.tsx`.
- Dependencies: 6.1.
- Test requirements: frontend tests all pass.
- Estimated lines changed: 120-180.
- Status: DONE — 543 frontend tests passing; custom_fields optional field added to Lead type and CreateLeadPayload.

## WU-7: Cleanup

### [x] 7.1 Remove seed and legacy hardcoded column reads
- Description: Seed via custom fields; remove old create params and legacy `_apply_data_corrections`.
- Files: `backend/app/leads/service.py`, `backend/app/summarizer.py`, tests using seed data.
- Dependencies: 2.2, 3.1, 4.2, 5.2, 6.2.
- Test requirements: AC-1, AC-2, no legacy field reads in active paths.
- Estimated lines changed: 120-180.
- Status: DONE — 12 new WU-7 tests written and passing; 2139 backend tests passing.

### [x] 7.2 Final verification and regression sweep
- Description: REFACTOR pass, remove stale imports, run full backend tests.
- Files: all touched files above.
- Dependencies: 7.1.
- Test requirements: `cd backend && python3 -m pytest tests/ -q`; grep confirms no active `lead.car_*`, `lead.age`, `lead.zona`, `register_interest`.
- Estimated lines changed: 40-80.
- Status: DONE — 2139 backend tests + 543 frontend tests passing. AC-1 verified.
