# Exploration: Session ID & CRM Match Field

## Problem 1: Conversation ID Mismatch — Full Lifecycle Map

### Current State

The conversation ID flows through **5 distinct touchpoints**, and a mismatch at any point orphans the session:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    CONVERSATION ID LIFECYCLE                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  1. INITIATION WEBHOOK (/api/v1/voice/initiation)                      │
│     ├─ Receives: conversation_id from EL (optional)                    │
│     ├─ Creates: session_store entry keyed by (client_id, conv_id)      │
│     ├─ Builds: VoiceSessionContext + caches on ConversationState       │
│     └─ NOTE: session_id="" (no CallSession created yet!)               │
│                                                                        │
│  2. CUSTOM LLM WEBHOOK (/api/v1/voice/{client_id}/custom-llm/...)      │
│     ├─ Receives: conversation_id from elevenlabs_extra_body (OPTIONAL) │
│     ├─ Fallback: find_by_client_lead(client_id, lead_id)               │
│     ├─ Fallback: generate "demo-{uuid4_hex[:12]}"                      │
│     ├─ Creates: CallSession in DB with elevenlabs_conversation_id      │
│     │   (NULL when EL didn't send it — persisted_conversation_id)      │
│     └─ Creates: session_store entry with DB session_id                 │
│                                                                        │
│  3. FRONTEND DEMO PAGE (index.html)                                    │
│     ├─ Captures: conversation_id from metadata event on WS             │
│     │   (msg.conversation_initiation_metadata_event.conversation_id)   │
│     ├─ Stores: currentSessionId = EL conversation_id                   │
│     └─ NOTE: custom_llm_extra_body has { lead_id } but NO client_id    │
│        and NO conversation_id!                                         │
│                                                                        │
│  4. /END ENDPOINT (POST /api/v1/calls/{conversation_id}/end)           │
│     ├─ Receives: path param = EL conversation_id from frontend         │
│     ├─ Lookup: get_session_by_elevenlabs_id(conversation_id)           │
│     ├─ Fallback: treats conversation_id as internal session UUID       │
│     ├─ Fallback: _reconcile_session if client_id + lead_id hints given │
│     └─ Closes: session + triggers summarizer + CRM sync                │
│                                                                        │
│  5. RECONCILIATION SWEEPER (_reconcile_session in service.py)          │
│     ├─ Searches: initiated sessions with NULL el_conversation_id       │
│     ├─ Window: ±600 seconds (RECONCILIATION_WINDOW_SECONDS)            │
│     ├─ Assigns: conversation_id from /end request                      │
│     └─ Closes: session + merges siblings + triggers summarizer         │
│                                                                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### Where It Breaks

**The root cause is in touchpoint 3 → 2 interaction:**

1. **Frontend sends `custom_llm_extra_body: { lead_id }` — but NOT `conversation_id`** (index.html line 543). ElevenLabs forwards this as `elevenlabs_extra_body` on every custom-LLM request.

2. **ElevenLabs sometimes doesn't include `conversation_id` in the forwarded body.** The `ElevenLabsExtraBody` schema accepts it (line 125) but EL doesn't always populate it, especially in signed-URL WebSocket flows.

3. **Webhook generates a `demo-*` fallback ID** (webhook.py line 768). This ID is used as the session_store key and for the DB `CallSession`, but `elevenlabs_conversation_id` is stored as NULL in the DB.

4. **Frontend captures the REAL EL `conversation_id`** from the metadata event (index.html line 593) and sends it to `/end`.

5. **`/end` can't find the session** because:
   - `get_session_by_elevenlabs_id()` looks for a DB record where `elevenlabs_conversation_id = <EL conv id>`, but the DB has NULL there.
   - The EL conversation_id doesn't match any internal session UUID (those are UUIDs, not EL IDs).
   - Reconciliation might save it IF `client_id` and `lead_id` are provided as hints AND the time window is within 600s.

**Result**: Session left orphaned (status=initiated), no analysis runs, no CRM sync fires.

### Proposed Fix: Ensure EL conversation_id Is Always Persisted

**Approach A (Recommended): Frontend includes conversation_id in custom_llm_extra_body**

The frontend already captures the EL conversation_id at connect time. If we include it in `custom_llm_extra_body`, every subsequent custom-LLM request will carry it:

```javascript
// Current (broken):
payload.custom_llm_extra_body = { lead_id: leadId };

// Fixed:
payload.custom_llm_extra_body = { lead_id: leadId, client_id: selectedClientId };
// conversation_id: NOT available at WS open time — only after metadata event
```

**Problem**: `custom_llm_extra_body` is sent at WebSocket open (line 564), BEFORE the metadata event fires (line 589-596). The conversation_id isn't known yet!

**Approach B (Recommended): Backend backfills conversation_id on /end**

When `/end` arrives with the EL conversation_id but can't find a DB match:
1. Use the reconciliation hints (client_id, lead_id) to find the orphan session.
2. Assign the EL conversation_id to `elevenlabs_conversation_id` column.
3. Close normally.

This is essentially what `_reconcile_session` already does — but it only runs when `get_session(session_id)` returns None. The issue is the lookup order:

```python
# Current (router.py line 249):
cs_lookup = await get_session_by_elevenlabs_id(db, conversation_id)
resolved_session_id = cs_lookup.id if cs_lookup else conversation_id
# Then close_session(resolved_session_id, ...) which tries get_session(resolved_session_id)
# EL conv_id ≠ internal UUID → falls to reconciliation
```

The reconciliation path ALREADY handles this case! The fix is to ensure:
1. Frontend ALWAYS passes `client_id` and `lead_id` in the `/end` body (it already does — lines 727-728).
2. The reconciliation window is adequate (already increased to 600s).

**Wait — re-reading the code more carefully:**

The reconciliation DOES work, but only when the EL conversation_id was never stored in the DB. If the initiation webhook ran and created a session_store entry with the conversation_id, BUT the custom-LLM webhook then created a DIFFERENT CallSession with a `demo-*` ID... we get TWO session_store entries and only one DB record.

**The real gap**: The initiation webhook creates a session_store entry at `(client_id, conversation_id)` with `session_id=""` (line 211-217). Then the custom-LLM webhook can't find this entry because EL doesn't send `conversation_id` in the body — so it falls through to `find_by_client_lead` or generates a new `demo-*` ID.

**Approach C (Best): Multi-pronged fix**

1. **Frontend**: Include `client_id` in `custom_llm_extra_body` (it's already in the URL path, but having it in the body makes reconciliation hints more reliable).

2. **Backend webhook**: When the initiation webhook has already cached a session_store entry for a conversation_id but the custom-LLM webhook doesn't receive that conversation_id, the `find_by_client_lead` fallback should find the initiation-cached entry and reuse its conversation_id. **This already works!** (webhook.py lines 759-766).

3. **Backend /end**: The reconciliation path already handles the case where EL conversation_id isn't stored. Ensure reconciliation succeeds by:
   - Confirming the frontend always sends hints (already does).
   - Confirming window is adequate (600s — already set).

4. **Backend CallSession**: Add a secondary update path — when `/end` reconciles a session, it should also check if there are session_store entries that can be cleaned up.

**Actual remaining gap after re-analysis**:

The REAL scenario where it breaks is:
- Initiation webhook is NOT called (signed-URL flow bypasses it).
- Custom-LLM webhook creates a session with `demo-*` conversation_id and NULL `elevenlabs_conversation_id`.
- Frontend captures the real EL conversation_id from metadata event.
- `/end` sends the real EL conversation_id → no DB match → reconciliation kicks in.
- Reconciliation finds the orphan by (client_id, lead_id, status=initiated, el_conv_id IS NULL, within window) → **should work**.

So the question is: **is reconciliation actually failing?** Let me check the conditions more carefully...

The reconciliation query requires `CallSession.status == "initiated"`. But the session was created by the custom-LLM webhook and has had turns — does it stay `initiated`? **Yes, it does!** The session stays `initiated` until explicitly closed by `/end` or the post-call webhook.

**Conclusion for Problem 1**: The reconciliation mechanism should already handle this. The band-aid (600s window) should work. The remaining issues are:
1. **Race condition**: If the session gets cleaned up by `session_store.cleanup_expired(ttl_seconds=300)` before `/end` arrives.
2. **Missing client_id in custom_llm_extra_body**: The webhook uses path-based routing (`/{client_id}/custom-llm/...`), so client_id is in the URL. But `lead_id` comes from `custom_llm_extra_body` which only has `{ lead_id }`.

**Definitive fix proposal**:
1. Add `client_id` to `custom_llm_extra_body` in the frontend (redundant but makes reconciliation hints complete).
2. When the custom-LLM webhook creates a CallSession, try to backfill the EL conversation_id from the session_store entry created by initiation (if any).
3. When `/end` reconciles a session successfully, also store the EL conversation_id on the CallSession so the post-call webhook can find it later.

Wait — point 3 **already happens** in `_reconcile_session` (service.py line 482): `cs.elevenlabs_conversation_id = conversation_id`. So reconciliation DOES backfill the ID. ✓

### Affected Areas (Problem 1)

- `backend/app/static/index.html` — add `client_id` to `custom_llm_extra_body`
- `backend/app/voice/webhook.py` — backfill EL conversation_id from session_store
- `backend/app/calls/service.py` — verify reconciliation is robust (may need test coverage only)
- `backend/app/voice/session.py` — no changes needed

---

## Problem 2: CRM Match Field — Current Field Flow

### Current State

```
┌──────────────────────────────────────────────────────────────────┐
│                    CRM FIELD FLOW                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  AIRTABLE (source of truth for leads)                             │
│  ├─ lead_id: Number (populated by Meta/Facebook)                  │
│  ├─ Nombre Completo: string                                       │
│  ├─ Teléfono: phone                                               │
│  ├─ Correo electrónico: string  ◄── CURRENT match_field           │
│  └─ Status: singleSelect                                          │
│                                                                   │
│  QORA Lead Model (SQLite)                                         │
│  ├─ id: UUID (Qora internal — NOT related to Airtable lead_id)   │
│  ├─ name, phone, email, status, etc.                              │
│  ├─ external_crm_id: string (Airtable recXXX record ID)          │
│  └─ NO external_lead_id field! ◄── THE GAP                       │
│                                                                   │
│  CRM SYNC (PUSH: Qora → Airtable after post-call analysis)       │
│  ├─ match_field: "Correo electrónico" (crm.yaml line 29)         │
│  ├─ _lead_to_dict() maps Qora fields → flat dict                 │
│  ├─ FieldMapper.map() applies field_mappings + status_mapping     │
│  └─ AirtableAdapter.upsert_record() uses match_field for dedup   │
│                                                                   │
│  CRM IMPORT (PULL: Airtable → Qora on demand)                    │
│  ├─ FieldMapper.reverse_map() reverses field_mappings             │
│  ├─ Dedup: by phone (client_id, phone) — NOT by lead_id          │
│  └─ Stores: external_crm_id = Airtable recXXX                    │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

### Why Email Matching Is Fragile

1. **Email is optional** — leads without email can't be matched at all.
2. **Email can change** — a lead updating their email breaks the link.
3. **Airtable phone type fields** can't be used for upsert match (Airtable API limitation).
4. **The Airtable `lead_id` is numeric** (populated by Meta). Qora's `id` is a UUID. They're incompatible.

The TODO in crm.yaml (line 27-28) already documents the intended fix:
```yaml
# TODO: when import stores the numeric Meta lead_id in a Qora field, switch
# back to match_field: lead_id for stronger idempotency.
```

### Proposed Fix

1. **Add `external_lead_id` column to Lead model** — `Integer, nullable=True`.
   - This stores the Meta/Facebook numeric lead ID.
   - Different from `external_crm_id` (Airtable record ID string like `recXXX`).

2. **Populate during import** — add `external_lead_id` to the field_mappings:
   ```yaml
   - source: external_lead_id
     target: "lead_id"
     type: integer
   ```
   - `reverse_map()` will pick it up automatically.
   - `_update_lead_from_qora_data()` and `_create_lead_from_qora_data()` need to handle it.

3. **Add to `_lead_to_dict()`** — so the push sync maps it back.

4. **Switch match_field** in crm.yaml:
   ```yaml
   match_field: "lead_id"
   ```

5. **Auto-migration** — add column in `main.py` startup migration block.

### Affected Areas (Problem 2)

- `backend/app/leads/models.py` — add `external_lead_id: Mapped[int | None]` column
- `backend/app/main.py` — auto-migration for new column
- `backend/app/integrations/crm_import_service.py` — handle `external_lead_id` in update/create helpers
- `backend/app/integrations/crm_sync_service.py` — add `external_lead_id` to `_lead_to_dict()`
- `backend/clients/quintana-seguros/crm.yaml` — add field_mapping + change match_field
- Tests: `test_crm_import.py`, `test_crm_sync_service.py`, `test_field_mapping.py`

---

## Independence Assessment

**These two problems are INDEPENDENT.** They share zero code touchpoints:

| Aspect | Problem 1 (Conv ID) | Problem 2 (CRM Match) |
|--------|---------------------|----------------------|
| Root module | `voice/webhook.py` | `integrations/crm_sync_service.py` |
| Data model | `CallSession.elevenlabs_conversation_id` | `Lead.external_lead_id` (new) |
| Config | None | `crm.yaml` |
| Frontend | `index.html` (custom_llm_extra_body) | None |
| Trigger | Every call | Post-call CRM sync only |
| DB tables | `call_sessions` | `leads` |

**Recommendation**: Split into **two separate SDD changes** for cleaner review, testing, and rollback:
- **Change A**: `session-id-fix` — Conversation ID lifecycle fix
- **Change B**: `crm-match-field` — External lead ID + CRM match_field switch

They can be developed and deployed in parallel with no conflicts.

---

## Complexity Estimate

### Problem 1: Conversation ID Fix
- **Lines of change**: ~30-50 (frontend + webhook backfill)
- **Risk**: LOW-MEDIUM — mostly frontend JS + defensive backend logic
- **Effort**: Low
- **Testing**: Integration test for reconciliation path; manual test with signed-URL flow
- **Key risk**: ElevenLabs WebSocket protocol changes. Frontend changes are the simplest path.

### Problem 2: CRM Match Field
- **Lines of change**: ~60-80 (model, migration, import, sync, config, _lead_to_dict)
- **Risk**: LOW — additive column, backward-compatible config change
- **Effort**: Low-Medium
- **Testing**: Unit tests for import/sync with external_lead_id, migration test
- **Key risk**: Existing leads without external_lead_id need to be reimported or backfilled. First import after the change should populate the field.

---

## Risks and Edge Cases

### Problem 1
1. **Signed-URL flow without initiation webhook**: Initiation doesn't fire → no pre-cached session_store entry → webhook generates `demo-*` ID → `/end` must reconcile. This path works but depends on the 600s window.
2. **Multiple sessions for same (client_id, lead_id)**: `find_by_client_lead` returns the one with highest turn_count. If the user reconnects quickly, the old session might get matched. Mitigated by `cleanup_expired(ttl_seconds=300)`.
3. **ElevenLabs WebSocket metadata event format**: Currently extracting from `conversation_initiation_metadata_event.conversation_id`. If EL changes this structure, the frontend won't capture the ID.

### Problem 2
1. **Existing leads have no external_lead_id**: After deploying, a CRM import must be run to backfill the field. Until then, match_field still uses email.
2. **Leads without Meta lead_id in Airtable**: Some leads might be added manually (no Facebook form). These won't have a numeric lead_id in Airtable → match falls back to... nothing. Need a fallback strategy (keep email as secondary match?).
3. **Airtable lead_id field type**: Must verify it's a standard Number field, not a formula or auto-number. If it's an auto-number, Airtable won't accept upsert on it.
4. **Migration**: Adding a nullable column is safe (SQLite ALTER TABLE ADD COLUMN).

---

## Ready for Proposal

**Yes.** Both problems are well-understood with clear fix paths. Recommend splitting into two independent SDD changes:

1. **`session-id-fix`**: Fix the conversation ID lifecycle to ensure EL conversation_id is always persisted on CallSession. Focus on webhook backfill + frontend `client_id` in extra_body.
2. **`crm-match-field`**: Add `external_lead_id` to Lead model, populate during import, switch CRM match_field from email to lead_id.

Each can proceed through propose → spec → design → apply independently.
