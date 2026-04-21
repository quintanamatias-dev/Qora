# Delta Spec: qora-memory-in-prompt

## Purpose

Extends CAP-6 (qora-phase2 memory injection) to wire memory variables into the
custom-LLM prompt render path. Introduces a shared `build_memory_context` builder
so both the initiation webhook (Twilio/SIP) and the custom-LLM webhook (WebSocket)
read memory from the same source of truth.

---

## CAP-1: Shared Memory Context Builder

### Requirement: build_memory_context function

A new async function `build_memory_context(db: AsyncSession, lead: Lead) -> MemoryContext`
MUST exist in `backend/app/memory.py` and be the single source of truth for computing
memory variables.

The return type `MemoryContext` MUST have exactly four fields:
`call_history: str`, `confirmed_facts: str`, `is_returning_caller: bool`, `call_number: int`.

The function MUST load AT MOST the 3 most-recent `CallSession` records where
`status="completed"` AND `summary IS NOT NULL AND summary != ""`, ORDER BY `ended_at DESC`.

`call_history` MUST be a multi-line string with one line per session:
`"Llamada del DD/MM/YYYY: \"<summary>\""` (summary truncated to first 150 chars).
Empty string if no qualifying sessions exist.

`confirmed_facts` MUST be a bulleted multi-line string from `lead.extracted_facts`:
`current_insurance` → `"- Seguro actual: X"`,
`interest_level` → `"- Nivel de interés: X/100"`,
`next_action_suggested` → `"- Acción sugerida: X"`.
Empty string if `extracted_facts` is None, empty, or yields no recognised keys.

`is_returning_caller` MUST be `True` iff at least one `CallSession` with
`status="completed"` exists for the lead.

`call_number` MUST equal `lead.call_count + 1`.

If `lead is None` the function MUST raise `ValueError`.

The function MUST emit one structured log event `memory_context_built` with fields
`{lead_id, session_count, has_facts, call_number}`.

#### Scenario: No prior sessions — all defaults

- GIVEN a lead with `call_count=0` and no completed `CallSession` records
- WHEN `build_memory_context(db, lead)` is called
- THEN `call_history == ""`, `confirmed_facts == ""`, `is_returning_caller == False`, `call_number == 1`
- AND log event `memory_context_built` is emitted with `session_count=0`

#### Scenario: One completed session with summary

- GIVEN a lead with one completed session whose `summary = "El cliente mostró interés en cambiar de seguro."`
- WHEN `build_memory_context(db, lead)` is called
- THEN `call_history` contains `"Llamada del"` and the first 150 chars of that summary
- AND `is_returning_caller == True`
- AND `call_number == lead.call_count + 1`

#### Scenario: Three sessions loaded, fourth ignored

- GIVEN a lead with 4 completed sessions (all with summaries)
- WHEN `build_memory_context(db, lead)` is called
- THEN `call_history` contains exactly 3 lines
- AND the 4th (oldest) session MUST NOT appear in `call_history`

#### Scenario: Sessions with no summary excluded from call_history

- GIVEN a lead with 2 completed sessions where one has `summary=None`
- WHEN `build_memory_context(db, lead)` is called
- THEN only the session with a summary appears in `call_history`

#### Scenario: Recognised extracted_facts keys produce confirmed_facts

- GIVEN a lead with `extracted_facts = {"current_insurance": "La Caja", "interest_level": 72}`
- WHEN `build_memory_context(db, lead)` is called
- THEN `confirmed_facts` contains `"- Seguro actual: La Caja"` and `"- Nivel de interés: 72/100"`

#### Scenario: Empty extracted_facts dict produces empty confirmed_facts

- GIVEN a lead with `extracted_facts = {}`
- WHEN `build_memory_context(db, lead)` is called
- THEN `confirmed_facts == ""`

#### Scenario: None extracted_facts produces empty confirmed_facts

- GIVEN a lead with `extracted_facts = None`
- WHEN `build_memory_context(db, lead)` is called
- THEN `confirmed_facts == ""`

#### Scenario: call_number is lead.call_count + 1

- GIVEN a lead with `call_count = 3`
- WHEN `build_memory_context(db, lead)` is called
- THEN `call_number == 4`

#### Scenario: None lead raises ValueError

- GIVEN `lead = None`
- WHEN `build_memory_context(db, None)` is called
- THEN a `ValueError` MUST be raised

---

## CAP-2: PromptLoader Populates Real Memory When DB Is Provided

### Requirement: PromptLoader async render with DB session

`PromptLoader.render()` MUST accept an optional `db: AsyncSession | None = None` parameter.

`PromptLoader._build_variables()` MUST become async and accept `db: AsyncSession | None = None`.

When `db is not None AND lead is not None`, `_build_variables()` MUST call
`build_memory_context(db, lead)` and inject the returned values for
`call_history`, `confirmed_facts`, `is_returning_caller`, `call_number`.

When `db is None` OR `lead is None`, memory variables MUST resolve to empty defaults:
`call_history=""`, `confirmed_facts=""`, `is_returning_caller="false"`, `call_number="1"`.

`is_returning_caller` MUST be stringified to `"true"` or `"false"` in the rendered prompt.

`call_number` MUST be stringified to a digit string (`"1"`, `"2"`, etc.).

The rendered prompt MUST NOT contain literal `{{call_history}}`, `{{confirmed_facts}}`,
`{{is_returning_caller}}`, or `{{call_number}}` after substitution.

`insurance_agent.render_system_prompt()` MUST accept an optional
`memory: MemoryContext | None = None` keyword argument; uses it when present,
falls back to empty defaults otherwise.

#### Scenario: db=None falls back to empty defaults

- GIVEN `PromptLoader` is called with `db=None`
- WHEN `render()` completes
- THEN `call_history`, `confirmed_facts` resolve to `""`
- AND `is_returning_caller` resolves to `"false"`, `call_number` to `"1"`

#### Scenario: lead=None falls back to empty defaults

- GIVEN `PromptLoader` is called with a valid `db` but `lead=None`
- WHEN `render()` completes
- THEN memory variables resolve to empty defaults without error

#### Scenario: No literal placeholders remain after render

- GIVEN a template containing `{{call_history}}`, `{{confirmed_facts}}`, `{{is_returning_caller}}`, `{{call_number}}`
- WHEN `render()` completes (with or without db)
- THEN the rendered string MUST NOT contain any of those literal placeholder strings

#### Scenario: is_returning_caller True stringified correctly

- GIVEN a lead with one completed session (so `is_returning_caller=True`)
- WHEN `render()` is called with a valid `db`
- THEN the rendered prompt contains the string `"true"` (not `"True"` or `True`)

#### Scenario: call_number stringified as digit

- GIVEN a lead with `call_count=2`
- WHEN `render()` is called with a valid `db`
- THEN the rendered prompt contains `"3"` (not `3` or `"call_number"`)

#### Scenario: call_history content appears in rendered prompt

- GIVEN a lead with a completed session with summary `"Cliente interesado en cobertura total."`
- WHEN `render()` is called with a valid `db`
- THEN the rendered prompt contains `"Cliente interesado"` within the call_history block

#### Scenario: confirmed_facts appear in rendered prompt

- GIVEN a lead with `extracted_facts = {"current_insurance": "Zurich"}`
- WHEN `render()` is called with a valid `db`
- THEN the rendered prompt contains `"Seguro actual: Zurich"`

#### Scenario: insurance_agent.render_system_prompt memory kwarg accepted

- GIVEN `render_system_prompt()` is called without `memory` kwarg
- WHEN the call completes
- THEN no exception is raised and memory variables resolve to empty defaults

---

## CAP-3: Custom-LLM Webhook Passes DB Session to Render

### Requirement: webhook.py passes DB session through render

In `_process_custom_llm_request`, the DB session MUST be passed to `PromptLoader().render()` via the `db` parameter.

The DB session MUST remain open for the full duration of the `render()` call.

On any `Exception` raised by `build_memory_context`, the system MUST log a
`memory_context_failed` error event and fall back to empty memory defaults;
the custom-LLM SSE response MUST still be returned normally.

#### Scenario: Happy path — DB session passed and memory injected

- GIVEN a returning lead with a completed session and the DB session is open
- WHEN the custom-LLM webhook is triggered
- THEN `render()` is called with the open `db` session
- AND the rendered prompt contains the prior session summary

#### Scenario: DB error during memory build — graceful fallback

- GIVEN `build_memory_context` raises a `SQLAlchemyError`
- WHEN the custom-LLM webhook processes the request
- THEN log event `memory_context_failed` MUST be emitted
- AND the webhook MUST return a valid SSE stream with empty memory defaults
- AND no 500 error is returned to ElevenLabs

#### Scenario: No lead in context — empty defaults, no error

- GIVEN the webhook processes a request where `lead` cannot be resolved
- WHEN `render()` is called with `db` but `lead=None`
- THEN the rendered prompt uses empty memory defaults without raising an exception

---

## CAP-4: Initiation Webhook Uses the Shared Builder

### Requirement: initiation.py delegates to build_memory_context (MODIFIED from CAP-6)

`backend/app/voice/initiation.py` MUST import and call `build_memory_context` from
`app.memory` to compute memory variables.
(Previously: inline `_format_call_history()` and `_format_confirmed_facts()` helpers
defined locally in `initiation.py`.)

The response shape of `POST /api/v1/voice/initiation` (all `dynamic_variables` keys)
MUST remain identical.

The inline helper functions `_format_call_history()` and `_format_confirmed_facts()`
MUST be deleted from `initiation.py` — no duplication allowed.

#### Scenario: Initiation response shape unchanged

- GIVEN a lead with one completed session
- WHEN `POST /api/v1/voice/initiation` is called
- THEN the response MUST contain `call_history`, `confirmed_facts`, `is_returning_caller`, `call_number` (and their underscore-wrapped variants) with the same types and values as before

#### Scenario: No inline helpers remain in initiation.py

- GIVEN the refactored `initiation.py`
- WHEN inspected
- THEN `_format_call_history` and `_format_confirmed_facts` MUST NOT be defined in that module
- AND `from app.memory import build_memory_context` MUST be present

---

## CAP-5: Observable End-to-End Memory Cycle

### Requirement: Second-call prompt contains prior session memory

(Delta on qora-phase2 CAP-6 — extends delivery path to custom-LLM render.)

Given a lead with one completed session containing a non-empty summary, the NEXT
`PromptLoader.render()` call for that lead MUST produce a rendered prompt that:
- Contains a substring from the session summary (first 40 chars)
- Contains `"true"` for `is_returning_caller`
- Contains `"2"` for `call_number`

On the very first call (no completed sessions), the rendered prompt MUST contain
`"false"` for `is_returning_caller` and `"1"` for `call_number`.

#### Scenario: First call — no history in prompt

- GIVEN a lead with `call_count=0` and no completed sessions
- WHEN `render()` is called with a valid `db`
- THEN the rendered prompt contains `"false"` for `is_returning_caller`
- AND `call_number` resolves to `"1"`
- AND `call_history` resolves to `""`

#### Scenario: Second call — prior summary appears in rendered prompt

- GIVEN a lead with one completed session whose summary starts with `"El cliente preguntó"`
- WHEN `render()` is called with a valid `db` for the next call
- THEN the rendered prompt contains `"El cliente preguntó"` (first 40 chars of summary)
- AND the rendered prompt contains `"true"` for `is_returning_caller`
- AND the rendered prompt contains `"2"` for `call_number`

#### Scenario: call_number increments with each completed session

- GIVEN a lead with `call_count=4`
- WHEN `build_memory_context(db, lead)` is called
- THEN `call_number == 5`

---

## Open Questions

1. **DateTime formatting locale and timezone** — `call_history` lines use
   `ref_dt.strftime("%d/%m/%Y")`. This assumes the DB stores datetimes in UTC but
   displays them without timezone conversion. Should dates be converted to
   `America/Argentina/Buenos_Aires` before formatting? The design phase MUST decide
   whether to use `pytz`/`zoneinfo` or keep UTC display.

2. **`memory_context_failed` severity** — Should this error event also trigger a
   Sentry alert, or is a structured log entry sufficient? If Sentry is enabled in
   the project, callers might want to be notified of persistent DB failures without
   crashing the call. The design phase MUST specify the alerting strategy.

3. **Determinism of `confirmed_facts` ordering** — The current `_format_confirmed_facts`
   processes keys in a fixed code-defined order (`current_insurance` → `objections` →
   `interest_level` → `next_action_suggested` → `misc_facts`). The spec preserves this
   ordering. If `extracted_facts` gains new keys, the order MUST be explicit in code —
   not dependent on dict insertion order. Design MUST confirm ordering contract.

4. **Interaction with `RETURNING_CALLER_CONTEXT` block in `insurance_agent.py`** —
   `insurance_agent.py` may already have a conditional block that renders different
   content for returning vs. new callers using `is_returning_caller`. With memory now
   injected at render time, this block MUST receive the real boolean, not the hardcoded
   `False`. The design phase MUST audit `insurance_agent.py` for any such block and
   confirm it will receive the correct value from `MemoryContext`.
