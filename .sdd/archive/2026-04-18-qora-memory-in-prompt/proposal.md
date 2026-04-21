# Proposal: qora-memory-in-prompt

## Intent

The agent's system prompt includes placeholders for memory (`{{call_history}}`, `{{confirmed_facts}}`, `{{is_returning_caller}}`, `{{call_number}}`) but `PromptLoader._build_variables()` hardcodes them to empty defaults, relying on the `/voice/initiation` webhook to populate them via ElevenLabs `dynamic_variables`. In the WebSocket-direct flow (browser demo + any future web widget), ElevenLabs never calls the initiation webhook — it only fires for Twilio/SIP inbound paths. Route memory population through the custom-LLM render path (which ALWAYS fires) by extracting memory-building logic into a shared module and wiring it into `PromptLoader`. This unblocks CAP-6 memory injection for all client surfaces without requiring frontend-specific coupling.

## Scope

### In Scope
- New module `backend/app/memory.py` — `async build_memory_context(db, lead) -> MemoryContext` (dataclass/TypedDict, 4 fields)
- Extract memory-building helpers from `initiation.py` into the new module (last 3 completed sessions, `call_history`, `confirmed_facts`, `is_returning_caller`, `call_number`)
- Refactor `initiation.py` to consume `build_memory_context` — behaviour unchanged, code deduplicated
- Make `PromptLoader._build_variables()` and `render()` async; accept DB session; populate real memory via shared builder when lead + db are present
- Update `webhook.py` (~line 569) to pass DB session into `render()`; keep session open through render
- Update `insurance_agent.py` `render_system_prompt()` to accept optional memory context kwarg (no DB dependency — keeps it pure)
- Unit tests: `build_memory_context` (0/1/3 sessions, extracted_facts, do_not_call)
- Unit tests: `_build_variables` with real memory vs. no-lead fallback
- Integration test: custom-LLM webhook renders prompt with prior-session summary
- E2E: extend `test_session_continuity_e2e.py` — second-call system prompt contains last call summary
- `docs/elevenlabs-setup.md` — short section: "Where memory is populated"

### Out of Scope
- Changing prompt template syntax or placeholder names
- Adding new memory variables beyond the 4 in CAP-6
- Caching memory across requests
- Per-call frontend overrides (skip memory this call)
- Phase 3 features (vector search / semantic memory)

## Capabilities

### New Capabilities
- `prompt-memory-injection`: Custom-LLM prompt render populates memory variables from DB at request time, regardless of ElevenLabs initiation webhook firing.

### Modified Capabilities
- `memory-injection` (qora-phase2 CAP-6): Source of truth moves from "initiation webhook response" to "prompt render at custom-LLM request". Both paths remain; initiation is still correct for Twilio/SIP; custom-LLM render becomes the primary path for WebSocket flows.

## Approach

Extract `_format_call_history()` and `_format_confirmed_facts()` from `initiation.py` into a new `app/memory.py` module. Add `build_memory_context(db, lead)` that queries `CallSession` (last 3 completed), computes all 4 variables, and returns a typed result. Wire it into `PromptLoader._build_variables()` (made async) with graceful fallback to empty defaults when `db` is `None`. Update `webhook.py` to keep the DB session open through `render()`. Both Twilio/SIP and WebSocket paths converge on the same formatter — single source of truth, no frontend coupling, ~60 lines net-new.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/memory.py` | New | `build_memory_context(db, lead) -> MemoryContext` |
| `backend/app/prompts/loader.py` | Modified | `_build_variables()` + `render()` async; accept DB session; real memory injection |
| `backend/app/prompts/insurance_agent.py` | Modified | `render_system_prompt()` accepts optional memory context kwarg |
| `backend/app/voice/initiation.py` | Modified | Consumes `build_memory_context` — no behaviour change |
| `backend/app/voice/webhook.py` | Modified | Pass DB session to `render()`; keep session open through render |
| `backend/tests/unit/test_memory.py` | New | Unit tests for `build_memory_context` |
| `backend/tests/unit/prompts/test_loader.py` | New/Modified | Async tests for `_build_variables` with memory |
| `backend/tests/integration/voice/test_custom_llm_memory.py` | New | Integration: render contains prior-session summary |
| `backend/tests/integration/voice/test_session_continuity_e2e.py` | Extended | Second-call memory assertion |
| `docs/elevenlabs-setup.md` | Modified | "Where memory is populated" section |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `Lead.extracted_facts` JSON shape drift — formatter silently produces empty output | Med | Use `.get(key, default)` per field; emit warning log if `extracted_facts` is non-null but yields zero lines |
| DB session lifetime in `webhook.py` — render currently runs outside DB context | Med | Restructure to keep `async with db_session()` open through `render()` call |
| Existing tests assert empty memory in rendered prompt | Low | Audit `test_custom_llm_path_route.py`; update or mock `build_memory_context` |

## Rollback Plan

- Revert `PromptLoader._build_variables()` to hardcoded defaults
- Delete `app/memory.py`
- Revert `initiation.py` to inline helpers (was self-contained)
- Revert `webhook.py` render call signature
- No DB migrations → zero-cost rollback

## Dependencies

- **qora-session-continuity** (completed): `CallSession.lead_id` must be persisted correctly for `get_sessions_for_lead()` to return results

## Success Criteria

- [ ] Browser demo second call: system prompt contains `call_history` with prior session summary
- [ ] Browser demo second call: `is_returning_caller` is `"true"`, `call_number` is `"2"`
- [ ] Twilio/SIP path: `/voice/initiation` response is unchanged (backward compat)
- [ ] All new unit + integration tests pass
- [ ] `loader.py` callers with no DB session fall back to empty defaults without error
