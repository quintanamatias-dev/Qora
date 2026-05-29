# Apply Progress: configurable-agent-tools — Phase 1 + Phase 2

**Branch (Phase 1)**: `feat/configurable-agent-tools-phase1`
**Branch (Phase 2)**: `feat/configurable-agent-tools-phase2`
**Mode**: Strict TDD
**PR**: #1 of 3 (Phase 1, stacked-to-main) + #2 of 3 (Phase 2, stacked to Phase 1)
**Date**: 2026-05-22

---

## Completed Tasks

### Phase 1 — Add capture_data + tool_config (COMPLETE ✅)

- [x] 1.1 RED: test_schemas.py — tool_config create/update/response tests (7 new tests)
- [x] 1.2 GREEN: Agent model + schemas + router for tool_config column
- [x] 1.3 RED: test_capture_data.py — 7 RED tests for capture_data handler
- [x] 1.4 GREEN: capture_data.py handler with LeadProfileFact upsert
- [x] 1.5 RED/GREEN: test_registry.py (new), test_dispatcher.py, test_context.py; registry.py, dispatcher.py, voice/context.py updated
- [x] 1.6 RED/GREEN: call_count moved from get_lead_details to initiation.py
- [x] 1.7 RED/GREEN: Quintana parity seed + config tests

### Phase 2 — Analysis-driven status transitions + legacy tool removal (COMPLETE ✅)

- [x] 2.1 RED: summarizer lifecycle tests — positive, negative, follow-up, retry/human-review, terminal-state no-op (11 tests)
- [x] 2.2 GREEN: apply_status_from_next_action pure function + wired into _merge_facts_into_lead
- [x] 2.3 RED/GREEN: removed register_interest, mark_not_interested, schedule_followup from TOOL_DEFINITIONS, _TOOL_REGISTRY; dispatch returns tool_removed; updated 6 test files
- [x] 2.4 REFACTOR: strip_deprecated_tools() in schemas.py; wired into voice/context.py for graceful DB legacy agent handling; 4 new tests

---

## TDD Cycle Evidence

### Phase 1

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/unit/agents/test_schemas.py` | Unit | ✅ 47/47 | ✅ Written | ✅ Passed | ✅ 7 cases | ✅ Clean |
| 1.2 | `tests/unit/agents/test_schemas.py` | Unit | N/A (additive) | ✅ Written | ✅ Passed | ✅ 3 schemas | ✅ Clean |
| 1.3 | `tests/unit/tools/test_capture_data.py` | Integration | N/A (new file) | ✅ Written | ✅ Passed | ✅ 6 scenarios | ✅ Clean |
| 1.4 | `tests/unit/tools/test_capture_data.py` | Integration | N/A (new module) | ✅ Written | ✅ Passed | ✅ atomic+upsert | ✅ Clean |
| 1.5 | `tests/unit/tools/test_registry.py` + dispatcher + context | Unit | ✅ 153/153 | ✅ Written | ✅ Passed | ✅ 10 registry cases | ✅ Clean |
| 1.6 | `tests/unit/tools/test_get_lead_details.py` + `test_initiation.py` | Unit+Integration | ✅ approval test | ✅ Written | ✅ Passed | ✅ no-increment + increment | ✅ Clean |
| 1.7 | `tests/test_qora_demo_seed.py` | Unit | ✅ 320 existing | ✅ Written | ✅ Passed | ✅ parity cases | ✅ Clean |

### Phase 2

| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `tests/unit/test_summarizer.py` | Unit | ✅ 59/59 | ✅ 11 written | ✅ Passed | ✅ 5 positive+negative+follow_up+retry+terminal cases | ✅ Clean |
| 2.2 | `tests/unit/test_summarizer.py` | Unit | N/A (same file) | ✅ Written | ✅ Passed | ✅ hostile+dnc+schedule_call variants | ✅ Clean |
| 2.3 | `tests/unit/tools/test_dispatcher.py` | Unit+Integration | ✅ 16/16 | ✅ 5 written | ✅ Passed | ✅ 3 legacy tools | ✅ Updated 6 test files |
| 2.4 | `tests/unit/agents/test_schemas.py` | Unit | ✅ 96/96 | ✅ 4 written | ✅ Passed | ✅ all-legacy+partial cases | ✅ Clean |

### Test Summary (Phase 2)
- **New tests written (Phase 2)**: 20
- **Total tests passing after Phase 2**: 1770 (5 pre-existing failures unchanged)
- **Layers used**: Unit (20), Integration (0 new)
- **Approval tests** (refactoring): 0 (no refactoring of existing behavior)
- **Pure functions created**: 2 (`apply_status_from_next_action`, `strip_deprecated_tools`)

---

## Files Changed

### Phase 1 Files

| File | Action | Description |
|------|--------|-------------|
| `backend/app/tenants/models.py` | Modified | Added `tool_config: Text nullable` column to Agent |
| `backend/app/agents/schemas.py` | Modified | Added `tool_config: dict \| None` to AgentCreate/AgentUpdate/AgentResponse |
| `backend/app/agents/router.py` | Modified | serialize/deserialize tool_config (dict ↔ JSON TEXT), pass to create_agent |
| `backend/app/tenants/service.py` | Modified | Added `tool_config` param to create_agent(); added `_QUINTANA_TOOL_CONFIG`; updated seed_quintana() for dual-run |
| `backend/app/tools/registry.py` | Modified | Added `capture_data` to TOOL_DEFINITIONS; added `build_capture_data_definition()`; updated `build_tool_definitions()` with `agent_tool_config` kwarg |
| `backend/app/tools/capture_data.py` | Created | Generic capture handler with required-field validation and LeadProfileFact upsert |
| `backend/app/tools/dispatcher.py` | Modified | Added `agent_tool_config` param; added capture_data routing with config injection |
| `backend/app/voice/context.py` | Modified | Parse agent.tool_config JSON and pass to build_tool_definitions as agent_tool_config |
| `backend/app/voice/initiation.py` | Modified | Added call_count increment + last_called_at (moved from get_lead_details) |
| `backend/app/tools/get_lead_details.py` | Modified | Removed call_count side-effect; now pure read |

### Phase 2 Files

| File | Action | Description |
|------|--------|-------------|
| `backend/app/summarizer.py` | Modified | Added `apply_status_from_next_action()` pure function; wired into `_merge_facts_into_lead`; added `_TERMINAL_STATUSES` and `_NEGATIVE_CLASSIFICATIONS` constants |
| `backend/app/tools/registry.py` | Modified | Removed register_interest/mark_not_interested/schedule_followup imports and TOOL_DEFINITIONS entries; added `_REMOVED_TOOLS` frozenset |
| `backend/app/tools/dispatcher.py` | Modified | Removed legacy tool imports and routing; added `tool_removed` early-return for `_LEGACY_REMOVED_TOOLS` |
| `backend/app/agents/schemas.py` | Modified | Added `strip_deprecated_tools()` pure function; added `_REMOVED_TOOLS` import |
| `backend/app/voice/context.py` | Modified | Wired `strip_deprecated_tools()` into tool name loading from DB |
| `backend/tests/unit/test_summarizer.py` | Modified | Added 11 lifecycle tests for `apply_status_from_next_action` |
| `backend/tests/unit/tools/test_dispatcher.py` | Modified | Updated mark_not_interested+schedule_followup tests to expect `tool_removed`; added 3 explicit tool_removed tests + 1 registry test |
| `backend/tests/unit/agents/test_schemas.py` | Modified | Updated legacy tool assertions; added 4 strip_deprecated_tools tests |
| `backend/tests/unit/agents/test_tools_list_contract.py` | Modified | Updated 3 tests that referenced legacy tools |
| `backend/tests/unit/test_admin_api_lifecycle.py` | Modified | Updated 1 test that used register_interest |
| `backend/tests/unit/voice/test_load_skill_tool.py` | Modified | Updated CRM tools list assertion for Phase 2 |

---

## Commits

### Phase 1 Commits
1. `feat(agents): add tool_config column and capture_data to tool registry`
2. `feat(tools): add capture_data handler with LeadProfileFact upsert`
3. `feat(tools): wire capture_data through dispatcher and voice context`
4. `refactor(tools): move call_count increment from get_lead_details to initiation`
5. `feat(tenants): Quintana parity seed with capture_data tool_config`
6. `fix(voice): pass agent_tool_config through webhook→dispatcher→capture_data end-to-end`

### Phase 2 Commits
1. `feat(summarizer): add apply_status_from_next_action for analysis-driven status transitions`
2. `feat(tools): remove legacy tools from registry and dispatcher (Phase 2)`
3. `refactor(schemas): add strip_deprecated_tools for graceful legacy agent handling`

---

## Deviations from Design

- **Phase 1**: voice/webhook.py wasn't modified directly; context injection happens in voice/context.py. The verify phase confirmed agent_tool_config flows end-to-end via webhook.
- **Phase 2**: `apply_status_from_next_action` takes `next_action_result` dict (from `facts["next_action_result"]`), not a NextActionResult model — this is intentional since by the time it runs in `_merge_facts_into_lead`, the model has been serialized via `model_dump()`.

---

## Risks

- **Phase 3 dependency**: Phase 3 (car field removal) depends on Phase 2. The `strip_deprecated_tools` integration in `voice/context.py` ensures a smooth rollout with no session crashes.
- **Status transition double-fire**: `apply_status_from_next_action` guards terminal states (returns None), but `transition_lead_status` also enforces state machine rules via `is_valid_transition`. Double protection.

---

## Status

7/7 Phase 1 tasks complete.
4/4 Phase 2 tasks complete.
Combined: 11/17 total tasks complete (Phase 3 remains).
Ready for verify phase on Phase 2. PR #3 is Phase 3 (car field cleanup).
