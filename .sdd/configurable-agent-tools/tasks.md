# Tasks: Configurable Agent Tools

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 850-1,100 total |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 capture_data + tool_config → PR 2 analysis status transitions → PR 3 cleanup |
| Delivery strategy | auto-forecast |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Add `capture_data` and `Agent.tool_config` without removing legacy tools | PR 1 | ~430-520 lines; deployable with Quintana dual-run |
| 2 | Move terminal statuses to analysis and remove legacy dispatch/defaults | PR 2 | ~280-360 lines; depends on PR 1 |
| 3 | Remove car-specific context and mark legacy fields deprecated | PR 3 | ~140-220 lines; depends on PR 2 |

## Phase 1: Add capture_data + tool_config

- [x] 1.1 RED: add `backend/tests/unit/agents/test_schemas.py` cases for `tool_config` create/update/response, valid `capture_data`, and invalid JSON; deps: none; est. 45 lines.
- [x] 1.2 GREEN: update `backend/app/tenants/models.py`, `backend/app/agents/schemas.py`, and agent service/router serialization for nullable JSON `tool_config`; deps: 1.1; est. 80 lines.
- [x] 1.3 RED: add `backend/tests/unit/tools/test_capture_data.py` for required fields, optional omission, not-found, cross-tenant, atomic writes, and no status changes; deps: 1.2; est. 120 lines.
- [x] 1.4 GREEN: create `backend/app/tools/capture_data.py` writing `LeadProfileFact` rows with `captured:{field}` keys; deps: 1.3; est. 130 lines.
- [x] 1.5 RED/GREEN: extend `backend/tests/unit/tools/test_registry.py`, `test_dispatcher.py`, and `test_context.py`; then update `registry.py`, `dispatcher.py`, `voice/context.py`, and `voice/webhook.py` to inject agent config; deps: 1.4; est. 170 lines.
- [x] 1.6 RED/GREEN: update `test_get_lead_details.py`, `test_initiation.py`, `get_lead_details.py`, and `voice/initiation.py` so call count moves to initiation; deps: none; est. 110 lines.
- [x] 1.7 RED/GREEN: add Quintana parity seed/config tests in `backend/tests/test_qora_demo_seed.py`; update `backend/app/tenants/service.py`; deps: 1.5; est. 90 lines.

## Phase 2: Analysis-driven status transitions

- [ ] 2.1 RED: add summarizer lifecycle tests covering positive, negative, follow-up, retry/human-review, and terminal-state no-op in `backend/tests/unit/test_summarizer.py`; deps: Phase 1; est. 130 lines.
- [ ] 2.2 GREEN: add next-action status mapping in `backend/app/summarizer.py` using `transition_lead_status` only when lead status is `called`; deps: 2.1; est. 90 lines.
- [ ] 2.3 RED/GREEN: update dispatcher/registry/schema tests, then remove legacy tools from `TOOL_DEFINITIONS`, defaults, and `_TOOL_REGISTRY`; return `tool_removed` for old calls; deps: 2.2; est. 140 lines.
- [ ] 2.4 REFACTOR: add deprecation warnings/auto-strip handling in `backend/app/agents/schemas.py` and affected tests; deps: 2.3; est. 70 lines.

## Phase 3: Legacy cleanup

- [ ] 3.1 RED/GREEN: update `backend/tests/unit/voice/test_context.py`, `test_initiation_context.py`, and `test_loader.py`; remove car fields from lead context, dynamic variables, and prompt substitutions; deps: Phase 2; est. 150 lines.
- [ ] 3.2 RED/GREEN: mark `Lead.car_*` fields deprecated in `backend/app/leads/models.py` and ensure serializers remain backward-compatible; deps: 3.1; est. 60 lines.
- [ ] 3.3 VERIFY: run `cd backend && python3 -m pytest tests/ -q` after each phase and update this task file checkboxes during apply; deps: each phase; est. 20 lines.
