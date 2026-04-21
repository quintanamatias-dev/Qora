# Design: qora-session-continuity

## Technical Approach

Two additive patches — (A) frontend sends `custom_llm_extra_body: { lead_id }` in the WS handshake and enriches `/end` body with `client_id` + `lead_id`, (B) backend stores `elevenlabs_conversation_id` at session creation and falls back to reconciliation when `/end` can't find the session by conversation ID. No new endpoints, no migrations. Maps directly to CAP-1..5 from the spec.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|----------------------|-----------|
| Propagate lead_id to backend | `custom_llm_extra_body` in WS handshake | New `/start` endpoint (Option C) | Additive, ~5 lines, EL already forwards the field as `elevenlabs_extra_body`. No race conditions. |
| Handle missing `elevenlabs_conversation_id` on `/end` | Reconciliation fallback in `close_session` | Server-side session_store lookup (Option D) | Heuristic is time-bounded (120s), tenant-isolated (`client_id` match), and null-safe. Option D breaks with concurrent calls. |
| Reconciliation window | Module-level constant `RECONCILIATION_WINDOW_SECONDS = 120` | Environment variable | Too simple for env config surface. Promote to env later if needed. |
| EL auto-inject `conversation_id`? | Design assumes NO (safer) | Assume yes | If EL does inject it, the `create_session` call stores it and reconciliation never triggers — bonus, not dependency. Code is null-safe either way. |
| Where reconciliation logic lives | Inside `close_session()` in `service.py` | In `router.py` | Service layer owns session lifecycle. Router stays thin (pass-through of hint params). |

## Data Flow

```
Frontend                    ElevenLabs WS              Backend (custom-LLM)
   |                             |                            |
   |-- ws.send({                 |                            |
   |     type: "conv_init",      |                            |
   |     dynamic_variables,      |                            |
   |     custom_llm_extra_body:  |                            |
   |       { lead_id } [NEW]     |                            |
   |   }) ---------------------->|                            |
   |                             |-- POST /custom-llm ------->|
   |                             |   elevenlabs_extra_body:    |
   |                             |     lead_id: "lead-42"     |
   |                             |     conversation_id: ?      |
   |                             |                            |
   |                             |                            |-- create_session(
   |                             |                            |     client_id, lead_id,
   |                             |                            |     elevenlabs_conversation_id [NEW]
   |                             |                            |   )
   |                             |                            |
   |<-- metadata_event ----------|                            |
   |   (conversation_id=abc123)  |                            |
   |   captured in JS var        |                            |
   |                             |                            |
   |-- POST /end/abc123 ---------------------------------------->|
   |   body: { reason,           |                            |
   |     client_id, lead_id }    |                            |
   |   [NEW fields]              |                            |
   |                             |                            |-- get_session_by_el_id("abc123")
   |                             |                            |   found? -> close_session (happy path)
   |                             |                            |   NOT found? -> reconcile:
   |                             |                            |     WHERE client_id=X, lead_id=Y,
   |                             |                            |     status='initiated',
   |                             |                            |     el_conv_id IS NULL,
   |                             |                            |     started_at >= now()-120s
   |                             |                            |     ORDER BY started_at DESC LIMIT 1
   |<-- 200 -----------------------------------------------------|
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/static/index.html` | Modify | Add `custom_llm_extra_body: { lead_id }` to WS handshake; extend `closeSessionOnBackend` body with `client_id`, `lead_id`; replace stale comment |
| `backend/app/voice/webhook.py` | Modify | Pass `elevenlabs_conversation_id=conversation_id` and ensure coerced `lead_id` reaches `create_session()`; add `lead_id` to `custom_llm_path_request` log |
| `backend/app/calls/service.py` | Modify | Add reconciliation fallback inside `close_session()` with `RECONCILIATION_WINDOW_SECONDS = 120` constant; new helper query |
| `backend/app/calls/schemas.py` | Modify | Add optional `client_id: str | None = None` and `lead_id: str | None = None` to `EndSessionRequest` |
| `backend/app/calls/router.py` | Modify | Pass `reconcile_client_id` and `reconcile_lead_id` from body to `close_session()` on the ValueError path |
| `backend/tests/unit/voice/test_custom_llm_path_route.py` | Modify | Extend with CAP-3 scenarios (session creation with conversation_id + lead_id populated) |
| `backend/tests/unit/calls/test_end_endpoint.py` | Modify | Extend with CAP-4 reconciliation scenarios |
| `backend/tests/integration/test_session_continuity_e2e.py` | Create | CAP-5 end-to-end memory cycle tests |

## Interfaces / Contracts

### Frontend — WebSocket handshake patch (~8 lines)

```javascript
// In ws.onopen, the ws.send payload adds:
...(leadId ? { custom_llm_extra_body: { lead_id: leadId } } : {})
```

### Frontend — closeSessionOnBackend patch (~3 lines)

```javascript
body: JSON.stringify({
  reason: reason,
  client_id: selectedClientId || undefined,
  lead_id: leadId || undefined,
})
```

### Backend — EndSessionRequest (schemas.py)

```python
class EndSessionRequest(BaseModel):
    reason: Literal[...]
    client_id: str | None = None   # NEW
    lead_id: str | None = None     # NEW
```

### Backend — close_session signature (service.py)

```python
async def close_session(
    session, *, session_id, closed_reason,
    update_lead_counters=True,
    reconcile_client_id: str | None = None,  # NEW
    reconcile_lead_id: str | None = None,    # NEW
) -> tuple[CallSession, bool]:
```

### Backend — webhook.py create_session call

```python
new_session = await create_session(
    db, client_id=client_id,
    lead_id=lead_id or None,
    elevenlabs_conversation_id=conversation_id or None,  # NEW
)
```

## Reconciliation Pseudo-Steps

```
1. /end receives { conversation_id (path), client_id, lead_id, reason }
2. get_session_by_elevenlabs_id(db, conversation_id) -> None
3. router catches ValueError from close_session
4. BEFORE raising 404, check: reconcile_client_id AND reconcile_lead_id present?
   -> No: raise HTTPException(404) as before (backward-compat)
   -> Yes: attempt reconciliation inside close_session()
5. Query: CallSession WHERE client_id=X AND lead_id=Y
   AND status='initiated' AND elevenlabs_conversation_id IS NULL
   AND started_at >= now() - 120s ORDER BY started_at DESC LIMIT 1
6. If match:
   - session.elevenlabs_conversation_id = conversation_id
   - session.status = 'completed'
   - session.closed_reason = reason
   - session.ended_at = now()
   - session.duration_seconds = (ended_at - started_at).total_seconds()
   - Increment Lead.call_count (first close -> always increment)
   - Log "end_session_reconciled" {reconciled_session_id, client_id, lead_id, conversation_id, age_seconds}
   - Return (session, False)
7. If no match: raise ValueError -> router returns 404
```

**Implementation note**: Reconciliation lives INSIDE `close_session()`, not in the router. When `session_id` lookup fails AND reconcile params are provided, `close_session` runs the fallback query before raising ValueError. This keeps the router thin.

## Concurrent Call Safety

- Two "initiated" sessions for same lead within 120s (rare, possible in testing): `ORDER BY started_at DESC LIMIT 1` picks the most recent.
- The earlier session eventually receives its own `/end` or is swept by the existing orphan cleaner.
- `client_id` match is strict — cross-tenant collision impossible.

## Testing Strategy

| Layer | What to Test | File | Approach |
|-------|-------------|------|----------|
| Unit | Session creation stores `elevenlabs_conversation_id` + `lead_id` | `test_custom_llm_path_route.py` | Mock DB, assert `create_session` kwargs |
| Unit | Reconciliation happy path, expired window, wrong tenant, status filter | `test_end_endpoint.py` | Pre-seed `CallSession` rows, assert reconciliation matches/rejects |
| Unit | `EndSessionRequest` accepts optional fields + backward-compat | `test_end_endpoint.py` | Parse payloads with/without new fields |
| Integration | Full cycle: call 1 -> /end -> summary -> call 2 loads memory | `test_session_continuity_e2e.py` (NEW) | In-memory SQLite, mock OpenAI |
| Frontend | Not testable (no E2E framework). Limitation documented. | N/A | Validate backend contract via `test_initiation.py` response shape |

## Logging Contract

| Event | Fields | Notes |
|-------|--------|-------|
| `custom_llm_path_request` | + `lead_id` (NEW) | Currently logs `client_id` only |
| `end_session_reconciled` (NEW) | `reconciled_session_id`, `client_id`, `lead_id`, `conversation_id`, `age_seconds` | Emitted on successful reconciliation |
| `end_session_unknown_id` | unchanged | Fires when reconciliation ALSO fails |

## Migration & Backward Compatibility

- **No DB migration needed.** `elevenlabs_conversation_id` column already exists and is nullable.
- Existing `CallSession` rows with NULL `elevenlabs_conversation_id` stay as-is (sweeper closes them eventually).
- `EndSessionRequest` new fields default to `None` — legacy callers without them get the pre-existing 404 behavior (no reconciliation attempted).
- The ElevenLabs post-call webhook uses a different endpoint (`/elevenlabs-postcall`) with `ElevenLabsPostCallPayload` schema — completely unaffected.

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| EL doesn't auto-inject `conversation_id` in `elevenlabs_extra_body` | Medium | Reconciliation fallback handles this. Frontend captures `conversation_id` from metadata event independently. |
| Concurrent calls for same lead within 120s | Low | `ORDER BY started_at DESC LIMIT 1` picks latest; earlier session reconciled separately |
| Race between custom-LLM webhook and `/end` | None | Custom-LLM fires BEFORE `/end` by definition (session must exist before close) |
| Cross-tenant session steal via reconciliation | None | `client_id` match is strict in reconciliation query |
| Double `Lead.call_count` increment on reconciled session | Low | Existing idempotency (`status == 'completed'` check) prevents double increment on second `/end` call |

## Open Questions

- [x] EL auto-inject conversation_id? -> Design assumes NO (null-safe)
- [x] Reconciliation window configurable? -> Constant (120s), promote to env if needed
- [x] EndSessionRequest backward compat? -> Optional fields, legacy callers unaffected
- [x] Lead.call_count idempotency on double /end? -> Existing check covers it

No remaining open questions.
