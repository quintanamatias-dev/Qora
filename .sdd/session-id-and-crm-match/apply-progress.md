# Apply Progress: session-id-and-crm-match

**Change**: `session-id-and-crm-match`
**Mode**: Strict TDD
**Phase**: Apply + Apply-Fix + Apply-Fix Pass 2 + Apply-Fix Pass 3 (Test Coverage)
**Final Status**: COMPLETE — 1995 passed, 0 ruff errors

---

## Completed Tasks (Original — 14/14)

- [x] 1.1 Lead model `external_lead_id: Mapped[int | None]` column
- [x] 1.2 Migration: `ALTER TABLE leads ADD COLUMN external_lead_id INTEGER` at startup
- [x] 2.1 Webhook backfill: promote real EL conv_id from session_store
- [x] 2.2 Webhook demo-* guard: do NOT promote demo-* conv_ids
- [x] 3.1 `_create_lead_from_qora_data` populates `external_lead_id`
- [x] 3.2 `_update_lead_from_qora_data` updates `external_lead_id`
- [x] 3.3 `_lead_to_dict` includes `external_lead_id`
- [x] 3.4 `crm.yaml` field_mappings adds `external_lead_id → lead_id (integer)`
- [x] 3.5 `crm.yaml` `match_field: "lead_id"` updated
- [x] 3.6 `_FakeLead` in `test_crm_status_mapping.py` gains `external_lead_id`
- [x] 4.1 Integration test: DB + import pipeline creates lead with `external_lead_id`
- [x] 4.2 Integration test: session backfill verified via test_session_id_and_crm_match.py
- [x] 4.3 Integration test: CRM match via `external_lead_id`
- [x] 4.4 Integration test: session lifecycle with reconciliation

## Completed Tasks (Apply-Fix Pass 1 — 5/5)

- [x] F1: Fix 2 failing tests (updated 200s → 700s, window is now 600s not 120s)
- [x] F2: Fix 28 ruff errors (unused imports, E402 noqa, duplicate key, redefined names)
- [x] F3: `external_lead_id` fallback — `sync_lead` now detects absent match_field in payload and skips gracefully with warning
- [x] F4: Duplicate `external_lead_id` detection — `_update_lead_from_qora_data` logs WARNING when another lead holds the same value
- [x] F5: Reconciliation turn_count ordering — `_reconcile_session` orders by `(total_user_turns + total_agent_turns) DESC, started_at DESC`

## Completed Tasks (Apply-Fix Pass 2 — 5/5)

- [x] P2-F1: Webhook backfill DB persistence — `conv_state` with `session_id=""` now triggers `create_session` call; `conv_state.session_id` updated with new DB session id
- [x] P2-F2a: CRM sync fallback to `external_crm_id` — when primary `match_field` absent from payload, tries target field mapped from `external_crm_id` source
- [x] P2-F2b: CRM sync fallback to `email` — if `external_crm_id` also absent, tries target field mapped from `email` source
- [x] P2-F2c: CRM sync all fallbacks null → skip with warning (already worked; updated message to list fallback tiers tried)
- [x] P2-F3: Duplicate `external_lead_id` detection in sync — DB query before upsert; logs WARNING and continues (does not block)

## Completed Tasks (Apply-Fix Pass 3 — Test Coverage — 3/3)

- [x] P3-F1: Startup migration test for `external_lead_id` — added `old_leads_db` fixture and 3 tests to `test_startup_schema_compat.py`: column added, NULL default on existing rows, idempotent second run
- [x] P3-F2: Race/reconnect scenario tests — added 3 unit tests to `test_session.py`: separate DB records coexist in store, `find_by_client_lead` returns newer session, TTL cleanup removes stale session while preserving fresh one
- [x] P3-F3: Backfill test quality — replaced 2 copied-logic tests in `test_webhook_conv_id_backfill.py` (tasks 2.1, 2.2) with outcome-based tests that call `_process_custom_llm_request` and assert what `create_session` received (`elevenlabs_conversation_id`), not which if-branch ran

---

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `backend/app/leads/models.py` | Modified | Added `external_lead_id: Mapped[int \| None]` |
| `backend/app/main.py` | Modified | Startup migration for `external_lead_id`; noqa E402 comments |
| `backend/app/voice/webhook.py` | Modified | Backfill: split `if conv_state` branch to handle `session_id=""` case — new `elif conv_state and not conv_state.session_id:` calls `create_session` and updates `conv_state.session_id` |
| `backend/app/integrations/crm_import_service.py` | Modified | `_create/update_lead` handle `external_lead_id`; duplicate detection via `_find_lead_by_external_lead_id`; `_update_lead_from_qora_data` gains `existing_external_lead_id_holder` param |
| `backend/app/integrations/crm_sync_service.py` | Modified | `_lead_to_dict` includes `external_lead_id` and `external_crm_id`; step 4b: fallback to `external_crm_id` then `email` match when primary absent; step 4c: duplicate `external_lead_id` detection via DB query; added `from sqlalchemy import select` |
| `backend/clients/quintana-seguros/crm.yaml` | Modified | `match_field: "lead_id"`, added `external_lead_id` field mapping |
| `backend/app/calls/service.py` | Modified | `RECONCILIATION_WINDOW_SECONDS = 600`; `_reconcile_session` orders by turn count DESC |
| `backend/app/agents/router.py` | Modified | Removed duplicate datetime import (syntax error fix) |
| `backend/app/agents/schemas.py` | Modified | Removed unused `model_validator` import |
| `backend/tests/unit/calls/test_end_endpoint.py` | Modified | Updated expired window test (200s→700s); added turn_count test |
| `backend/tests/unit/calls/test_merge_sessions.py` | Modified | Updated outside-window test (200s→700s) |
| `backend/tests/test_crm_import_external_lead_id.py` | Modified | Added duplicate detection test |
| `backend/tests/integration/integrations/test_crm_sync_service.py` | Modified | Replaced skip-only test with 4 new TDD tests: external_crm_id fallback, email fallback, all-null skip, duplicate detection |
| `backend/tests/test_webhook_conv_id_backfill.py` | Modified (Pass 3) | Replaced 2 copied-logic tests (2.1, 2.2) with outcome-based tests calling `_process_custom_llm_request`; added `_make_patch_context` helper to share patch stack; 3 tests total |
| `backend/tests/unit/test_crm_status_mapping.py` | Modified | `_FakeLead` gains `external_crm_id` attribute |
| `backend/tests/unit/test_startup_schema_compat.py` | Modified (Pass 3) | Added `old_leads_db` fixture + 3 tests for `external_lead_id` column migration |
| `backend/tests/unit/voice/test_session.py` | Modified (Pass 3) | Added 3 reconnect/race tests: separate records coexist, `find_by_client_lead` returns newer, TTL cleanup removes stale |
| Multiple test files | Modified | Removed unused imports (ruff F401/F811/F821/F601 fixes) |

---

## TDD Cycle Evidence

| Task | RED | GREEN | REFACTOR |
|------|-----|-------|---------|
| 1.1 Lead model column | 3 tests failed TypeError | 3 tests pass | — |
| 2.1 Real conv_id backfill | Logic tests as assertions | Fix in webhook.py | — |
| 2.2 Demo conv_id no-backfill | Assertion inline | Confirmed by same fix | — |
| 3.1 `_create_lead` external_lead_id | 1 test failed | Passes after fix | — |
| 3.2 `_update_lead` external_lead_id | 1 test failed | Passes after fix | — |
| 3.3 `_lead_to_dict` external_lead_id | 2 tests failed | Passes after fix | — |
| F1 Window tests (2 failures) | 200s now inside 600s window | Updated to 700s; passes | — |
| F3 Null external_lead_id sync | test fails (upsert called) | Guard added; not called | — |
| F4 Duplicate detection (import) | test fails (unknown kwarg) | Param + warning added | — |
| F5 Turn count ordering | test fails (newer session picked) | Order by turns DESC | — |
| P2-F1 Webhook backfill DB persistence | 0 create_session calls → FAIL | `elif not conv_state.session_id:` branch calls create_session | Removed unused `response` var |
| P2-F2a external_crm_id fallback | 0 upsert calls → FAIL | Fallback loop + model_copy in step 4b | — |
| P2-F2b email fallback | 0 upsert calls → FAIL | Same fallback loop covers email tier | — |
| P2-F2c all-null skip | PASS (existing skip) | Passes after 4b refactor | Updated warning message |
| P2-F3 sync duplicate detection | No warning logged → FAIL | DB query step 4c; logger.warning | — |
| P3-F1 external_lead_id startup migration | Tests missing (gap) | 3 tests added; all pass | — |
| P3-F2 reconnect/race scenario | Tests missing (gap) | 3 tests added; all pass | — |
| P3-F3 backfill test quality | 2 tests copied branch logic | Replaced with outcome-based tests calling production `_process_custom_llm_request` | Extracted `_make_patch_context` helper |

---

## Command Evidence (Final Pass 3)

| Command | Exit | Result |
|---------|------|--------|
| `cd backend && python3 -m pytest tests/ -q` | 0 | `1995 passed, 3 warnings` |
| `cd backend && ruff check .` | 0 | `All checks passed!` |

---

## Deviations from Design

None — all fixes are test-only. Production code was not modified in Pass 3.

## Issues Found

None — all 3 test coverage gaps from verify Pass 3 resolved. Suite grew from 1989 to 1995 tests.
