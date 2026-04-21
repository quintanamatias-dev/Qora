# Tasks: QORA Phase 2 — Memory and Persistence

## Batch Plan
- **Batch 1 (Foundation + Phase 2a):** T01-T07
- **Batch 2 (Phase 2b):** T08-T10
- **Batch 3 (Phase 2c):** T11-T12

## Foundation
- [x] **T01** [CAP-5] Files: `backend/app/calls/models.py`, `backend/app/calls/service.py`
  - Add `CallSession` fields: `summary`, `closed_reason`, turn totals, `extracted_facts`.
  - Add typed helpers for turn counting and lead session lookup.

- [x] **T02** [CAP-5] Files: `backend/app/leads/models.py`, `scripts/migrate_phase2.py`
  - Add new `Lead` memory fields with `do_not_call=False` default.
  - Migration script adds missing columns idempotently for existing SQLite DBs.

## Phase 2a — Close the Loop
- [x] **T03** [CAP-1] Files: `backend/app/voice/webhook.py`, `backend/app/calls/service.py`
  - Persist the latest user utterance from `body.messages` with fire-and-forget async handling.
  - Empty/missing user messages skip cleanly without delaying SSE.

- [x] **T04** [CAP-2a, CAP-5] Files: `backend/app/calls/schemas.py`, `backend/app/calls/router.py`, `backend/app/calls/service.py`
  - Add `POST /api/v1/calls/{conversation_id}/end` request/response models and handler.
  - Close is idempotent, sets lifecycle fields, and increments lead counters once.

- [x] **T05** [CAP-3] Files: `backend/app/static/index.html`
  - On WS close, call `/end` with `user_hangup` for code `1000`, else `network_drop`.
  - Show reconnect UI only for non-1000 closes; reconnect closes old session with `reconnect_attempt` before starting a new one.
  - ✅ Complete — frontend reconnect implemented in `index.html` (Batch 4).

- [x] **T06** [CAP-2b] Files: `backend/app/calls/schemas.py`, `backend/app/calls/router.py`, `backend/app/calls/service.py`
  - Add `POST /api/v1/calls/elevenlabs-postcall` payload parsing and unknown-session handling.
  - Close initiated sessions or merge extra transcript turns when ElevenLabs has more data.

- [x] **T07** [CAP-2c] Files: `backend/app/sweeper.py`, `backend/app/main.py`, `backend/app/calls/service.py`
  - Run a 60s async sweeper for initiated sessions older than 10 minutes.
  - Mark stale sessions `abandoned`, set `ended_at`, and never increment `Lead.call_count`.

## Phase 2b — Memory Generation
- [x] **T08** [CAP-4] Files: `backend/app/summarizer.py`
  - Implement one GPT-4o-mini call that returns a <=150-token summary plus structured facts.
  - Failures are logged and never break close flows.

- [x] **T09** [CAP-4] Files: `backend/app/calls/router.py`, `backend/app/calls/service.py`, `backend/app/sweeper.py`
  - Trigger summarization asynchronously from `/end`, post-call webhook, and sweeper.
  - Skip GPT work for zero-turn abandoned sessions.

- [x] **T10** [CAP-4, CAP-5] Files: `backend/app/summarizer.py`, `backend/app/calls/service.py`
  - Persist `CallSession.summary`/`extracted_facts` and merge into `Lead` with objection union and latest values.
  - Set `Lead.do_not_call=True` when `next_action_suggested` is `do_not_call`.

## Phase 2c — Memory Injection
- [x] **T11** [CAP-6] Files: `backend/app/voice/initiation.py`, `backend/app/prompts/loader.py`, `backend/app/calls/service.py`
  - Load the last 3 completed sessions and build `call_history`, `confirmed_facts`, `is_returning_caller`, `call_number`.
  - Fallbacks are empty strings/first-call defaults when no history exists.

- [x] **T12** [CAP-6] Files: `backend/app/voice/initiation.py`, `backend/clients/quintana-seguros/prompt.md`
  - Inject memory variables into initiation payload/template usage.
  - Block initiation for `do_not_call` leads with a clear non-success status.
