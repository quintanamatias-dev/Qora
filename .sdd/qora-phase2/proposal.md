# Proposal: QORA Phase 2 — Memory and Persistence

## Intent

Phase 1 gave QORA multi-tenancy. Phase 2 closes the conversation lifecycle loop and adds cross-call memory: QORA must know who it spoke to before, what was discussed, and start the next call with that context. Today, sessions are never properly closed, user turns are discarded, and every call starts cold.

## Scope

### In Scope

**Phase 2a — Close the Loop**
- Persist user turns to DB after each SSE response (currently only agent turns saved)
- Implement `POST /calls/{id}/end` to properly close `CallSession` (status → `completed`, timestamps set)
- ElevenLabs post-call webhook (`POST /api/v1/voice/post-call`) — receives call metadata when EL closes the call; secondary source of truth
- Background sweeper: cron that closes sessions stuck as `initiated` > 10 min
- Fix `call_count` increment: move from `get_lead_details` tool → session close path

**Phase 2b — Memory Generation**
- Post-call summary generation with GPT-4o-mini (called from close path + post-call webhook)
- Store summary in `CallSession.summary` (existing column or add it)
- Extract and upsert structured facts (`insurance_carrier`, `best_time`, `objection`, etc.) into `leads.facts` JSON column

**Phase 2c — Memory Injection**
- Load last N sessions with summaries on initiation webhook
- Inject memory as `dynamic_variables` into ElevenLabs prompt (e.g., `{{last_call_summary}}`, `{{lead_facts}}`)
- Update `quintana-seguros/prompt.md` to use memory variables

### Out of Scope
- Multi-session memory search / vector retrieval (Phase 3)
- Analytics dashboard / call history UI (Phase 3)
- Sentiment scoring or structured call evaluation (Phase 3)
- Real-time mid-call context updates
- Per-client summary prompt customization

## Capabilities

### New Capabilities
- `call-session-close`: `/calls/{id}/end` endpoint + sweeper that properly terminates sessions and triggers post-processing
- `user-turn-persistence`: SSE response handler persists user turns to `ConversationTurn` table
- `elevenlabs-post-call-webhook`: `/api/v1/voice/post-call` receives EL webhook, closes session if still open
- `call-summary-generation`: GPT-4o-mini post-call summary stored in `CallSession.summary`
- `lead-facts-extraction`: Structured fact extraction from conversation stored in `leads.facts` JSON column
- `memory-injection`: Initiation webhook loads prior summaries + facts and injects as `dynamic_variables`

### Modified Capabilities
- `call-count-tracking` (CAP in Phase 0/1): Move increment from `get_lead_details` tool → session close; wire to `Lead.call_count`

## Approach

### Decision 1: ElevenLabs Post-Call Webhook as Secondary Close Trigger
ElevenLabs fires a post-call webhook with transcript and metadata when the conversation ends on their side. We implement it as a **secondary trigger** (not primary) — our `end` endpoint is primary. The webhook catches calls where the frontend didn't call `/end` (e.g., page refresh, crash). Idempotent: if session already `completed`, webhook is a no-op.

### Decision 2: GPT-4o-mini for Summaries
Cost ~$0.001/call. Sufficient for 3–5 sentence summary + JSON fact extraction in a single prompt call. Called async after session close — never blocks the call itself.

### Decision 3: JSON Facts Column in `leads` Table
No separate facts table. `leads.facts JSONB` (or JSON) stores a dict of extracted fields. Upserted on each call — new facts merge into existing ones. Keeps the schema simple; Phase 3 can normalize if needed.

### Decision 4: Memory Injected via `dynamic_variables`
ElevenLabs `dynamic_variables` are the correct hook. Injected at initiation time from `render_system_prompt()`. Fields: `{{last_call_summary}}`, `{{lead_facts_summary}}`, `{{call_count}}`. Defaults to empty string if no history — prompt must handle gracefully.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/voice/webhook.py` | Modified | Persist user turns; trigger summary on close |
| `backend/app/voice/initiation.py` | Modified | Load last N sessions; inject memory as dynamic_variables |
| `backend/app/voice/router.py` | Modified | Add `POST /calls/{id}/end` and `POST /voice/post-call` routes |
| `backend/app/models.py` | Modified | Add `CallSession.summary`, `Lead.facts` JSON column |
| `backend/app/summarizer.py` | New | GPT-4o-mini summary + fact extraction logic |
| `backend/app/sweeper.py` | New | Background task to close stale sessions |
| `backend/clients/quintana-seguros/prompt.md` | Modified | Add memory variable placeholders |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| GPT-4o-mini summary call fails / times out | Low | Async with retry (×2); failure logged but doesn't break call close |
| EL post-call webhook arrives before `/end` is called | Low | Idempotent close; last writer wins on status |
| `facts` JSON upsert corrupts existing facts | Med | Merge strategy: only overwrite non-null extracted fields |
| Memory injection makes prompt too long | Low | Cap `last_call_summary` to 300 chars; truncate older summaries |

## Rollback Plan

- Phase 2a: `end` endpoint is additive — removing it reverts to stuck sessions (same as today, not worse)
- Phase 2b: Summarizer is async and isolated — disable by removing the post-close call; no data corruption
- Phase 2c: Memory injection uses template variables — if `{{last_call_summary}}` is absent from prompt.md, nothing is injected; zero impact on call behavior

## Dependencies

- Phase 1 complete (multi-tenancy, per-client prompts) ✅
- `CallSession` and `ConversationTurn` models exist ✅
- ElevenLabs post-call webhook: must be configured in EL dashboard to point to `POST /api/v1/voice/post-call`
- OpenAI API key for GPT-4o-mini (already used for LLM webhook)

## Success Criteria

- [ ] After a call ends, `CallSession.status = "completed"` within 30 seconds via any close path
- [ ] Both user and agent turns are stored in `ConversationTurn` for every call
- [ ] `Lead.call_count` increments exactly once per completed session
- [ ] `CallSession.summary` is populated within 60 seconds of session close
- [ ] `Lead.facts` contains at least one extracted field after a qualifying call
- [ ] A second call to Carlos Méndez starts with context: *"Te llamo de vuelta, la última vez me dijiste que tenés La Caja..."*
- [ ] Sessions stuck > 10 min as `initiated` are swept to `completed` automatically
