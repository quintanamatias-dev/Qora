# Exploration: Session Continuity via custom_llm_extra_body

## Problem Statement

Every ElevenLabs call currently creates a `CallSession` with `lead_id=NULL` and
`elevenlabs_conversation_id=NULL`. This happens because the frontend WebSocket
initiation message deliberately omits `custom_llm_extra_body` — the field that
ElevenLabs forwards to the custom-LLM backend as `elevenlabs_extra_body`. Without
it, the backend never receives `lead_id`, and no downstream behavior that depends
on knowing *which lead* is on the call can fire.

The consequences cascade through five Phase 2 features that are already implemented
but silently broken: (1) memory injection returns empty history because no prior
sessions match `lead_id=NULL`, (2) the `/end` endpoint returns 404 because it
looks up `CallSession` by `elevenlabs_conversation_id` which was never stored,
(3) post-call summary never runs because it triggers on `/end` success, (4) fact
extraction never runs because it triggers on summarizer completion, and (5) lead
call counters never increment because `close_session` skips the update when
`lead_id` is NULL.

## Root Cause Evidence

### The stale comment (frontend)

**File**: `backend/app/static/index.html`, lines 397-421

```javascript
// NOTE: do NOT include custom_llm_extra_body — ElevenLabs rejects it (1008) unless
// the agent has that feature explicitly enabled in the dashboard.
ws.send(JSON.stringify({
  type: 'conversation_initiation_client_data',
  dynamic_variables: { ... }
  // ← custom_llm_extra_body is MISSING
}));
```

This comment is **wrong**. It was valid during an earlier ElevenLabs API version
but is no longer accurate.

### ElevenLabs official documentation (confirmed)

- [Custom LLM docs](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm.mdx) — `custom_llm_extra_body` is documented as a first-class field in `conversation_initiation_client_data`.
- [WebSocket API reference](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket) — confirms `custom_llm_extra_body` is forwarded as `elevenlabs_extra_body` on every subsequent custom-LLM HTTP request. No dashboard toggle required.

### The backend already expects it

**File**: `backend/app/voice/webhook.py`, lines 504-510

```python
extra = body.elevenlabs_extra_body
lead_id = extra.lead_id or body.lead_id or (body.model_extra or {}).get("lead_id")
conversation_id = (
    extra.conversation_id
    or body.conversation_id
    or (body.model_extra or {}).get("conversation_id")
)
```

The backend reads `elevenlabs_extra_body.lead_id` and `.conversation_id` correctly.
They just always arrive as `None` because the frontend never sends them.

### Missing `elevenlabs_conversation_id` on create

**File**: `backend/app/voice/webhook.py`, lines 600-607

```python
new_session = await create_session(
    db,
    client_id=client_id,
    lead_id=lead_id or None,
    # ← elevenlabs_conversation_id is NOT passed
)
```

Even when `conversation_id` is available in scope (line 506-510), it is never
passed to `create_session`. This means `CallSession.elevenlabs_conversation_id`
stays NULL even if EL starts sending it.

## Flow Diagrams

### Current (broken) flow

```
Frontend                    ElevenLabs WS              Backend (custom-LLM)
   │                            │                            │
   │── ws.send({               │                            │
   │     type: "conv_init",    │                            │
   │     dynamic_variables,    │                            │
   │     ❌ NO custom_llm_     │                            │
   │        extra_body         │                            │
   │   }) ─────────────────────▶                            │
   │                            │── POST /custom-llm ──────▶│
   │                            │   elevenlabs_extra_body:  │
   │                            │     client_id: null ❌     │
   │                            │     lead_id: null ❌       │
   │                            │     conversation_id: null ❌│
   │                            │                            │
   │                            │                            │── create_session(
   │                            │                            │     client_id=from_path ✅
   │                            │                            │     lead_id=null ❌
   │                            │                            │     el_conv_id=not_passed ❌
   │                            │                            │   )
   │                            │                            │
   │◀─ conv_init_metadata ─────│                            │
   │   (conversation_id=abc123)│                            │
   │   captured too late ❌     │                            │
   │                            │                            │
   │── /end/abc123 ────────────────────────────────────────▶│
   │                            │                            │── get_session_by_el_id("abc123")
   │                            │                            │   → NULL (never stored) ❌
   │◀─ 404 ────────────────────────────────────────────────│
```

### Proposed (fixed) flow — Option A + B

```
Frontend                    ElevenLabs WS              Backend (custom-LLM)
   │                            │                            │
   │── ws.send({               │                            │
   │     type: "conv_init",    │                            │
   │     dynamic_variables,    │                            │
   │     custom_llm_extra_body:│                            │
   │       { lead_id } ✅      │                            │
   │   }) ─────────────────────▶                            │
   │                            │── POST /custom-llm ──────▶│
   │                            │   elevenlabs_extra_body:  │
   │                            │     client_id: null ¹      │
   │                            │     lead_id: "lead-42" ✅  │
   │                            │     conversation_id: ? ²   │
   │                            │                            │
   │                            │                            │── create_session(
   │                            │                            │     client_id=from_path ✅
   │                            │                            │     lead_id="lead-42" ✅
   │                            │                            │     el_conv_id=conv_id ³
   │                            │                            │   )
   │                            │                            │
   │── /end/abc123 ────────────────────────────────────────▶│
   │                            │                            │── get_session_by_el_id("abc123")
   │                            │                            │   → found via reconciliation ✅
   │◀─ 200 ────────────────────────────────────────────────│
   │                            │                            │── close_session → summary → facts
```

**Notes**:
1. `client_id` is NOT sent in `custom_llm_extra_body` — already in URL path per `qora-tenant-resolution`. Sending it redundantly would trigger `client_id_mismatch` warning on every request.
2. ElevenLabs MAY forward `conversation_id` inside `elevenlabs_extra_body` (docs suggest it does). Needs verification during implementation.
3. If EL doesn't forward `conversation_id` in `elevenlabs_extra_body`, Option B reconciles it at `/end` time.

## Options Evaluated

| # | Approach | Effort | Coverage (bugs fixed) | Risk | Verdict |
|---|----------|--------|-----------------------|------|---------|
| A | Frontend sends `custom_llm_extra_body: { lead_id }` | ~5 lines frontend | #1, #3, #4, #5 (lead-dependent) | None — additive, backend already reads the field | **Adopt** |
| B | `/end` reconciliation: match `(client_id, lead_id, recent)` when `elevenlabs_conversation_id` not found | ~20 lines backend | #2 (`/end` 404s) | Low — time-window heuristic; mitigated by also storing `conversation_id` when available | **Adopt** |
| C | New `/api/v1/calls/start` endpoint: frontend POSTs after capturing `conversation_id` from metadata event | ~50 lines (new endpoint + frontend coordination) | #1, #2, #5 | Medium — race condition: custom-LLM may fire before `/start` completes | **Reject** (overkill) |
| D | Server-side session_store reconciliation: lookup by `(client_id, lead_id)` when `conversation_id` missing | ~15 lines backend | #1 partial | High — breaks with concurrent calls for same lead; implicit coupling | **Reject** (fragile) |

## Recommendation: A + B Combined

**Option A** fixes the root cause — `lead_id` propagation. With `lead_id` flowing
through `elevenlabs_extra_body`, the backend can:
- Store `lead_id` on `CallSession` → memory injection finds prior sessions (bug #1)
- `close_session` updates `Lead.call_count` and `last_called_at` (bug #5)
- Summary runs → fact extraction runs (bugs #3, #4)

**Option B** fills the remaining gap — `elevenlabs_conversation_id`. The `/end`
endpoint currently does `get_session_by_elevenlabs_id(conversation_id)` which
returns NULL because the conversation_id was never stored on the `CallSession`.
Two sub-fixes:

1. **Store conversation_id at creation time**: Pass the EL-provided `conversation_id`
   to `create_session()` in `_process_custom_llm_request` (it's already in scope
   at line 506-510 but not passed through).
2. **Reconciliation fallback**: If `/end` receives a `conversation_id` that doesn't
   match any `elevenlabs_conversation_id` in DB, look for the most recent
   `initiated` session with matching `(client_id)` created in the last 60 seconds
   and assign the `conversation_id` to it retroactively.

Combined, A + B close all 5 bugs with minimal code changes (~25 lines total),
no new endpoints, no race conditions, and purely additive modifications.

**Rejected**: Option C adds unnecessary complexity (new endpoint + frontend
orchestration + timing dependency). Option D is fragile with concurrent calls.

## Key Unknowns (for design phase)

1. **Does EL forward `conversation_id` inside `elevenlabs_extra_body`?**
   Docs suggest `custom_llm_extra_body` fields are forwarded verbatim, but
   `conversation_id` might be auto-injected by EL separately (as a top-level
   field). If EL auto-injects it, we might not need to send it from the frontend
   at all. Verify empirically during implementation.

2. **Reconciliation time window**: The Option B fallback uses a "most recent
   initiated session in last N seconds" heuristic. What value for N? 60 seconds
   is conservative; design phase should decide based on typical EL call setup
   latency.

3. **`create_session` missing `elevenlabs_conversation_id` param**: The call at
   webhook.py:603 already has `conversation_id` in scope but doesn't pass it.
   Should this be fixed alongside Option A, or is it a separate concern? (Likely
   fix it — it's one extra keyword arg.)

## Relationship to Prior Changes

### Complements: `qora-tenant-resolution` (archived 2026-04-18)

That change solved `client_id` resolution by putting it in the URL path
(`/api/v1/voice/{client_id}/custom-llm/chat/completions`). The `client_id` problem
is SOLVED. This change addresses the **other** fields (`lead_id`,
`elevenlabs_conversation_id`) that still arrive as NULL.

**Important constraint**: Do NOT send `client_id` in `custom_llm_extra_body`.
It's already in the URL path. Sending it redundantly would trigger the
`client_id_mismatch` warning log on every single request (webhook.py:451-456).

### Unblocks: `qora-phase2` (spec exists at `.sdd/qora-phase2/spec.md`)

Phase 2 features (CAP-1 through CAP-6) are **already implemented** in code:
- `initiation.py`: CAP-6 memory injection (lines 214-227) — works, but
  `get_sessions_for_lead()` returns empty because `lead_id` is always NULL.
- `calls/service.py`: `close_session` triggers `_schedule_summarize` (line 288) —
  works, but never fires because `/end` returns 404.
- `calls/service.py`: Lead counter update (lines 276-281) — works, but skipped
  when `lead_id` is NULL.

This one change unblocks the entire Phase 2 pipeline without touching any of
the already-implemented business logic.

## Affected Areas

- `backend/app/static/index.html` (lines 397-421) — add `custom_llm_extra_body`
- `backend/app/voice/webhook.py` (line 603) — pass `elevenlabs_conversation_id`
- `backend/app/calls/router.py` (lines 114-147) — add reconciliation fallback
- `backend/app/calls/service.py` — possibly add `reconcile_conversation_id` helper

## Ready for Proposal

**Yes**. Root cause is confirmed, solution is clear (A + B), effort is low (~25
lines), risk is minimal, and the approach is purely additive. Proceed to
`sdd-propose`.
