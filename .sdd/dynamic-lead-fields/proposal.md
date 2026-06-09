# Proposal: Dynamic Lead Fields

## Intent

Replace 6 hardcoded Quintana-specific columns on the `leads` table (`car_make`, `car_model`, `car_year`, `current_insurance`, `age`, `zona`) with a new `lead_custom_fields` key-value table that is client-configurable. This unblocks Qora from onboarding non-insurance clients, removes the biggest multi-tenancy blocker in the data layer, and makes the voice agent tool schema, quote-ready logic, and CRM field mappings all driven by client configuration rather than hardcoded constants.

## Scope

### In Scope
- New `lead_custom_fields` table (key-value, per-client, type-enforced at write time)
- 3-tier lead model: `leads` (universal base) + `lead_custom_fields` (client business data) + `lead_profile_facts` (Qora intelligence, unchanged)
- Startup migration: create table + copy existing column data + migration marker (idempotent)
- `is_quote_ready()` becomes client-configurable via `quote_ready_fields` list in `crm.yaml`
- `_QUINTANA_TOOL_CONFIG` / `capture_data` schema generated dynamically from client field config
- `register_interest` tool removed entirely (legacy, replaced by `capture_data`)
- CRM import/export (bidirectional) reads/writes `lead_custom_fields`
- Prompt rendering (`_build_variables`) resolves custom fields by `field_key`
- Post-call pipeline: `current_lead_data` snapshot + `CORRECTABLE_FIELDS` registry updated
- Lead API response + frontend TypeScript types updated
- All test fixtures updated
- Old columns deprecated in place (SQLite DROP COLUMN deferred to future cleanup)

### Out of Scope
- Secret manager integration for `api_key` (production hardening, separate change)
- Analytics queries on custom fields (no current need)
- Admin UI for field mapping (separate product feature)
- Alembic or formal migration tooling
- Multi-CRM simultaneous active integrations

## Capabilities

### New Capabilities
- `lead-custom-fields`: CRUD service for `lead_custom_fields` table — write (with type coercion), read (single lead, batch), upsert, and query by `(lead_id, client_id, field_key)`
- `quote-ready-config`: Client-configurable `quote_ready_fields` list in `crm.yaml`; `is_quote_ready()` reads from this list + custom fields

### Modified Capabilities
- `crm-sync`: `_lead_to_dict()` includes custom fields; import writes to `lead_custom_fields`
- `prompt-rendering`: `_build_variables()` merges base Lead fields + custom fields for template resolution
- `capture-data-tool`: Tool schema generated dynamically from client field config; `register_interest` removed

## Approach

Incremental migration in 7 work units (WU). Each WU is independently deployable with no breaking changes until WU-7 cleanup:

| WU | Scope | Risk |
|----|-------|------|
| WU-1 | Schema + model + CRUD service + startup migration | Low |
| WU-2 | CRM import/export (bidirectional) | High |
| WU-3 | Prompt rendering (`_build_variables`) | Medium |
| WU-4 | Post-call pipeline: `is_quote_ready`, snapshot, `CORRECTABLE_FIELDS` | High |
| WU-5 | Tools: `register_interest` removal, `get_lead_details`, `_QUINTANA_TOOL_CONFIG` dynamic | Medium |
| WU-6 | API response + frontend types + test fixtures | Medium |
| WU-7 | Cleanup: remove deprecated column reads, update seeds, remove legacy `_apply_data_corrections` | Low |

Old columns remain in the DB after WU-7 (dead but harmless). Explicit DROP in a future release once stable.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/leads/models.py` | Modified | Remove 6 column defs; add `LeadCustomField` model |
| `backend/app/leads/service.py` | Modified | `create_lead()` signature; seed data; custom_fields CRUD |
| `backend/app/leads/router.py` | Modified | `CreateLeadRequest` schema; `_lead_to_dict` response |
| `backend/app/summarizer.py` | Modified | `is_quote_ready()`, `current_lead_data` snapshot, legacy cleanup |
| `backend/app/integrations/crm_sync_service.py` | Modified | `_lead_to_dict()` reads custom_fields |
| `backend/app/integrations/crm_import_service.py` | Modified | `_update_lead` / `_create_lead` write to custom_fields |
| `backend/app/analysis/universal/data_corrections.py` | Modified | `CORRECTABLE_FIELDS` writes to custom_fields |
| `backend/app/tenants/service.py` | Modified | `_QUINTANA_TOOL_CONFIG` → dynamic from field config |
| `backend/app/prompts/loader.py` | Modified | `_build_variables()` merges custom fields |
| `backend/app/tools/register_interest.py` | Removed | Legacy tool deleted |
| `backend/app/tools/get_lead_details.py` | Modified | Reads from custom_fields |
| `backend/app/main.py` | Modified | Startup migration: create table + copy data + remove old `zona` migration |
| `frontend/src/api/types.ts` | Modified | Remove 4 fields; add `custom_fields?: Record<string, string>` |
| `frontend/tests/mocks/` + `*.test.tsx/ts` | Modified | ~8 files, fixture updates only |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| R1: JOIN performance on batch lead lists | Low | Batch-load custom fields with `lead_id IN (...)` |
| R2: Type coercion — `car_year` stored as TEXT | Low | Enforce at write time; `field_type` column guides coercion |
| R3: `_QUINTANA_TOOL_CONFIG` backward compat during transition | Medium | Keep static fallback until WU-5 is verified in prod |
| R4: `is_quote_ready()` breaks if `quote_ready_fields` missing from config | Medium | Default to empty list → never quoted (safe degradation) |
| R5: `register_interest` removal breaks agent calls in prod | Low | Tool already replaced by `capture_data`; verify no active usage before WU-7 |
| R6: Seed data creates orphaned custom_fields on re-seed | Low | Seed uses upsert semantics |
| R7: `api_key_env` field name misleads `resolve_api_key()` | Low | Rename field in crm.yaml; fix resolver; document intentional dev/test pattern |

## Rollback Plan

- WU-1 through WU-6: Old columns remain populated. Revert code to read from Lead columns. No data loss.
- WU-7 (cleanup): Do NOT run unless all WUs are stable in production. Once old column reads are removed, rollback requires re-adding read paths (no schema rollback needed — columns stay in DB).
- Migration marker prevents re-running data copy on rollback/re-deploy.

## Dependencies

- Python 3.11+ (SQLite ≥3.39 for DROP COLUMN support when needed)
- `crm.yaml` schema extension: `quote_ready_fields`, `field_definitions` list with `field_key`, `field_type`, `label`

## Success Criteria

- [ ] All 6 fields removed from `leads` columns and accessible via `lead_custom_fields`
- [ ] Existing Quintana leads data preserved after startup migration
- [ ] `is_quote_ready()` driven by `crm.yaml` config, not hardcoded field names
- [ ] `capture_data` tool schema generated from field config (no `_QUINTANA_TOOL_CONFIG` constant)
- [ ] `register_interest` tool absent from codebase
- [ ] CRM sync (import + export) fully operational with custom fields
- [ ] Prompt templates (`{{car_make}}` etc.) resolve correctly from custom_fields
- [ ] All frontend types and test fixtures updated; CI green
- [ ] A second client can be configured with zero custom fields and Qora handles it gracefully
