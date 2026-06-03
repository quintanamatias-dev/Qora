# Tasks: Session ID Lifecycle Fix + CRM Match Field

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 90–130 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | auto-forecast |
| Chain strategy | pending |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: pending
400-line budget risk: Low

## Phase 1: Schema & Model (Foundation)

- [x] 1.1 **RED**: Write test asserting `Lead` model has `external_lead_id` Integer nullable column — `tests/test_lead_model.py`
- [x] 1.2 **GREEN**: Add `external_lead_id: Mapped[int | None] = mapped_column(Integer, nullable=True)` to `backend/app/leads/models.py` after `external_crm_id`
- [x] 1.3 Add auto-migration block in `backend/app/main.py`: `ALTER TABLE leads ADD COLUMN external_lead_id INTEGER DEFAULT NULL`

## Phase 2: Conversation ID Backfill (Problem 1)

- [x] 2.1 **RED**: Write test — when `find_by_client_lead` returns entry with real EL conv_id, assert `CallSession.elevenlabs_conversation_id` is set to that value — `tests/test_webhook_conv_id_backfill.py`
- [x] 2.2 **RED**: Write test — when entry has `demo-*` conv_id, assert `elevenlabs_conversation_id` remains None
- [x] 2.3 **GREEN**: In `backend/app/voice/webhook.py` `_process_custom_llm_request`, inside `elif lead_id:` branch after `find_by_client_lead`, add: if `existing.conversation_id` doesn't start with `demo-`, set `persisted_conversation_id = existing.conversation_id`
- [x] 2.4 **REFACTOR**: Verify no dead paths — ensure reconciliation fallback still works as safety net

## Phase 3: CRM Import & Sync (Problem 2)

- [x] 3.1 **RED**: Write test — `_create_lead_from_qora_data` with `external_lead_id` populates `Lead.external_lead_id` — `tests/test_crm_import_external_lead_id.py`
- [x] 3.2 **RED**: Write test — `_update_lead_from_qora_data` updates `external_lead_id` on existing Lead
- [x] 3.3 **RED**: Write test — `_lead_to_dict()` includes `external_lead_id` when present, omits when None
- [x] 3.4 **GREEN**: In `backend/app/integrations/crm_import_service.py`, add `external_lead_id` handling in `_create_lead_from_qora_data()` and `_update_lead_from_qora_data()`
- [x] 3.5 **GREEN**: In `backend/app/integrations/crm_sync_service.py`, add `external_lead_id` to `_lead_to_dict()` output
- [x] 3.6 Update `backend/clients/quintana-seguros/crm.yaml`: add field_mapping `external_lead_id → lead_id` (type: integer), change `match_field` to `"lead_id"`

## Phase 4: Integration Verification

- [x] 4.1 Write integration test: backfill path — session_store entry with real EL conv_id → CallSession stored with correct elevenlabs_conversation_id
- [x] 4.2 Write integration test: CRM import with Airtable record containing numeric `lead_id` → assert `Lead.external_lead_id` populated
- [x] 4.3 Run full test suite: `cd backend && python3 -m pytest tests/ -q` — 1980 passed, 2 pre-existing failures (unrelated)
- [x] 4.4 Run linter: `cd backend && ruff check .` — no new errors introduced (6 pre-existing E402 in main.py from load_dotenv pattern)

## Dependency Order

Phase 1 → Phase 2 and Phase 3 (independent of each other) → Phase 4 (integration tests depend on both fixes being in place).

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Both fixes + all tests | Single PR | ~100 lines, well under 800-line budget |
