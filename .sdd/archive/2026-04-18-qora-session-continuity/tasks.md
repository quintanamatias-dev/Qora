# Tasks: qora-session-continuity

## Phase 1 — Backend session creation (Group 1 / CAP-3)

- [x] **1.1 / T01 — test / RED** — CAP-3 REQ-3.1, scenario `conversation_id` persisted. **Files:** `backend/tests/unit/voice/test_custom_llm_path_route.py`. **Accept:**
  - Failing test posts custom-LLM payload with `conversation_id` and asserts created `CallSession.elevenlabs_conversation_id`.

- [x] **1.2 / T02 — test / RED** — CAP-3 REQ-3.2, scenario `lead_id` persisted. **Files:** `backend/tests/unit/voice/test_custom_llm_path_route.py`. **Accept:**
  - Failing test posts payload with `elevenlabs_extra_body.lead_id` and asserts `CallSession.lead_id`.

- [x] **1.3 / T03 — test / RED** — CAP-3 REQ-3.3, empty strings → NULL. **Files:** `backend/tests/unit/voice/test_custom_llm_path_route.py`. **Accept:**
  - Failing test covers `conversation_id=""` and `lead_id=""`; persisted values are `NULL`.

- [x] **1.4 / T04 — prod / GREEN** — CAP-3 REQ-3.1. **Files:** `backend/app/calls/service.py`. **Accept:**
  - `create_session()` accepts `elevenlabs_conversation_id` and stores it without breaking existing callers.

- [x] **1.5 / T05 — prod / GREEN** — CAP-3 REQ-3.1/3.2/3.3. **Files:** `backend/app/voice/webhook.py`. **Accept:**
  - `_process_custom_llm_request` resolves `conversation_id` from body / `elevenlabs_extra_body`, resolves `lead_id`, coerces empty strings to `None`, and passes both to `create_session()`.
  - `custom_llm_path_request` log includes `lead_id`.

## Phase 2 — /end reconciliation fallback (Group 2 / CAP-4)

- [x] **2.1 / T06 — test / RED** — CAP-4 reconciliation happy path. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test proves unknown `conversation_id` reconciles matching `(client_id, lead_id)` initiated session within 120s.

- [x] **2.2 / T07 — test / RED** — CAP-4 idempotency / counter rule. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Parametrized failing test proves `Lead.call_count` increments exactly once for direct close and reconciled close.

- [x] **2.3 / T08 — test / RED** — CAP-4 expired window. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test returns 404 for matching initiated session older than 120s.

- [x] **2.4 / T09 — test / RED** — CAP-4 tenant isolation. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test proves wrong-tenant session is never reconciled.

- [x] **2.5 / T10 — test / RED** — CAP-4 status filter. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test proves only `status="initiated"` sessions qualify.

- [x] **2.6 / T11 — test / RED** — CAP-4 newest match wins. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test asserts `ORDER BY started_at DESC LIMIT 1` behavior.

- [x] **2.7 / T12 — test / RED** — CAP-4 logging contract. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test captures `end_session_reconciled` with `{reconciled_session_id, client_id, lead_id, conversation_id, age_seconds}`.

- [x] **2.8 / T13 — test / RED** — CAP-4 backward compatibility. **Files:** `backend/tests/unit/calls/test_end_endpoint.py`. **Accept:**
  - Failing test keeps 404 when `conversation_id` unknown and hints missing.

- [x] **2.9 / T14 — prod / GREEN** — CAP-4 design constant. **Files:** `backend/app/calls/service.py`. **Accept:**
  - Add `RECONCILIATION_WINDOW_SECONDS = 120` as module constant.

- [x] **2.10 / T15 — prod / GREEN** — CAP-4 reconciliation implementation. **Files:** `backend/app/calls/service.py`. **Accept:**
  - `close_session()` accepts `reconcile_client_id` / `reconcile_lead_id`, reconciles initiated NULL-conversation session in-place, computes close fields, preserves idempotency, updates lead counters once, and emits reconciliation log.

- [x] **2.11 / T16 — prod / GREEN** — CAP-4 request contract. **Files:** `backend/app/calls/schemas.py`. **Accept:**
  - `EndSessionRequest` adds optional `client_id` and `lead_id` with `None` defaults.

- [x] **2.12 / T17 — prod / GREEN** — CAP-4 router wiring. **Files:** `backend/app/calls/router.py`. **Accept:**
  - `/end` passes reconciliation hints through to `close_session()` and preserves existing 404 behavior on final miss.

## Phase 3 — Frontend propagation + E2E cycle (Groups 3–4 / CAP-1,2,5)

- [x] **3.1 / T18 — test / RED** — CAP-1/3 frontend-contract backend proof. **Files:** `backend/tests/unit/voice/test_custom_llm_path_route.py`. **Accept:**
  - Failing test simulates EL-forwarded payload with `elevenlabs_extra_body.lead_id` and proves DB session stores `lead_id`.
  - **Outcome**: Satisfied by existing T02 test (`test_path_route_creates_session_with_lead_id`). Already passes.

- [x] **3.2 / T19 — prod / GREEN** — CAP-1 REQ-1.1 + stale comment removal. **Files:** `backend/app/static/index.html`. **Accept:**
  - WS `conversation_initiation_client_data` includes `custom_llm_extra_body: { lead_id }` only when truthy.
  - Remove stale rejection comment and replace it with EL docs citation.

- [x] **3.3 / T20 — prod / GREEN** — CAP-2 REQ-2.2. **Files:** `backend/app/static/index.html`. **Accept:**
  - `closeSessionOnBackend` POST body includes `client_id` and `lead_id` next to existing fields.
  - **Note**: Function signature extended to `closeSessionOnBackend(sessionId, reason, clientId, leadId)` — passed as args from closures since const vars are not accessible from module-level function.

- [x] **3.4 / T21 — test / RED** — CAP-5 full memory cycle. **Files:** `backend/tests/integration/voice/test_session_continuity_e2e.py`. **Accept:**
  - Integration test covers call 1 initiation, `/end`, summary persistence, and call 2 returning `is_returning_caller=true` with non-empty `call_history`.
  - **Outcome**: Test passes immediately — Batch 1 fixes unblock memory cycle end-to-end.

- [x] **3.5 / T22 — prod / GREEN** — CAP-5 glue. **Files:** none needed. **Accept:**
  - Minimal fixups make T21 pass without widening scope.
  - **Outcome**: No production code needed — Batch 1 already implements the full cycle.

## Phase 4 — Docs + verification (Groups 5–6)

- [x] **4.1 / T23 — docs / GREEN** — CAP-1/2/4 operator guidance. **Files:** `docs/elevenlabs-setup.md`. **Accept:**
  - Add "Session Continuity & custom_llm_extra_body" covering forwarded fields, why only `lead_id` is sent, `/end` reconciliation window, and EL docs link.

- [x] **4.2 / T24 — verify** — full regression. **Files:** none. **Accept:**
  - Run `python3 -m pytest tests/ -q` from `backend/`; all tests pass.
  - **Outcome**: 301/301 passed in 3.63s. ✅

- [x] **4.3 / T25 — verify** — lint/format gate. **Files:** none. **Accept:**
  - Run `ruff check .` and `ruff format --check .` from `backend/`; both pass.
  - **Outcome**: `ruff format .` applied to 7 files (Batch 1+2 code, no lint issues). Both checks now clean. ✅

- [x] **4.4 / T26 — verify** — manual smoke. **Files:** none. **Accept:**
  - Curl checks confirm session creation with `lead_id`, successful reconciliation with hints, and 404 without hints.
  - **Outcome**: All 3 tests passed. See apply-progress for full curl outputs. ✅

## Recommended batches

- **Batch 1:** T01–T17 — backend tests, schema, service, router.
- **Batch 2:** T18–T22 — frontend propagation and E2E continuity.
- **Batch 3:** T23–T26 — docs and final verification.

## Verify Remediation — Round 1

- [x] **T27 — RED+GREEN** — Empty/absent conversation_id stores NULL in DB (CAP-3 / REQ-3.3). **Files:** `backend/app/voice/webhook.py`, `backend/tests/unit/voice/test_custom_llm_path_route.py`. **Outcome:** 2 RED tests written; fixed by separating `persisted_conversation_id` (NULL when absent/empty) from `conversation_id` (demo-* fallback for session_store key only). Both tests GREEN. ✅

- [x] **T28 — RED+GREEN** — duration_seconds must be integer, not float (CAP-4). **Files:** `backend/app/calls/service.py`, `backend/app/calls/schemas.py`, `backend/tests/unit/calls/test_end_endpoint.py`. **Outcome:** 2 tests (direct + reconciliation paths). Both service paths now cast to `int(...)`. Schema changed to `int | None`. Both tests GREEN. ✅

- [x] **T29 — GREEN** — Backend tolerates absent custom_llm_extra_body (CAP-1 / REQ-1.3). **Files:** `backend/tests/unit/voice/test_custom_llm_path_route.py`. **Outcome:** Backend already supported this (ElevenLabsExtraBody has default_factory). Test added as contract proof. ✅ **Spec note:** REQ-1.3 is satisfied at backend contract level; frontend UX does not currently offer a no-lead demo mode by product choice.

- [x] **T30 — GREEN** — /end body accepts conversation_id with mismatch detection (CAP-2 / REQ-2.2). **Files:** `backend/app/calls/schemas.py`, `backend/app/calls/router.py`, `backend/app/static/index.html`, `backend/tests/unit/calls/test_end_endpoint.py`. **Outcome:** `EndSessionRequest` gets optional `conversation_id` field; router logs `conversation_id_mismatch_end` warning when body differs from path (path always wins); frontend `closeSessionOnBackend` now includes `conversation_id` in body. 2 tests GREEN (match + mismatch). ✅
