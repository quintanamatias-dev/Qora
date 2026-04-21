# Exploration: Memory Variables Populated at Custom-LLM Render Time

## Problem Statement

The Qora voice agent never remembers prior conversations with a lead, even though
the system prompt template (`prompt.md`) includes memory placeholders (`{{call_history}}`,
`{{confirmed_facts}}`, `{{is_returning_caller}}`, `{{call_number}}`). These placeholders
were designed to be populated via ElevenLabs `dynamic_variables` at initiation time
(CAP-6, qora-phase2). The initiation webhook (`/voice/initiation`) correctly loads the
last 3 completed sessions, formats call history, and builds confirmed facts from
`Lead.extracted_facts` — but this webhook is only fired by ElevenLabs on Twilio/SIP
inbound paths, **not** on the WebSocket-direct flow used by the browser demo.

In the WebSocket-direct flow, ElevenLabs calls the custom-LLM webhook (`/voice/webhook`)
directly, which renders the prompt via `PromptLoader.render()`. Inside
`_build_variables()` (loader.py:209-226), the four CAP-6 memory variables are hardcoded
to empty strings / `"false"` / `"1"`. The comment at line 181-183 explicitly says:
_"populated via ElevenLabs dynamic_variables at initiation time; here they resolve as
empty strings so the template renders cleanly in the custom-LLM webhook path."_ This is
the root cause: the only code path that fires (custom-LLM) renders without memory.

## Current vs Proposed Flow (ASCII)

```
CURRENT (broken) — WebSocket-direct from browser
─────────────────────────────────────────────────
Browser ──WS──► ElevenLabs ──POST /voice/webhook──► Backend
                                                    │
                                           PromptLoader.render()
                                           _build_variables():
                                             call_history = ""        ← EMPTY
                                             confirmed_facts = ""     ← EMPTY
                                             is_returning_caller = "false"
                                             call_number = "1"        ← WRONG
                                                    │
                                           Template rendered without memory
                                           Agent has no context ✗

PROPOSED (fixed) — same path, memory injected at render
───────────────────────────────────────────────────────
Browser ──WS──► ElevenLabs ──POST /voice/webhook──► Backend
                                                    │
                                           PromptLoader.render(client, lead, db)
                                           _build_variables():
                                             ┌── build_memory_for_lead(db, lead) ◄── NEW
                                             │   queries CallSession (last 3)
                                             │   formats call_history
                                             │   formats confirmed_facts
                                             │   computes is_returning_caller
                                             │   computes call_number
                                             └──► real values injected
                                                    │
                                           Template rendered WITH memory
                                           Agent knows prior conversations ✓
```

## Affected Areas

| File | Why |
|------|-----|
| `backend/app/prompts/loader.py` | `_build_variables()` must call shared memory builder; `render()` needs DB session |
| `backend/app/voice/webhook.py:569` | Must pass DB session to `render()`; currently closes DB context before render |
| `backend/app/voice/initiation.py:32-99` | Memory formatting helpers to extract into shared module |
| `backend/app/calls/service.py:184-207` | `get_sessions_for_lead()` already exists — no changes needed |
| `backend/clients/quintana-seguros/prompt.md` | No changes — template already has the placeholders |

## Options Evaluated

| | Option A: Direct Render | Option B: Frontend Pre-fetch | Option C: Shared Module Only |
|---|---|---|---|
| **Approach** | `_build_variables()` queries DB directly via inline helper | New REST endpoint; frontend embeds memory in WS `dynamic_variables` | Extract helpers from `initiation.py` to `app/memory.py`; both paths import |
| **Effort** | ~50 lines + tests | ~80 lines + tests | ~60 lines + tests |
| **Coverage** | Every custom-LLM render | Only WS-direct (requires frontend changes) | Depends on who calls the module |
| **Frontend coupling** | None | High — requires frontend changes for every client | None |
| **Code duplication** | Duplicates formatting logic from initiation.py | Duplicates nothing but adds surface area | Zero duplication |
| **Risk** | `render()` signature change; callers must be updated | Endpoint security; race condition (memory fetched before call starts) | Minimal — pure refactor of existing code |
| **Verdict** | Solves the problem but duplicates logic | Over-engineered; fragile coupling | Clean but doesn't wire it into render by itself |

## Recommendation: A + C Combined

**Extract + wire in one change.**

1. **New module `backend/app/memory.py`** — move `_format_call_history()` and
   `_format_confirmed_facts()` from `initiation.py` here. Add a new async function
   `build_memory_for_lead(db: AsyncSession, lead: Lead) -> MemoryVars` that:
   - Calls `get_sessions_for_lead(db, lead.id, status_filter=["completed"], limit=3)`
   - Formats `call_history` and `confirmed_facts`
   - Computes `is_returning_caller` and `call_number`
   - Returns a typed dict or dataclass

2. **`initiation.py`** — replace inline helper calls with
   `from app.memory import build_memory_for_lead`. Existing behavior unchanged.

3. **`loader.py`** — `render()` accepts an optional `db: AsyncSession | None` param.
   If `db` and `lead` are both available, call `build_memory_for_lead(db, lead)` and
   merge into the variables dict. Falls back to empty defaults when `db` is `None`
   (backward compat for tests / non-DB callers).

4. **`webhook.py`** — pass `db` session to `PromptLoader().render(client, lead, db=db)`.
   Restructure the DB context so the session stays open through the render call (it
   currently closes before render at line 564-569 — needs adjustment).

**Why A + C?** Single source of truth for memory formatting. Both the initiation
(Twilio/SIP) and custom-LLM (WS-direct) paths use the same builder. No frontend changes.
No new endpoints. ~60 lines of net-new code.

## Relationship to Prior Changes

- **qora-phase2 (CAP-6)**: Implemented memory injection via `dynamic_variables` in the
  initiation webhook. This was correct for the Twilio/SIP flow but doesn't fire in the
  WS-direct flow. This change **revises** CAP-6's delivery mechanism: memory now travels
  through the custom-LLM prompt render path, which fires on EVERY conversation.

- **qora-session-continuity**: Fixed `CallSession.lead_id` persistence so sessions are
  correctly linked to leads. This is a **prerequisite** — without it,
  `get_sessions_for_lead()` would return nothing and memory would still be empty.

## Key Unknowns / Risks

1. **`Lead.extracted_facts` shape** — `_format_confirmed_facts()` expects specific keys
   (`current_insurance`, `objections`, `interest_level`, `next_action_suggested`,
   `misc_facts`). If the summarizer writes a different shape, facts will silently be
   empty. **Mitigation**: add a log warning when `extracted_facts` is non-null but
   produces zero formatted lines.

2. **DB session lifetime in webhook.py** — the current code closes the `async with
   db_session()` block before calling `render()`. The fix needs to keep the session open
   through render, or open a second session inside render. Keeping it open is simpler and
   avoids double-session overhead.

3. **`call_count` not passed from webhook** — `webhook.py:569` calls
   `render(client, lead)` without `call_count`, so it defaults to `1`. The shared builder
   should compute `call_number` from `lead.call_count` directly, making the parameter
   unnecessary.

## Ready for Proposal

**Yes** — the root cause is confirmed, the fix is scoped, and the recommended option
(A + C) is clear. Next step: `sdd-propose` to formalize scope, then `sdd-spec` / `sdd-design`.
