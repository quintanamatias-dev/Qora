# Tasks: QORA Phase 0

## Summary
- Total tasks: 32
- Estimated sessions: 10-13
- Strategy: strict TDD per capability (RED → GREEN → REFACTOR), then API wiring and seed verification.

## Group 0 — Project Cleanup & Foundation

- [x] **T0.1 (RED, S)** Define test harness/bootstrap in `backend/tests/conftest.py`, `backend/tests/factories/`, and `backend/pytest.ini` for async DB, app factory, respx, and SSE fixtures.  
  **Files:** create/modify `backend/tests/conftest.py`, `backend/tests/fixtures/openai_sse.py`, `backend/pytest.ini`.  
  **AC:** async tests run against isolated SQLite; OpenAI/ElevenLabs mocks reusable.
- [x] **T0.2 (GREEN, M)** Remove replaced runtime modules and create QORA domain skeleton.  
  **Files:** delete old `backend/app/voice/`, `channels/`, `recording/`, `agents/` paths being replaced; create `core/`, `tenants/`, `leads/`, `calls/`, `voice/`, `tools/`, `prompts/`.  
  **Deps:** T0.1. **AC:** no stale Twilio pipeline imports remain; new package layout imports cleanly.
- [x] **T0.3 (GREEN, S)** Rewrite foundation config/bootstrap.  
  **Files:** `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/db.py`, `backend/app/core/logging.py`.  
  **Deps:** T0.2. **AC:** app starts with lifespan skeleton, health check, DB session dependency, structlog setup.
- [x] **T0.4 (GREEN, S)** Align dependency/config surface for QORA.  
  **Files:** `backend/pyproject.toml`, `backend/.env.example`.  
  **Deps:** T0.3. **AC:** required libs/settings for FastAPI async SQLite, respx, and OpenAI SSE tests are declared.

## Group 1 — Core Domain: Tenants

- [x] **T1.1 (RED, S)** Write tenant model/service tests for CRUD, unknown tenant, and seed guard.  
  **Files:** `backend/tests/unit/tenants/test_service.py`.  
  **Deps:** T0.1. **AC:** covers Quintana seed + cross-tenant lookup behavior.
- [x] **T1.2 (GREEN, M)** Implement `Client` and `AgentConfig` persistence/services.  
  **Files:** `backend/app/tenants/models.py`, `backend/app/tenants/service.py`.  
  **Deps:** T1.1. **AC:** CRUD works; one Quintana Seguros client seeded with Jaumpablo defaults.
- [x] **T1.3 (GREEN, S)** Expose minimal tenant admin/debug router.  
  **Files:** `backend/app/tenants/router.py`.  
  **Deps:** T1.2. **AC:** GET by id returns tenant config or 404.

## Group 2 — Core Domain: Leads

- [x] **T2.1 (RED, M)** Write state machine tests for all valid/invalid transitions from CAP-3.  
  **Files:** `backend/tests/unit/leads/test_state_machine.py`.  
  **Deps:** T0.1. **AC:** 409 semantics represented in service results/exceptions.
- [x] **T2.2 (RED, S)** Write lead CRUD/seed tests including duplicate-seed guard and tenant scoping.  
  **Files:** `backend/tests/unit/leads/test_service.py`.  
  **Deps:** T0.1. **AC:** verifies 5 Quintana leads and required initial statuses.
- [x] **T2.3 (GREEN, M)** Implement `Lead` model, enum, transition rules, and CRUD.  
  **Files:** `backend/app/leads/models.py`, `backend/app/leads/service.py`.  
  **Deps:** T2.1, T2.2. **AC:** full schema persisted; invalid transitions rejected; `called` transition available for initiation flow.
- [x] **T2.4 (GREEN, S)** Add lead admin/debug router.  
  **Files:** `backend/app/leads/router.py`.  
  **Deps:** T2.3. **AC:** GET/PATCH endpoints scope queries by `client_id`.

## Group 3 — Core Domain: Calls

- [x] **T3.1 (RED, S)** Write call lifecycle tests for start/add_turn/end/billing and abandoned finalization.  
  **Files:** `backend/tests/unit/calls/test_service.py`.  
  **Deps:** T0.1. **AC:** covers transcript count, outcome updates, CEIL billing.
- [x] **T3.2 (RED, S)** Write filler state tests for dedup and last-filler tracking.  
  **Files:** `backend/tests/unit/voice/test_filler.py`.  
  **Deps:** T0.1. **AC:** no consecutive filler repeats in one conversation.
- [x] **T3.3 (GREEN, M)** Implement call session and transcript persistence/service.  
  **Files:** `backend/app/calls/models.py`, `backend/app/calls/service.py`.  
  **Deps:** T3.1. **AC:** sessions persist lifecycle fields and transcript turns.
- [x] **T3.4 (GREEN, S)** Implement in-memory `ConversationState` store and filler helpers.  
  **Files:** `backend/app/voice/filler.py`.  
  **Deps:** T3.2. **AC:** tracks `session_id`, `turn_count`, `last_filler`, fallback-safe filler selection.
- [x] **T3.5 (GREEN, S)** Add call admin/debug router.  
  **Files:** `backend/app/calls/router.py`.  
  **Deps:** T3.3. **AC:** call/session inspection endpoint available for tests.

## Group 4 — Voice: ElevenLabs Webhooks

- [x] **T4.1 (RED, M)** Write initiation webhook integration tests for found lead, missing lead, timeout, call creation, and auto-`called` transition.  
  **Files:** `backend/tests/integration/voice/test_initiation.py`.  
  **Deps:** T2.3, T3.3. **AC:** covers CAP-2 scenarios.
- [x] **T4.2 (GREEN, M)** Implement initiation webhook.  
  **Files:** `backend/app/voice/initiation.py`.  
  **Deps:** T4.1. **AC:** returns 7 `dynamic_variables`, creates call session, tolerates unknown/slow lead lookup.
- [x] **T4.3 (RED, L)** Write custom-LLM integration tests for 422 missing client, 404 unknown tenant, first filler token, `[DONE]`, tool-call midstream, and abandoned disconnect.  
  **Files:** `backend/tests/integration/voice/test_custom_llm.py`.  
  **Deps:** T1.2, T2.3, T3.4. **AC:** covers CAP-1/CAP-5/CAP-7 webhook scenarios.
- [x] **T4.4 (GREEN, L)** Extend streaming client to surface content + tool-call deltas.  
  **Files:** `backend/app/ai/llm_streaming.py`.  
  **Deps:** T4.3. **AC:** supports multi-phase stream continuation after tool execution.
- [x] **T4.5 (GREEN, L)** Implement custom LLM webhook with tenant routing, lead injection, SSE, fallback timer, transcript persistence, and disconnect finalization.  
  **Files:** `backend/app/voice/webhook.py`.  
  **Deps:** T4.3, T4.4, T5.5, T6.3. **AC:** OpenAI-compatible SSE within 500ms, first token filler, tool loop works.

## Group 5 — Tools: Agent Actions

- [x] **T5.1 (RED, S)** Write `get_lead_details` tests.  
  **Files:** `backend/tests/unit/tools/test_get_lead_details.py`.  
  **Deps:** T2.3. **AC:** existing lead returns full JSON, increments `call_count`, sets `last_called_at`.
- [x] **T5.2 (RED, S)** Write `register_interest` tests.  
  **Files:** `backend/tests/unit/tools/test_register_interest.py`.  
  **Deps:** T2.3. **AC:** missing-field error and successful `interested` transition covered.
- [x] **T5.3 (RED, S)** Write `mark_not_interested` and `schedule_followup` tests.  
  **Files:** `backend/tests/unit/tools/test_mark_not_interested.py`, `backend/tests/unit/tools/test_schedule_followup.py`.  
  **Deps:** T2.3. **AC:** reason/date persistence and transition rules covered.
- [x] **T5.4 (GREEN, M)** Implement four tool handlers.  
  **Files:** `backend/app/tools/get_lead_details.py`, `register_interest.py`, `mark_not_interested.py`, `schedule_followup.py`.  
  **Deps:** T5.1, T5.2, T5.3. **AC:** handlers return spec-compliant JSON and enforce transitions.
- [x] **T5.5 (GREEN, S)** Add tool registry + dispatcher.  
  **Files:** `backend/app/tools/dispatcher.py`.  
  **Deps:** T5.4. **AC:** all four tools wired and reusable by webhook executor.

## Group 6 — Prompts: Jaumpablo System

- [x] **T6.1 (RED, S)** Write prompt rendering tests for variable injection, voseo, filler instructions, and tool rules.  
  **Files:** `backend/tests/unit/prompts/test_insurance_agent.py`.  
  **Deps:** T1.2, T2.3. **AC:** missing variables render safely; Quintana prompt selected.
- [x] **T6.2 (RED, S)** Write filler-selection tests for context grouping and repetition substitution.  
  **Files:** `backend/tests/unit/prompts/test_filler_policy.py`.  
  **Deps:** T3.4. **AC:** same filler never repeats consecutively.
- [x] **T6.3 (GREEN, M)** Implement Jaumpablo prompt template and rendering utilities.  
  **Files:** `backend/app/prompts/insurance_agent.py`.  
  **Deps:** T6.1, T6.2. **AC:** includes insurance flow, objections, dynamic filler guidance, and all template vars.

## Group 7 — API Wiring

- [x] **T7.1 (RED, S)** Write app wiring tests for router registration and health endpoint.  
  **Files:** `backend/tests/integration/test_app_wiring.py`.  
  **Deps:** T0.3. **AC:** `/health` passes and routers appear under `/api/v1`.
- [x] **T7.2 (GREEN, S)** Register all domain/voice/tool routers in app entrypoint.  
  **Files:** `backend/app/main.py`.  
  **Deps:** T1.3, T2.4, T3.5, T4.2, T4.5, T5.5. **AC:** startup seeds tenant/leads once and exposes complete API surface.

## Group 8 — TDD Completion Matrix

- [x] **T8.1 (RED, M)** Add scenario-matrix tests to guarantee at least 1 automated test per spec scenario (26+).  
  **Files:** extend `backend/tests/unit/**`, `backend/tests/integration/**`, add `backend/tests/test_spec_coverage.py` if needed.  
  **Deps:** prior RED tasks. **AC:** each CAP scenario maps to a named test.
- [ ] **T8.2 (GREEN, M)** Close gaps from matrix: multi-tenant isolation, fallback filler at 500ms, transcript exact-count, cross-tenant queries, prompt-driven tool intent confirmation.  
  **Files:** targeted test/impl files across tenants, leads, voice, prompts.  
  **Deps:** T8.1. **AC:** full spec acceptance summary passes in automated suite.
- [ ] **T8.3 (REFACTOR, S)** Consolidate fixtures/helpers and remove duplicated setup without reducing coverage.  
  **Files:** `backend/tests/conftest.py`, fixtures modules, shared builders.  
  **Deps:** T8.2. **AC:** test suite remains readable, deterministic, and maintainable.
