# Design: Session ID Lifecycle Fix + CRM Match Field

## Technical Approach

Two independent changes sharing no code touchpoints. Problem 1 adds an EL conversation_id backfill in the webhook's session-creation path using session_store data cached at initiation. Problem 2 adds a nullable Integer column to Lead and wires it through import/sync/config.

## Architecture Decisions

| Decision | Options | Tradeoff | Choice |
|----------|---------|----------|--------|
| Where to backfill EL conv_id | (A) Webhook session-creation, (B) /end reconciliation only | A catches it earlier, reduces reconciliation dependency; B already exists but fires late | **A** — backfill at webhook time, keep B as safety net |
| Backfill source | (A) session_store entry from initiation, (B) parse EL metadata in webhook | A is zero-cost (data already cached); B requires new parsing logic | **A** — `session_store.find_by_client_lead` already returns the initiation-cached entry which may have the EL conv_id |
| Frontend changes for conv_id | (A) Add client_id to extra_body, (B) No frontend changes | Proposal says backend-only; extra_body already carries lead_id, client_id is in URL path | **B** — NO frontend changes. client_id is already in the URL path `/{client_id}/custom-llm/...` |
| external_lead_id column type | Integer vs BigInteger | Meta lead IDs are numeric, confirmed by user. Standard Integer (64-bit in SQLite) is sufficient | **Integer, nullable** |
| Import dedup key change | (A) Switch to external_lead_id dedup, (B) Keep phone dedup | Phone dedup works today; external_lead_id is for CRM match_field, not import dedup | **B** — Keep phone dedup for import, external_lead_id is only for push sync match_field |

## Data Flow

### Problem 1: Conversation ID Resolution (fixed)

```
Initiation webhook ──→ session_store.create(conv_id=EL_ID, session_id="")
                                │
Custom-LLM webhook ─────────────┤
  ├─ EL sends conv_id? ──YES──→ use it (persisted_conversation_id)
  ├─ NO: find_by_client_lead() ──→ found initiation entry?
  │   ├─ YES: reuse its conversation_id (may be real EL ID)
  │   │   └─ BACKFILL: set elevenlabs_conversation_id on new CallSession
  │   └─ NO: generate demo-* fallback (existing behavior)
  └─ create CallSession with elevenlabs_conversation_id = backfilled or NULL
                                │
/end endpoint ──────────────────┤
  ├─ get_session_by_elevenlabs_id(EL_ID) ──→ FOUND (backfill worked)
  └─ NOT FOUND ──→ reconciliation fallback (safety net, unchanged)
```

**Key insight**: The initiation webhook (initiation.py:210-217) creates a session_store entry with `conversation_id=resolved_conversation_id` and `session_id=""`. The custom-LLM webhook's `find_by_client_lead` (webhook.py:761) finds this entry and reuses its `conversation_id`. But the initiation entry's conversation_id IS the EL conversation_id — so when the webhook creates the CallSession, it should store this as `elevenlabs_conversation_id`.

**The actual bug**: At webhook.py:755-768, when `persisted_conversation_id` is None (EL didn't send conv_id in the body), the code falls to `find_by_client_lead` and reuses the *session_store key* as `conversation_id` — but it does NOT set `elevenlabs_conversation_id` on the CallSession. The CallSession gets `elevenlabs_conversation_id=None` (webhook.py:1087). Later, `/end` searches by `elevenlabs_conversation_id` and finds nothing.

**Fix location**: webhook.py `_process_custom_llm_request`, in the `elif lead_id:` branch (line 759-765). When `find_by_client_lead` finds an initiation-cached entry, check if that entry's `conversation_id` looks like a real EL conversation_id (not a `demo-*` fallback). If so, set `persisted_conversation_id` to that value so the CallSession stores it as `elevenlabs_conversation_id`.

### Problem 2: External Lead ID

```
Airtable record ──→ reverse_map() ──→ qora_data["external_lead_id"]
                                           │
  _create_lead_from_qora_data() ───────────┤──→ Lead.external_lead_id = value
  _update_lead_from_qora_data() ───────────┘

Lead (DB) ──→ _lead_to_dict() ──→ {"external_lead_id": N}
                                       │
  FieldMapper.map() ───────────────────┘──→ {"lead_id": N}
                                                │
  adapter.upsert_record(match_field="lead_id") ─┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/voice/webhook.py` | Modify | In `_process_custom_llm_request`, when `find_by_client_lead` returns an existing entry, backfill `persisted_conversation_id` from the entry's `conversation_id` if it's not a `demo-*` ID |
| `backend/app/leads/models.py` | Modify | Add `external_lead_id: Mapped[int \| None] = mapped_column(Integer, nullable=True)` after `external_crm_id` |
| `backend/app/main.py` | Modify | Add migration block: `ALTER TABLE leads ADD COLUMN external_lead_id INTEGER DEFAULT NULL` |
| `backend/app/integrations/crm_import_service.py` | Modify | Handle `external_lead_id` in `_update_lead_from_qora_data()` and `_create_lead_from_qora_data()` |
| `backend/app/integrations/crm_sync_service.py` | Modify | Add `external_lead_id` to `_lead_to_dict()` |
| `backend/clients/quintana-seguros/crm.yaml` | Modify | Add field_mapping entry `external_lead_id` ↔ `lead_id` (type: integer); change `match_field` to `"lead_id"` |

## Interfaces / Contracts

### Problem 1: No new interfaces

The fix is a single conditional inside `_process_custom_llm_request`. The `ConversationState.conversation_id` field and `CallSession.elevenlabs_conversation_id` column already exist.

```python
# webhook.py — inside the `elif lead_id:` branch (line 759)
existing = session_store.find_by_client_lead(client_id, lead_id)
if existing is not None:
    conversation_id = existing.conversation_id
    conv_state = existing
    # BACKFILL: if the initiation-cached entry has a real EL conversation_id,
    # promote it so the new CallSession stores it as elevenlabs_conversation_id
    if not existing.conversation_id.startswith("demo-"):
        persisted_conversation_id = existing.conversation_id
```

### Problem 2: Lead model addition

```python
# leads/models.py — after external_crm_id
external_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Conv_id backfill when initiation entry has real EL ID | Mock session_store.find_by_client_lead returning entry with EL conv_id; assert CallSession.elevenlabs_conversation_id is set |
| Unit | Conv_id backfill skipped when entry has demo-* ID | Mock returning demo-* entry; assert elevenlabs_conversation_id is NULL |
| Unit | external_lead_id in _create/_update helpers | Pass qora_data with external_lead_id; assert Lead attribute set |
| Unit | external_lead_id in _lead_to_dict | Create Lead with external_lead_id; assert key present in output dict |
| Unit | FieldMapper forward+reverse with integer lead_id | Existing field_mapping tests extended with new mapping entry |
| Integration | Full /end flow with backfilled conv_id | Call initiation → webhook → /end; assert session closes successfully |
| Integration | CRM import populates external_lead_id | Mock Airtable records with numeric lead_id; assert Lead.external_lead_id populated |

## Migration / Rollout

- **Problem 1**: Zero DB changes. Deploy and all new calls benefit immediately. Existing orphaned sessions are not retroactively fixed (acceptable).
- **Problem 2**: `ALTER TABLE leads ADD COLUMN external_lead_id INTEGER DEFAULT NULL` — instant, non-locking in SQLite. After deploy, run one CRM import (`POST /api/v1/clients/quintana-seguros/crm/import`) to backfill existing leads. Then switch `match_field` in crm.yaml (can be done in the same deploy).

## Open Questions

- [x] ~~Meta lead_id is numeric?~~ Confirmed by user — Integer.
- [x] ~~Frontend changes allowed?~~ NO. Backend-only constraint confirmed.
- [ ] Verify Airtable `lead_id` field is a standard Number field (not formula/auto-number) before switching match_field — if it's auto-number, Airtable rejects upsert on it. One-time manual check required before deploy.
