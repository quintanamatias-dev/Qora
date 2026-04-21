# Design: qora-memory-in-prompt

## Technical Approach

Extract memory-building logic from `initiation.py` into `backend/app/memory.py`, wire it into `PromptLoader._build_variables()` (made async), and pass the DB session from `webhook.py` through `render()`. Both Twilio/SIP (initiation) and WebSocket-direct (custom-LLM) paths converge on the same builder. No frontend changes, no new endpoints.

## Architecture Decisions

### AD-1: Shared module location

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `app/memory.py` (top-level) | Simple, discoverable, no nesting | **Chosen** |
| `app/prompts/memory.py` | Groups with prompts, but memory isn't a prompt concern | Rejected |
| `app/calls/memory.py` | Groups with calls, but memory serves prompts too | Rejected |

**Rationale**: Memory context is consumed by both voice/initiation and prompts/loader — neither owns it. Top-level `app/memory.py` avoids coupling.

### AD-2: MemoryContext as TypedDict (not dataclass)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `TypedDict` | Zero overhead, dict-compatible, easy to merge into variables dict | **Chosen** |
| `dataclass` | Requires `.asdict()` before merging, more ceremony | Rejected |
| Plain `dict` | No type safety | Rejected |

**Rationale**: `_build_variables` returns `dict[str, str]` — TypedDict merges naturally via `{**vars, **memory}`. Type-checked at dev time, zero runtime cost.

### AD-3: Timezone for call_history dates

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `America/Argentina/Buenos_Aires` via `zoneinfo` | Correct for business/UX context; Python 3.9+ stdlib | **Chosen** |
| UTC display | Technically simpler but shows wrong date at night (UTC-3 offset) | Rejected |
| `pytz` | Third-party dep for something stdlib handles | Rejected |

**Rationale**: The prompt is rioplatense Spanish for Argentine users. Showing UTC dates would display the wrong day after 9pm. Python 3.11 (`zoneinfo` stdlib) — no fallback needed.

### AD-4: `RETURNING_CALLER_CONTEXT` interaction

**Audit result**: `RETURNING_CALLER_CONTEXT` in `insurance_agent.py` (line 136-139) formats a 2-line string injected via `{returning_caller_context}` placeholder when `call_count > 1`. This is orthogonal to `MemoryContext`:
- `RETURNING_CALLER_CONTEXT` → agent behavioral instruction ("Te llamo de vuelta...")
- `MemoryContext.call_history` → factual session log ("Llamada del DD/MM/YYYY: ...")

**Decision**: Keep `RETURNING_CALLER_CONTEXT` as-is. It receives `call_count` from `MemoryContext.call_number` when memory is available. No removal, no duplication.

### AD-5: Error logging strategy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `structlog.error()` with `{lead_id, error_type, error_msg}` | Queryable, lightweight, matches project pattern | **Chosen** |
| Sentry alert | Project has no Sentry integration (confirmed via grep) | Out of scope |

### AD-6: `confirmed_facts` ordering

Fixed code-defined order per spec REQ-1.4: `current_insurance` → `interest_level` → `next_action_suggested`. Processed via ordered list of tuples, not dict iteration. Deterministic for snapshot testing.

## Data Flow

```
CURRENT STATE
─────────────
webhook.py                     loader.py
  async with db as db:           _build_variables(client, lead, call_count):
    client = get_client(db)        call_history = ""            ← HARDCODED
    lead = get_lead(db)            confirmed_facts = ""         ← HARDCODED
  # ← DB CLOSED HERE              is_returning_caller = "false"
  PromptLoader().render(c, l) ──►  call_number = "1"
                                   return vars_dict
                                 _render_template(template, vars) → prompt
                                                                   (no memory)

NEW STATE
─────────
webhook.py                     loader.py                    memory.py
  async with db as db:           async _build_variables(     build_memory_context(
    client = get_client(db)        client, lead,               db, lead):
    lead = get_lead(db)            call_count, db):            sessions = get_sessions_for_lead(...)
    # ↓ DB STILL OPEN              if db and lead:             call_history = format_call_history(sessions)
    system = await render(           mem = await build_mem(…)  confirmed_facts = format_confirmed_facts(…)
      client, lead, db=db)           merge mem → vars          is_returning_caller = len(sessions) > 0
  # ← DB CLOSED AFTER render      else:                       call_number = lead.call_count + 1
                                     empty defaults            return MemoryContext(…)
                                   return vars_dict

initiation.py (refactored)
  async with db as db:
    ...
    mem = await build_memory_context(db, lead)
    # use mem.call_history, mem.confirmed_facts, etc.
    # in dynamic_variables response
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/memory.py` | **Create** | `MemoryContext` TypedDict, `build_memory_context()`, `format_call_history()`, `format_confirmed_facts()` |
| `backend/app/prompts/loader.py` | **Modify** | `render()` + `_build_variables()` → async; accept `db` param; call `build_memory_context`; try/except graceful fallback |
| `backend/app/prompts/insurance_agent.py` | **Modify** | `render_system_prompt()` accepts `memory: MemoryContext | None = None`; uses it for `call_count` in `RETURNING_CALLER_CONTEXT` |
| `backend/app/voice/webhook.py` | **Modify** | Move `render()` call inside `async with db_session()` block; pass `db=db` |
| `backend/app/voice/initiation.py` | **Modify** | Replace inline `_format_call_history` + `_format_confirmed_facts` with `build_memory_context` import |
| `backend/tests/unit/test_memory.py` | **Create** | ~9 unit tests for `build_memory_context` |
| `backend/tests/unit/prompts/test_loader.py` | **Modify** | Update existing sync-assumption tests; add ~8 memory-related tests |
| `backend/tests/integration/voice/test_custom_llm_memory.py` | **Create** | ~3 integration tests: webhook renders with memory |
| `backend/tests/integration/voice/test_initiation.py` | **Modify** | ~2 regression tests: response shape unchanged |
| `backend/tests/integration/voice/test_session_continuity_e2e.py` | **Modify** | ~3 new assertions: second-call prompt contains summary |

## Interfaces / Contracts

### `backend/app/memory.py`

```python
from __future__ import annotations
from typing import TypedDict
from sqlalchemy.ext.asyncio import AsyncSession
from app.leads.models import Lead

class MemoryContext(TypedDict):
    call_history: str
    confirmed_facts: str
    is_returning_caller: bool
    call_number: int

async def build_memory_context(db: AsyncSession, lead: Lead) -> MemoryContext:
    """Single source of truth for memory variables.
    Raises ValueError if lead is None.
    Logs memory_context_built event.
    """
    ...

def format_call_history(sessions: list) -> str:
    """Format sessions as dated summary lines. Timezone: America/Argentina/Buenos_Aires."""
    ...

def format_confirmed_facts(extracted_facts: dict | None) -> str:
    """Format extracted_facts in fixed order: current_insurance, interest_level, next_action_suggested."""
    ...
```

### `loader.py` — async render signature

```python
async def render(
    self,
    client: "Client",
    lead: "Lead | None" = None,
    call_count: int = 1,
    db: AsyncSession | None = None,  # NEW — optional
) -> str:
```

### `loader.py` — `_build_variables` async with graceful error handling

```python
async def _build_variables(
    self,
    client: "Client",
    lead: "Lead | None",
    call_count: int,
    db: "AsyncSession | None" = None,  # NEW
) -> dict[str, str]:
    ...
    # After computing base variables, attempt memory injection
    if db is not None and lead is not None:
        try:
            memory = await build_memory_context(db, lead)
        except Exception as e:
            logger.error(
                "memory_context_failed",
                lead_id=lead.id,
                error_type=type(e).__name__,
                error_msg=str(e),
            )
            memory = None
    else:
        memory = None

    if memory is not None:
        variables["call_history"] = memory["call_history"]
        variables["confirmed_facts"] = memory["confirmed_facts"]
        variables["is_returning_caller"] = str(memory["is_returning_caller"]).lower()
        variables["call_number"] = str(memory["call_number"])
        # Update returning_caller_context using real call_number
        if memory["call_number"] > 1:
            variables["returning_caller_context"] = RETURNING_CALLER_CONTEXT.format(
                call_count=memory["call_number"]
            )
    return variables
```

### `insurance_agent.py` — render_system_prompt signature change

```python
def render_system_prompt(
    client: "Client",
    lead: "Lead | None" = None,
    call_count: int = 1,
    memory: "MemoryContext | None" = None,  # NEW — optional
) -> str:
    ...
    # When memory is provided, use its call_number for returning_caller_context
    effective_call_count = memory["call_number"] if memory else call_count
    if effective_call_count > 1:
        returning_caller_context = RETURNING_CALLER_CONTEXT.format(
            call_count=effective_call_count
        )
```

### `webhook.py` — DB session lifetime restructure

```python
# BEFORE (line 536-569):
async with db_session() as db:
    client = await get_client(db, client_id)
    ...
    lead = await get_lead(db, lead_id)
# ← DB CLOSED
system_content = ... await PromptLoader().render(client, lead)  # no DB access

# AFTER:
async with db_session() as db:
    client = await get_client(db, client_id)
    ...
    lead = await get_lead(db, lead_id)
    # DB STILL OPEN — render can query for memory
    system_content = (
        client.system_prompt_override
        if client.system_prompt_override is not None
        else await PromptLoader().render(client, lead, db=db)
    )
# ← DB CLOSED after render completes
```

### `initiation.py` — refactor pseudocode

```python
# BEFORE (inline helpers + manual building):
call_history = _format_call_history(completed_sessions)
confirmed_facts = _format_confirmed_facts(lead.extracted_facts)
is_returning_caller = len(completed_sessions) > 0
call_number = (lead.call_count or 0) + 1

# AFTER (shared builder):
from app.memory import build_memory_context
memory = await build_memory_context(session, lead)
# Use memory["call_history"], memory["confirmed_facts"], etc.
# in dynamic_variables dict — SAME keys, SAME types, SAME response shape
```

Delete `_format_call_history()` and `_format_confirmed_facts()` from `initiation.py`.

## Testing Strategy

| Layer | File | Tests | What |
|-------|------|-------|------|
| Unit | `tests/unit/test_memory.py` (new) | ~9 | CAP-1 scenarios: 0/1/3/4 sessions, extracted_facts variants, None lead, call_number math |
| Unit | `tests/unit/prompts/test_loader.py` (modify) | ~8 new | CAP-2: db=None fallback, lead=None fallback, no literal placeholders, stringification, memory content in prompt |
| Integration | `tests/integration/voice/test_custom_llm_memory.py` (new) | ~3 | CAP-3: happy path with DB, DB error graceful fallback, no-lead empty defaults |
| Integration | `tests/integration/voice/test_initiation.py` (modify) | ~2 | CAP-4: response shape regression, no inline helpers |
| E2E | `tests/integration/voice/test_session_continuity_e2e.py` (modify) | ~3 | CAP-5: second-call prompt has summary, is_returning_caller=true, call_number increments |

### Tests that may break

- `test_loader.py`: 14 tests call `render()` synchronously — already `async`/`await`, no change needed (signature stays compatible with `db=None` default)
- `test_insurance_agent.py`: `render_system_prompt` calls use `(client, lead, call_count)` — backward compat via optional `memory=None` kwarg
- `test_custom_llm_path_route.py`: if any test asserts `call_history == ""` when prior sessions exist in DB, it will now see real values — update mocks or expectations

## Backward Compatibility

| Change | Compat? | Notes |
|--------|---------|-------|
| `render()` adds `db=None` param | Yes | Optional kwarg — all callers work unchanged |
| `_build_variables()` becomes async | Internal | Private method, all callers are in `loader.py` — we control them |
| `_render_template()` updated to await `_build_variables` | Internal | Same — private, we control |
| `render_system_prompt()` adds `memory=None` kwarg | Yes | Optional — existing callers unaffected |
| Initiation response shape | **Must** stay identical | Regression test covers this |

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Async propagation cascade — caller of `render()` not awaited | Low | Grep found 1 production caller (`webhook.py:569`) + 14 test callers — all already `await` it |
| Timezone: `zoneinfo` unavailable | None | Python 3.11 confirmed; `zoneinfo` is stdlib since 3.9 |
| Empty `extracted_facts` edge cases (`None`, `{}`, `"null"`) | Med | Formatter uses `if not extracted_facts: return ""` — handles `None`, `{}`, `""`. Add explicit test for JSON `"null"` string |
| `get_sessions_for_lead` returns sessions without summary | Low | Spec says filter `summary IS NOT NULL AND summary != ""` — add `.where()` clause in `build_memory_context`, not the service (service stays general-purpose) |
| Test isolation — unit tests for `build_memory_context` need DB | Med | Use existing `seeded_db` fixture pattern from `test_memory_injection.py` |

## Migration / Rollout

No migration required. No DB schema changes. No feature flags. Rollback = revert commit.

## Open Questions

None — all 4 questions from spec resolved above (AD-3: timezone, AD-5: error severity, AD-6: ordering, AD-4: RETURNING_CALLER_CONTEXT).

## Callers of `render()` (exhaustive grep)

| File | Line | Context |
|------|------|---------|
| `backend/app/voice/webhook.py` | 569 | `await PromptLoader().render(client, lead)` — production |
| `backend/tests/unit/prompts/test_loader.py` | 147, 169, 187, 203, 217, 241, 266, 289, 306, 323, 344, 375, 394 | 14 test calls — all already `await` |
