# Proposal: Session ID Lifecycle Fix + CRM Match Field

## Intent

Two live-production bugs are causing silent data loss in every demo call:

1. **Orphaned sessions**: ElevenLabs doesn't always send `conversation_id` in the custom-LLM webhook body. Backend falls back to a `demo-*` ID; when `/end` arrives with the real EL conversation_id, no DB record matches → session stays `initiated`, analysis never runs, CRM sync never fires.

2. **Fragile CRM match**: Airtable upserts match on email, which is optional and can change. The numeric Meta/Facebook `lead_id` already lives in Airtable but has nowhere to land in Qora's Lead model → idempotency broken on re-sync.

Both are small, independent fixes that are easiest to ship together.

---

## Scope

### In Scope
- Add `client_id` to `custom_llm_extra_body` in the frontend demo (improves reconciliation hints)
- Backfill `elevenlabs_conversation_id` on CallSession from session_store during the custom-LLM webhook (when available)
- Add `external_lead_id: Integer, nullable` column to Lead model + auto-migration
- Populate `external_lead_id` during CRM import via field_mappings
- Expose `external_lead_id` in `_lead_to_dict()` for push sync
- Switch `match_field` in `crm.yaml` from `"Correo electrónico"` → `"lead_id"`

### Out of Scope
- Bulk backfill script for existing leads (first import run after deploy handles this)
- Replacing the 600s reconciliation window mechanism (it still runs as the last safety net)
- ElevenLabs post-call webhook changes
- Other clients' `crm.yaml` configs

---

## Capabilities

### New Capabilities
- None

### Modified Capabilities
- `call-session-lifecycle`: `elevenlabs_conversation_id` is now backfilled earlier (webhook time, not only reconciliation time)
- `crm-sync`: Adds `external_lead_id` as the primary match key for Airtable upsert

---

## Approach

**Problem 1 — Conversation ID**: The reconciliation path in `calls/service.py` already backfills the EL conversation_id when `/end` reconciles a session — but only after a lookup failure. The fix adds an earlier backfill point: when the custom-LLM webhook starts a session, check the session_store for an initiation-cached entry with a real EL conversation_id and copy it onto the new `CallSession`. Also add `client_id` to the frontend `custom_llm_extra_body` (it's in the URL path already, but explicit hints improve reconciliation reliability).

**Problem 2 — CRM Match**: Purely additive. New nullable `Integer` column on Lead, new field_mapping entry in `crm.yaml`, small changes to import create/update helpers and `_lead_to_dict()`. Fallback: if `external_lead_id` is NULL, CRM sync keeps working via `external_crm_id` lookup (Airtable record ID). The match_field switch takes effect immediately after deploy + first re-import.

---

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/static/index.html` | Modified | Add `client_id` to `custom_llm_extra_body` |
| `backend/app/voice/webhook.py` | Modified | Backfill `elevenlabs_conversation_id` from session_store at session creation |
| `backend/app/leads/models.py` | Modified | Add `external_lead_id: Mapped[int \| None]` |
| `backend/app/main.py` | Modified | Auto-migration: `ALTER TABLE leads ADD COLUMN external_lead_id INTEGER` |
| `backend/app/integrations/crm_import_service.py` | Modified | Handle `external_lead_id` in `_update_lead_from_qora_data` + `_create_lead_from_qora_data` |
| `backend/app/integrations/crm_sync_service.py` | Modified | Add `external_lead_id` to `_lead_to_dict()` |
| `backend/clients/quintana-seguros/crm.yaml` | Modified | Add field_mapping entry; change `match_field` to `"lead_id"` |

**Estimated lines of change**: ~90–130 lines total (Problem 1: ~35–50 / Problem 2: ~55–80)

---

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Leads without Meta `lead_id` in Airtable (manual entries) | Medium | Keep `external_crm_id` as secondary identifier; log warning on upsert miss |
| Airtable `lead_id` is formula/auto-number (can't upsert on it) | Low | Verify field type in Airtable UI before switching match_field |
| Session_store race: initiation entry expired before webhook runs | Low | Backfill is best-effort; reconciliation window remains as fallback |
| Migration on production SQLite with live traffic | Low | `ADD COLUMN ... DEFAULT NULL` is instant and non-locking in SQLite |

---

## Rollback Plan

- **Problem 1**: Revert `index.html` (remove `client_id` from body) and revert webhook backfill. No DB schema change → instant rollback.
- **Problem 2**: Revert `crm.yaml` match_field to `"Correo electrónico"`. The `external_lead_id` column stays (nullable, harmless). No data is lost.

---

## Dependencies

- ElevenLabs must be exposing `lead_id` in `custom_llm_extra_body` (confirmed: already in production).
- Airtable `lead_id` must be a standard Number field (needs one-time verification before deploy).

---

## Success Criteria

- [ ] Demo call end-to-end: session closes, analysis runs, CRM sync fires — even when EL sends no `conversation_id` in the webhook body
- [ ] CallSession in DB has non-NULL `elevenlabs_conversation_id` after every completed call
- [ ] CRM import populates `external_lead_id` on Lead records for all Airtable rows with a numeric `lead_id`
- [ ] CRM sync upserts succeed using `lead_id` match field without duplicate records
- [ ] Existing leads without `external_lead_id` still sync correctly (graceful fallback)
- [ ] No regression in unit tests for import, sync, field_mapping, and reconciliation paths
