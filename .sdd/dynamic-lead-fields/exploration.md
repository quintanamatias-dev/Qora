## Exploration: dynamic-lead-fields

### Current State

The `leads` table has 6 Quintana-specific columns hardcoded as direct SQLAlchemy mapped columns: `car_make` (String), `car_model` (String), `car_year` (Integer), `current_insurance` (String), `age` (Integer), `zona` (String). These fields are read, written, rendered, synced, and validated across ~25 files in both backend and frontend. The `lead_profile_facts` table already exists with supersede-pattern key-value storage but is used only for internal agent intelligence (profile:, service_issue:, signal:, captured: namespaces). A new `lead_custom_fields` table will house client-configurable business data (CRM-mapped fields).

### Area 1: Column Touchpoints — Complete Map

#### `car_make`, `car_model`, `car_year` (Vehicle Fields)

| File | Lines | Operation | Risk |
|------|-------|-----------|------|
| `backend/app/leads/models.py` | 88-90 | Column definition (mapped_column) | **HIGH** — must remove columns |
| `backend/app/leads/service.py` | 64-67, 73-84, 310-321 | create_lead() params + Lead() constructor + _SEED_LEADS | **HIGH** — signature change |
| `backend/app/leads/router.py` | 64-67, 149-152, 256-265 | CreateLeadRequest schema + _lead_to_dict + create_new_lead | **HIGH** — API schema change |
| `backend/app/summarizer.py` | 82-90, 269-278, 1082-1118 | is_quote_ready() + current_lead_data snapshot + _apply_data_corrections (legacy) | **HIGH** — quote logic must read from custom_fields |
| `backend/app/tools/register_interest.py` | 26-33, 40-45, 64-94 | TOOL_DEFINITION schema + handler params + lead.car_* writes | **HIGH** — writes directly to Lead columns |
| `backend/app/tools/get_lead_details.py` | 58-61 | Reads lead.car_make/model/year/current_insurance | **MEDIUM** — read-only, change to custom_fields |
| `backend/app/tools/capture_data.py` | N/A (writes to LeadProfileFact) | Uses `captured:` namespace already | **LOW** — works via key-value already |
| `backend/app/integrations/crm_sync_service.py` | 254-275 | _lead_to_dict includes car_make, car_model, car_year, current_insurance | **HIGH** — must read from custom_fields |
| `backend/app/integrations/crm_import_service.py` | 349-354, 430-432 | _update_lead writes lead.car_make etc. + _create_lead sets them | **HIGH** — import must write to custom_fields |
| `backend/app/integrations/field_mapping.py` | N/A | Pure mapper — field names come from crm.yaml source/target | **LOW** — already dynamic |
| `backend/app/analysis/universal/data_corrections.py` | 189-238 | CORRECTABLE_FIELDS registry: car_make, car_model, car_year, current_insurance, age | **HIGH** — must look up custom_fields instead of Lead attrs |
| `backend/app/tenants/service.py` | 170-193 | _QUINTANA_TOOL_CONFIG capture_data schema | **MEDIUM** — must become dynamic from CRM field mapping |
| `backend/app/prompts/loader.py` | 439-448, 488-496 | _build_variables: `car_make`, `car_model`, `car_year`, `current_insurance` | **HIGH** — template rendering must read custom_fields |
| `backend/clients/quintana-seguros/agents/jaumpablo/system-prompt.md` | 11, 38, 42 | `{{car_make}} {{car_model}} {{car_year}}`, `{{current_insurance}}` | **MEDIUM** — template stays, variable resolution changes |
| `backend/app/main.py` | 171-183 | Startup migration for `zona` column | **LOW** — remove after data migration |
| `frontend/src/api/types.ts` | 19-22, 44-47, 179 | Lead interface + CreateLeadPayload + CallAnalysis.current_insurance | **MEDIUM** — remove 4 fields from Lead type |
| `frontend/tests/mocks/handlers.ts` | 47-50, 73-76 | Mock lead data | **LOW** — update mocks |
| `frontend/src/features/calls/call-analysis-panel.tsx` | 442-446 | Renders `analysis.current_insurance` | **LOW** — comes from CallAnalysis, not Lead |

#### `age`, `zona` (Quote-Ready Fields)

| File | Lines | Operation | Risk |
|------|-------|-----------|------|
| `backend/app/leads/models.py` | 113-114 | Column definitions | **HIGH** |
| `backend/app/summarizer.py` | 82-90 | is_quote_ready() checks lead.age and lead.zona | **HIGH** — must query custom_fields |
| `backend/app/summarizer.py` | 273 | current_lead_data snapshot includes `age` | **HIGH** |
| `backend/app/integrations/crm_sync_service.py` | 266-267 | _lead_to_dict includes age, zona | **HIGH** |
| `backend/app/integrations/crm_import_service.py` | 345-348, 428-429 | Import writes lead.zona, lead.age | **HIGH** |
| `backend/app/tenants/service.py` | 182-191 | _QUINTANA_TOOL_CONFIG required fields | **MEDIUM** |
| `backend/app/analysis/universal/data_corrections.py` | 208-209 | CORRECTABLE_FIELDS registry for age | **HIGH** |

### Area 2: Migration Strategy

**Current state**: Qora does NOT use Alembic. Schema migrations happen via idempotent `ALTER TABLE ADD COLUMN IF NOT EXISTS` blocks in `main.py` startup (`_apply_schema_compat`).

**Recommended approach** — 3-phase startup migration:

1. **Phase A — Create new table**: Add `lead_custom_fields` CREATE TABLE in `main.py` `_apply_schema_compat`. Idempotent (IF NOT EXISTS).

2. **Phase B — Copy data**: One-time migration block: for each lead with non-null car_make/car_model/car_year/current_insurance/age/zona, INSERT corresponding rows into `lead_custom_fields`. Use a migration marker (e.g., a pragma or a row in a `_migrations` table) to avoid re-running.

3. **Phase C — Drop columns**: SQLite does NOT support `ALTER TABLE DROP COLUMN` on older versions (< 3.35.0). Python 3.11 bundles SQLite ≥3.39, so `ALTER TABLE DROP COLUMN` is safe. However, safer approach: leave old columns in place but stop reading/writing them. Mark as deprecated. Clean up in a future release.

**Backward compatibility**: During transition, both read paths exist (custom_fields preferred, fallback to Lead column). Once all code is migrated, old columns are dead.

### Area 3: Template Rendering — Full Trace

**Path**: `crm.yaml` → PromptLoader → `_build_variables` → `_render_template` → LLM

1. **system-prompt.md** contains `{{car_make}} {{car_model}} {{car_year}}` and `{{current_insurance}}`
2. **PromptLoader.render_for_agent()** → calls `_render_template()`
3. **`_render_template()`** → calls `_build_variables()`
4. **`_build_variables()`** (lines 437-502) reads `lead.car_make`, `lead.car_model`, `lead.car_year`, `lead.current_insurance` directly from Lead ORM attrs

**Required change**: `_build_variables()` must be changed to:
- Accept custom fields as a parameter (or load them from DB)
- Build a merged dict: base Lead fields + custom fields from `lead_custom_fields`
- The template `{{car_make}}` would resolve from custom_fields rows where `field_key='car_make'`

**Important**: The template files (`system-prompt.md`) do NOT need to change. `{{car_make}}` stays — only the variable resolution source changes.

**Risk**: `_build_variables()` is async already (CAP-2) and has a `db` parameter. Adding a custom_fields query fits naturally. Performance impact: one additional SELECT per prompt render (can be batched with the existing `build_memory_context` call).

### Area 4: CRM Sync — Bidirectional Flow

#### Export: Qora → Airtable (`crm_sync_service.py`)

1. Post-call: summarizer calls `_schedule_crm_sync()`
2. `_run_crm_sync_in_background()` opens own DB session
3. `sync_lead()` fetches Lead via `get_lead()`
4. **`_lead_to_dict(lead)`** (lines 245-275) — builds flat dict with `car_make`, `car_model`, `car_year`, `current_insurance`, `age`, `zona` from Lead attrs
5. `FieldMapper.map()` applies crm.yaml field_mappings to transform dict → CRM payload
6. `adapter.upsert_record()` pushes to Airtable

**Required change**: `_lead_to_dict()` must include custom fields from `lead_custom_fields` table. The FieldMapper is already dynamic (reads from crm.yaml) — no changes needed to FieldMapper itself. The crm.yaml `source` values will match `field_key` in custom_fields.

#### Import: Airtable → Qora (`crm_import_service.py`)

1. `import_leads_from_crm()` fetches Airtable records
2. `mapper.reverse_map()` converts CRM fields → Qora field names
3. `_update_lead_from_qora_data()` (lines 314-377) — directly sets `lead.car_make`, `lead.car_model`, `lead.car_year`, `lead.current_insurance`, `lead.zona`, `lead.age`
4. `_create_lead_from_qora_data()` (lines 404-436) — sets them on new Lead creation

**Required change**: Both `_update_lead_from_qora_data()` and `_create_lead_from_qora_data()` must write to `lead_custom_fields` instead. The logic becomes: for each reverse-mapped field, check if it's a base lead field (name, phone, email, status) → write to Lead column. If it's a custom field → write/upsert to `lead_custom_fields`.

### Area 5: Post-Call Analysis Pipeline

#### `is_quote_ready()` (summarizer.py:70-90)

```python
def is_quote_ready(lead):
    return all([lead.car_make, lead.car_model, lead.car_year, lead.age, lead.zona])
```

This is a **pure function** that checks 5 fields directly on the Lead ORM. ALL 5 fields are being migrated to custom_fields.

**Required change**: This function must be refactored to accept custom fields (either as a dict parameter, or query them). Options:
- **Option A**: Pass a dict of custom fields to `is_quote_ready(lead, custom_fields={})`
- **Option B**: Make it a client-configurable "required fields for quote" list in crm.yaml
- **Recommendation**: Option B — this is the natural extension. Each client defines their own "quote-ready" field list in crm.yaml. `is_quote_ready()` checks that all fields in that list are present in custom_fields.

#### `current_lead_data` snapshot (summarizer.py:269-278)

The data corrections pipeline receives a snapshot of correctable fields:
```python
current_lead_data = {
    "name": lead_for_notes.name, "phone": ..., "email": ...,
    "age": lead_for_notes.age, "car_make": ..., "car_model": ...,
    "car_year": ..., "current_insurance": ...
}
```

**Required change**: Merge base Lead fields + custom_fields into this snapshot. The CORRECTABLE_FIELDS registry in `data_corrections.py` must also be updated: `lead_attr` currently points to Lead ORM attributes. After migration, custom field corrections write to `lead_custom_fields` instead.

#### `_apply_data_corrections()` (legacy, summarizer.py:1082-1118)

This legacy function writes corrections directly to `lead.car_make`, `lead.car_model`, `lead.car_year`. Already being phased out in favor of `_apply_structured_corrections()`.

**Required change**: The structured path (`_apply_structured_corrections`) already uses `CORRECTABLE_FIELDS` registry. The registry's `lead_attr` values need to either point to custom_field writes or a new abstraction. The legacy `_apply_data_corrections()` can be removed.

### Area 6: Analytics Queries

`backend/app/analytics/service.py` — **No direct references to car_make, car_model, car_year, current_insurance, age, or zona.** Analytics queries operate on:
- `CallAnalysis` (classification, service_issues)
- `LeadProfileFact` (fact_key namespaces: signal:, service_issue:)
- `CallSession` (agent_id, duration)

**No changes needed** in analytics. Custom fields are not queried in analytics today.

### Area 7: Frontend Impact

| File | Change Needed |
|------|---------------|
| `frontend/src/api/types.ts` | Remove `car_make`, `car_model`, `car_year`, `current_insurance` from `Lead` and `CreateLeadPayload` interfaces. Add optional `custom_fields?: Record<string, string>` |
| `frontend/tests/mocks/handlers.ts` | Update mock leads to not include these fields; optionally add custom_fields |
| `frontend/src/features/leads/page.test.tsx` | Remove car_* fields from test fixtures (4 test blocks, ~16 lines) |
| `frontend/src/features/leads/next-action.test.ts` | Remove car_* from mock lead |
| `frontend/src/features/leads/detail-page.test.tsx` | Remove car_* from mock lead |
| `frontend/src/api/hooks.test.tsx` | Remove car_* from mock |
| `frontend/src/api/leads.test.ts` | Remove car_* from mock |
| `frontend/src/features/calls/call-analysis-panel.tsx` | `current_insurance` display comes from CallAnalysis (not Lead) — **no change needed** |

**Total frontend impact**: ~8 files, mostly test fixture updates. No UI component renders car_make/car_model/car_year directly from Lead today.

### Area 8: Risks and Edge Cases

#### R1: Performance — Key-Value JOINs vs Direct Columns
- **Risk**: SELECT with JOIN to custom_fields instead of direct column read
- **Mitigation**: For prompt rendering and CRM sync, we load ALL custom fields for one lead in a single query. Indexed on (lead_id, client_id). For a key-value table with ~6-10 fields per lead, this is negligible.
- **Real concern**: Batch operations (list all leads with their custom fields). Solution: batch-load in one query using `lead_id IN (...)`.

#### R2: Type Coercion (field_type enforcement)
- **Risk**: custom_fields stores `field_value` as TEXT. car_year is an Integer.
- **Mitigation**: `field_type` column indicates the expected type. Coercion happens at read time (same as CRM field_mapping already does). The data corrections pipeline already handles `_extract_int()` from text.

#### R3: `_QUINTANA_TOOL_CONFIG` (tenants/service.py)
- **Current**: Hardcoded JSON schema defining capture_data tool fields (car_make, car_model, car_year, current_insurance, age, zona).
- **Required change**: Must become DYNAMIC — generated from client's CRM field mapping configuration. When a client configures field mappings, the capture_data tool schema should be derived from those mappings.
- **Risk**: This is a seed constant. Changing it affects existing agents. Must ensure backward compatibility during transition.

#### R4: `is_quote_ready()` — "quoted" Status Check
- **Current**: Checks 5 hardcoded fields. If all present → status "quoted".
- **Risk**: After migration, these 5 fields are in custom_fields. The quote-ready check must query custom_fields. BUT: what constitutes "quote-ready" should be client-configurable anyway (not all clients sell insurance).
- **Recommendation**: Add a `quote_ready_fields` list to client/CRM config. Default for Quintana: `["car_make", "car_model", "car_year", "age", "zona"]`. Other clients define their own list or have no quote-ready concept.

#### R5: `register_interest` Tool — Direct Column Writes
- **Current**: Writes directly to `lead.car_make`, `lead.car_model`, `lead.car_year`, `lead.current_insurance`.
- **Required**: Must write to `lead_custom_fields` instead.
- **Risk**: This tool is in dual-run alongside `capture_data`. Phase 2 of configurable-agent-tools was supposed to remove legacy tools. This migration is a natural point to complete that Phase 2.

#### R6: Seed Data (`_SEED_LEADS` in leads/service.py)
- **Current**: 5 Quintana test leads hardcoded with car_make, car_model, etc.
- **Required**: Seed must create lead_custom_fields rows instead of setting Lead columns.

#### R7: `crm.yaml` API Key Storage
- **Current**: `api_key_env` field stores the raw API key directly (for dev/test).
- **Risk**: Field name says "env" but contains the actual key. The `resolve_api_key()` method calls `os.environ.get(self.api_key_env)` — this won't find the key in env vars since it's the key itself.
- **Note**: Per architecture decision, this is intentional for dev/test. Must be fixed for production (secret manager).

### Approaches

1. **Incremental Migration (Recommended)** — Add lead_custom_fields table, dual-write during transition, migrate reads one-by-one, keep old columns as deprecated until all code is migrated.
   - Pros: Low blast radius, easy rollback, testable incrementally
   - Cons: Temporary code duplication, slightly longer timeline
   - Effort: **Medium**

2. **Big-Bang Migration** — Add table, migrate all reads/writes at once, drop old columns.
   - Pros: Clean, no dual-write period
   - Cons: High risk, touches ~25 files at once, hard to debug, no rollback
   - Effort: **High**

### Recommendation

**Incremental Migration** (Approach 1), split into work units:

1. **WU-1: Schema + Model** — Create `lead_custom_fields` table, model, and CRUD service functions
2. **WU-2: CRM Import/Export** — Migrate crm_sync and crm_import to read/write custom_fields
3. **WU-3: Prompt Rendering** — Migrate _build_variables to include custom_fields
4. **WU-4: Post-Call Pipeline** — Migrate is_quote_ready, current_lead_data snapshot, data_corrections
5. **WU-5: Tools** — Migrate register_interest, get_lead_details, capture_data
6. **WU-6: API + Frontend** — Update Lead API response, frontend types, tests
7. **WU-7: Cleanup** — Remove deprecated column reads, update seeds, remove legacy _apply_data_corrections

### Open Questions

1. **Should `field_type` enforcement happen at write time or read time?** (Currently: CRM field_mapping does coercion at map time. Recommendation: write time — validate and coerce when writing to custom_fields, store the canonical value.)

2. **How should `is_quote_ready()` work for non-insurance clients?** (Recommendation: make it a client-configurable `quote_ready_fields` list in crm.yaml. Absent = no quote-ready concept = never transition to "quoted".)

3. **Should `register_interest` be removed entirely?** (It's legacy from before `capture_data`. This migration is a natural completion of configurable-agent-tools Phase 2.)

4. **Data migration for existing SQLite DB**: Should we run the migration automatically on startup, or provide a CLI command? (Recommendation: startup migration like all existing migrations, with a one-time marker.)

### Ready for Proposal
Yes — the codebase investigation is complete. All touchpoints mapped, risks identified, migration strategy clear. Ready to proceed to SDD Proposal with the incremental migration approach.
