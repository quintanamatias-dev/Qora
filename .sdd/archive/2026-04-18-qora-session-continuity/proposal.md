# Proposal: qora-session-continuity

## Intent

The frontend omits `custom_llm_extra_body` from the ElevenLabs WebSocket handshake due to a stale incorrect comment, causing every `CallSession` to be created with `lead_id=NULL` and `elevenlabs_conversation_id=NULL`. This silently disables all five Phase 2 features (memory injection, post-call summaries, fact extraction, call counters, `/end` resolution) despite the backend logic being fully implemented and tested. The fix is additive: send `custom_llm_extra_body: { lead_id }` from the frontend, pass `conversation_id` to `create_session()` in the webhook, and add a reconciliation fallback in `/end` for the case where `elevenlabs_conversation_id` is still NULL.

## Scope

### In Scope
- Frontend: add `custom_llm_extra_body: { lead_id }` to `conversation_initiation_client_data` WebSocket message
- Frontend: capture `conversation_id` from `conversation_initiation_metadata_event`; include it in `/end` POST body alongside `client_id` and `lead_id`
- Backend `webhook.py`: pass `conversation_id` to `create_session()` when it is available in scope (it already is — just not forwarded)
- Backend `calls/service.py`: `close_session()` accepts optional reconciliation hint `{client_id, lead_id}`; fallback to most-recent `initiated` session matching `(client_id, lead_id)` created within ~120s when `elevenlabs_conversation_id` not found
- Backend `calls/schemas.py`: `EndSessionRequest` adds optional `client_id`, `lead_id` fields (backward-compatible)
- Backend `calls/router.py`: `/end` endpoint reads hint fields and passes them to `close_session()`
- Tests: (1) frontend payload shape, (2) `CallSession` creation populates `elevenlabs_conversation_id`, (3) `/end` reconciliation happy path, (4) reconciliation does not steal another tenant's session, (5) end-to-end: create session → `/end` → summary fires
- Remove stale comment in `index.html` and replace with citation to EL docs
- Update `docs/elevenlabs-setup.md` with the `custom_llm_extra_body` pattern

### Out of Scope
- Removing the legacy custom-LLM route
- Changing the initiation webhook shape
- Multi-agent per-client routing
- Phase 3 memory features (embedding-based retrieval, per-tenant summary prompts)
- Sending `client_id` in `custom_llm_extra_body` (already solved via URL path in `qora-tenant-resolution`)

## Capabilities

### New Capabilities
- `session-continuity`: the system maintains a fully-linked `CallSession` record from WebSocket handshake → custom-LLM invocations → `/end` → post-call summary, linked via `elevenlabs_conversation_id` + `lead_id`

### Modified Capabilities
- `tenant-routing` (from `qora-tenant-resolution`): extend to also read `lead_id` from `elevenlabs_extra_body` on path-based requests (it already does — this change ensures the field is non-NULL at last)
- `call-session-close` (CAP-2a from `qora-phase2`): add reconciliation fallback for sessions where `elevenlabs_conversation_id` is NULL at `/end` time

## Approach

**Option A + B combined** (from exploration):

1. **Frontend (Option A)**: Add `custom_llm_extra_body: { lead_id }` to the `conversation_initiation_client_data` message and capture `conversation_id` from the `conversation_initiation_metadata_event` to pass to `/end`. Removes root cause. ~5 lines.

2. **Backend create fix**: In `_process_custom_llm_request`, forward the `conversation_id` already in scope to `create_session()`. 1 keyword arg.

3. **Reconciliation fallback (Option B)**: In `close_session()`, if no session is found by `elevenlabs_conversation_id`, look for the most-recent `initiated` session with matching `(client_id, lead_id)` started within a configurable window (default 120s), assign the `conversation_id` to it, and proceed. ~20 lines.

No new endpoints. No migrations. Purely additive. Total diff: ~30 lines.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/static/index.html` | Modified | Remove stale comment; add `custom_llm_extra_body`; capture and forward `conversation_id` |
| `backend/app/voice/webhook.py` | Modified | Pass `conversation_id` to `create_session()` at line 603 |
| `backend/app/calls/service.py` | Modified | `close_session()` + reconciliation fallback helper |
| `backend/app/calls/schemas.py` | Modified | Optional `client_id`, `lead_id` on `EndSessionRequest` |
| `backend/app/calls/router.py` | Modified | `/end` passes hint fields to `close_session()` |
| `backend/tests/integration/voice/` | New | End-to-end flow + reconciliation scenarios |
| `backend/tests/unit/calls/` | New | Reconciliation fallback unit tests |
| `docs/elevenlabs-setup.md` | Modified | Document `custom_llm_extra_body` pattern |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| EL does not forward `conversation_id` in `elevenlabs_extra_body` | Med | Reconciliation fallback in Option B doesn't depend on it; `/end` receives `conversation_id` directly from frontend |
| Two calls for same lead within reconciliation window swap sessions | Low | Short window (~120s), order by `started_at DESC`, match only sessions with NULL `elevenlabs_conversation_id` |
| Existing tests break (missing `client_id`/`lead_id` in `/end` body) | Low | New fields are optional; no existing payload changes |

## Rollback Plan

- **Frontend**: revert `custom_llm_extra_body` addition and `conversation_id` capture (~2 lines each)
- **Backend**: reconciliation fallback is null-safe; reverting the `close_session()` change restores original lookup behavior with no DB migration needed
- No schema migrations in this change

## Dependencies

- `qora-tenant-resolution` (archived 2026-04-18) — `client_id` path resolution must be in place (it is)
- ElevenLabs agent configured with a custom-LLM URL pointing to the path-based endpoint

## Success Criteria

- [ ] `CallSession.lead_id` is non-NULL for every call initiated with a valid lead
- [ ] `CallSession.elevenlabs_conversation_id` is non-NULL after session creation or reconciliation
- [ ] `POST /api/v1/calls/{conversation_id}/end` returns 200 (not 404) for all normal call flows
- [ ] Post-call summary and fact extraction fire after a clean call end
- [ ] `Lead.call_count` increments correctly after each completed call
- [ ] Reconciliation does not assign a session belonging to tenant A to a request from tenant B
