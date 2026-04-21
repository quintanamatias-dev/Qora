# Design: QORA Phase 2 — Memory and Persistence

## Technical Approach

Three sub-phases build on each other linearly: 2a closes sessions and persists user turns, 2b generates summaries/facts after close, 2c injects that memory at initiation. All async, all non-blocking to the voice stream.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| AD-1: Async post-processing | `asyncio.create_task` from close path | FastAPI `BackgroundTasks`, Celery | Project already uses `create_task` for cleanup (main.py L161). No new deps. Fire-and-forget fits — failure doesn't affect close response. |
| AD-2: Sweeper runtime | `asyncio` loop in lifespan (same as session_store_cleanup) | APScheduler, cron | Mirrors existing `_session_store_cleanup_task` pattern. Zero deps. 60s interval sufficient. |
| AD-3: Close endpoint location | `app/calls/router.py` under `/calls/{id}/end` | `voice/router.py` | Session close is a calls-domain concern, not voice. Existing calls router already has session CRUD. |
| AD-4: Summarizer model | `gpt-4o-mini` via `settings.openai_model_fast` | gpt-4o, local model | Already configured in Settings. ~$0.001/call. Single prompt does summary + fact extraction in one call. |
| AD-5: Fact storage | JSON columns on `CallSession` + `Lead` | Separate facts table, JSONB | SQLite uses TEXT for JSON (no native JSONB). `sa.JSON` auto-serializes. Keeps schema flat for MVP. Phase 3 can normalize. |
| AD-6: User turn source | `body.messages[-1]` where `role=="user"` | Full message diff | ElevenLabs sends cumulative messages. Last user message is always the new utterance. Scan from end to find it. |
| AD-7: Memory variable injection | Extend `_build_variables` in PromptLoader + `dynamic_variables` in initiation | Separate memory middleware | Both paths needed: `dynamic_variables` for ElevenLabs template vars, PromptLoader for custom-LLM system prompt. |
| AD-8: Migration strategy | `Base.metadata.create_all` (existing pattern) | Alembic | No Alembic in project. `create_all` is idempotent for ADD COLUMN on SQLite. New columns have defaults/nullable=True, so existing rows survive. |

## Data Flow

```
  ┌─────────────┐     SSE stream      ┌──────────────┐
  │ ElevenLabs  │ ──────────────────→  │  webhook.py  │
  │  WebSocket  │                      │  custom-llm  │
  └─────────────┘                      └──────┬───────┘
                                              │ fire-and-forget
                                              │ persist user turn (CAP-1)
                                              ▼
  ┌─────────────┐    POST /end         ┌──────────────┐
  │  Frontend   │ ──────────────────→  │  calls/      │
  │  (demo.js)  │                      │  router.py   │
  └─────────────┘                      └──────┬───────┘
                                              │ close session
                                              │ increment call_count
                                              │ create_task(summarize)
                                              ▼
  ┌─────────────┐   POST postcall      ┌──────────────┐
  │ ElevenLabs  │ ──────────────────→  │  calls/      │──→ summarizer.py
  │  Webhook    │                      │  router.py   │    (GPT-4o-mini)
  └─────────────┘                      └──────────────┘       │
                                                              │ merge facts
                                                              ▼
  ┌──────────────┐  GET initiation     ┌──────────────┐  ┌────────┐
  │ ElevenLabs   │ ──────────────────→ │ initiation.py│→ │Lead DB │
  │ pre-call     │ ◀── dynamic_vars ── │ + memory     │  │sessions│
  └──────────────┘                     └──────────────┘  └────────┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/calls/models.py` | Modify | Add `summary`, `closed_reason`, `total_user_turns`, `total_agent_turns`, `extracted_facts` to CallSession |
| `backend/app/leads/models.py` | Modify | Add `summary_last_call`, `objections_heard`, `interest_level`, `extracted_facts`, `do_not_call`, `next_action`, `next_action_at` to Lead |
| `backend/app/calls/router.py` | Modify | Add `POST /{conversation_id}/end` and `POST /elevenlabs-postcall` |
| `backend/app/calls/service.py` | Modify | Add `close_session()` (idempotent), `get_sessions_for_lead()`, `count_turns()` |
| `backend/app/calls/schemas.py` | Create | Pydantic request/response models for end + postcall endpoints |
| `backend/app/voice/webhook.py` | Modify | Add fire-and-forget user turn persistence before SSE stream |
| `backend/app/voice/initiation.py` | Modify | Load last 3 sessions, build memory variables, inject into response |
| `backend/app/summarizer.py` | Create | `generate_summary()` + `extract_facts()` — single GPT-4o-mini call, async |
| `backend/app/sweeper.py` | Create | `stale_session_sweeper()` — async loop, 60s interval, 10min threshold |
| `backend/app/main.py` | Modify | Start sweeper task alongside cleanup task in lifespan |
| `backend/app/prompts/loader.py` | Modify | Add memory variables to `_build_variables()` |
| `backend/clients/quintana-seguros/prompt.md` | Modify | Add `{{call_history}}` and `{{confirmed_facts}}` sections |

## Interfaces / Contracts

```python
# --- calls/schemas.py ---
class EndSessionRequest(BaseModel):
    reason: Literal["agent_goodbye", "user_hangup", "network_drop", "timeout", "reconnect_attempt"]

class EndSessionResponse(BaseModel):
    id: str
    status: str
    duration_seconds: float | None
    closed_reason: str

class ElevenLabsPostCallPayload(BaseModel):
    conversation_id: str
    agent_id: str | None = None
    transcript: list[dict] | None = None  # [{role, message}]
    metadata: dict | None = None
    model_config = {"extra": "allow"}

# --- summarizer.py ---
class ExtractedFacts(TypedDict, total=False):
    objections: list[str]
    interest_level: int  # 0-100
    current_insurance: str | None
    next_action_suggested: Literal["call_again", "send_quote", "wait", "do_not_call"]
    misc_facts: dict

async def generate_summary_and_facts(
    api_key: str,
    transcript: list[TranscriptTurn],
    model: str = "gpt-4o-mini",
) -> tuple[str, ExtractedFacts]:
    """Single GPT call returns (summary_text, extracted_facts). Max 150 tokens for summary."""

# --- Memory injection dynamic_variables addition ---
# Added to initiation response alongside existing vars:
{
    "call_history": "Llamada 1 (15/04): Lead mostró interés en cotización...",
    "confirmed_facts": "Seguro actual: La Caja. Objeciones: precio alto.",
    "is_returning_caller": "true",
    "call_number": "2",
    "_call_history_": "...",  # underscore-wrapped for EL template
    "_confirmed_facts_": "...",
    "_is_returning_caller_": "...",
    "_call_number_": "...",
}
```

## Sweeper Design

Async loop started in `lifespan()` next to existing cleanup task. Every 60s: query `CallSession` where `status="initiated" AND started_at < now() - 10min`. Mark as `status="abandoned"`, set `ended_at`. Do NOT increment `call_count`. Trigger summarizer only if `turn_count > 0`.

## Error Handling

- **GPT-4o-mini failure**: Caught in `generate_summary_and_facts`, logged via structlog, session remains `completed` without summary. No retry in Phase 2 (Phase 3 can add dead-letter queue).
- **Idempotent close**: `close_session()` checks `status`; if already `completed`, returns existing record without re-incrementing `call_count`. If `abandoned`, upgrades to `completed` (late close from postcall).
- **User turn persist failure**: Already wrapped in try/except in webhook.py (existing pattern). Non-blocking.
- **EL postcall with unknown conversation_id**: Return 404. Log warning.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `summarizer.py` — prompt construction, fact parsing | Mock `httpx` OpenAI call, assert JSON structure |
| Unit | `close_session` idempotency | In-memory SQLite, call twice, assert `call_count` increments once |
| Unit | `sweeper` — stale detection | Create sessions with past timestamps, run sweeper, assert status |
| Unit | Memory variable formatting | Assert `call_history` string format from mock sessions |
| Integration | `/calls/{id}/end` → summarizer triggered | `httpx.AsyncClient` + app, mock OpenAI, verify DB fields |
| Integration | `/calls/elevenlabs-postcall` → merge transcript | POST webhook, assert turns merged + summary regenerated |
| Integration | Initiation returns memory vars | Create prior sessions with summaries, call initiation, assert dynamic_variables |
| E2E (manual) | Full call lifecycle | Demo page → call → end → verify summary in DB → second call has memory |

## Migration Strategy

No Alembic in project. `Base.metadata.create_all` (called in `init_db`) handles new columns for SQLite — it issues `CREATE TABLE IF NOT EXISTS` which adds tables but does NOT add columns to existing tables. **For existing deployments**: add a one-time migration script (`scripts/migrate_phase2.py`) that runs `ALTER TABLE call_sessions ADD COLUMN ...` for each new field. For dev (fresh DB delete + recreate), `create_all` handles everything. Alembic introduction deferred to Phase 3.

## Open Questions

- [ ] ElevenLabs post-call webhook payload schema — need to verify exact fields from EL docs (agent_id, conversation_id, transcript format). Design assumes `{conversation_id, transcript: [{role, message}]}`.
- [ ] Should `do_not_call` block at initiation webhook level (return 403) or at dialer level? Spec says "call MUST NOT be initiated" — design places check in initiation webhook.
