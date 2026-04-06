# Tasks: QORA Cleanup & Documentation

## Group 1: Dead Code Removal

- [x] 1.1 Delete `backend/agents/configs/sales-agent-01.json`; deliverable: file absent from repo.
- [x] 1.2 Delete `backend/callcenter.db` if present; deliverable: only `backend/qora.db` remains.
- [x] 1.3 Delete `backend/test_output/`; deliverable: no generated MP3 artifacts remain.
- [x] 1.4 Delete `backend/fallback_audio/`; deliverable: empty V1 placeholder removed.
- [x] 1.5 Remove `POST /voice/debug-llm` and `/voice/debug-llm/chat/completions` from `backend/app/voice/webhook.py`; deliverable: endpoint returns 404 after cleanup.
- [x] 1.6 Move inline `import structlog as _sl` and `import uuid as _uuid` to module-level imports in `backend/app/voice/webhook.py`; deliverable: no function-scope imports remain.

## Group 2: Agent Config Unification (TDD)

- [x] 2.1 [RED] Add/extend webhook integration tests in `backend/tests/integration/voice/test_custom_llm.py` to assert `render_system_prompt(client, lead)` is called when no override exists.
- [x] 2.2 [GREEN] In `backend/app/voice/webhook.py`, remove `_build_default_system_prompt`, import `render_system_prompt` from `backend/app/prompts/insurance_agent.py`, and make the new test pass.
- [x] 2.3 [RED] Run/focus the 3 known failing tests in `backend/tests/integration/voice/test_custom_llm.py` and `backend/tests/test_spec_coverage.py`; keep failures proving missing `client_id` must raise 422/`ValidationError`.
- [x] 2.4 [GREEN] Update `ElevenLabsExtraBody` in `backend/app/voice/webhook.py` so `client_id` is required and remove the `or "quintana-seguros"` fallback; deliverable: the 3 targeted tests pass.
- [x] 2.5 [REFACTOR] Update `backend/app/core/seed_data.py` (or the active Quintana seed module) so `quintana-seguros` includes `elevenlabs_agent_id`; deliverable: seeded client data stays aligned with runtime expectations.

## Group 3: WebSocket 1006 Handling (UI)

- [x] 3.1 Update `ws.onclose` in `backend/app/static/index.html` to map `1000` to "Conversación finalizada" and `1006`/other codes to "Se perdió la conexión" with error state.
- [x] 3.2 Add a "Reconectar" button in `backend/app/static/index.html` that reuses the last `agentId` and `leadId`, calls `startConversation()`, and removes itself after click.

## Group 4: Documentation

- [x] 4.1 Rewrite `backend/README.md` to describe QORA, current architecture, and stack; remove Twilio/V1 references.
- [x] 4.2 Create `docs/architecture.md` with an ASCII/system diagram plus component and data-flow descriptions.
- [x] 4.3 Create `docs/running-locally.md` with env var names, local startup steps, and ngrok exposure steps.

## Group 5: Verification

- [x] 5.1 Run `pytest backend/tests/`; deliverable: all tests pass and total count is at least 183.
- [x] 5.2 Execute a manual checklist covering prompt rendering, debug endpoint 404, WS `1000` clean end, WS `1006` reconnect flow, and end-to-end demo success.
