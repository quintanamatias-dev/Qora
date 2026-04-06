# Proposal: QORA Cleanup & Documentation

## Intent

Phase 0 is working but the codebase carries V1 legacy artifacts, disconnected modules, and zero documentation. Before Phase 1 (real outbound calls) we need a clean, understandable, maintainable foundation. This is a technical debt + knowledge-transfer change.

## Scope

### In Scope
- Remove all dead code and test artifacts from V1 era
- Unify agent configuration: one canonical location, actually wired to runtime
- Polish WebSocket demo UI (1006 disconnect handling)
- Replace README.md and create `docs/architecture.md` + `docs/running-locally.md`
- Fix 3 pre-existing test failures; update tests referencing old arch
- Archive completed `.sdd` change folders (qora-prd, qora-phase0, fix-web-demo, elevenlabs-conversational)

### Out of Scope
- Phase 1 features (outbound dialing, campaign management)
- ElevenLabs agent config changes
- Any new capability development

## Capabilities

### New Capabilities
- `agent-config`: Canonical per-client agent configuration loaded at runtime from `backend/app/agents/configs/`

### Modified Capabilities
- None (pure cleanup + new documentation; no existing spec-level behavior changes)

## Approach

**Dead code removal** — straight deletes: `agents/configs/sales-agent-01.json`, `debug_llm` endpoint, inline imports in `webhook.py`, `test_output/`, `callcenter.db`, empty `fallback_audio/`.

**Agent config unification** — move config to `backend/app/agents/configs/quintana-seguros.json`. Refactor `webhook.py` to load system prompt from `insurance_agent.py` via the config loader instead of hardcoding it inline.

**WebSocket UI** — add a graceful 1006 reconnect/notify flow in `backend/app/static/`.

**Docs** — write three documents: updated README (what QORA is), `docs/architecture.md` (component diagram + data flow), `docs/running-locally.md` (env vars, dev server, ngrok).

**Tests** — audit `backend/tests/`, fix failing assertions, update path references to old `agents/configs/`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/agents/configs/sales-agent-01.json` | Removed | Dead V1 agent config |
| `backend/app/voice/webhook.py` | Modified | Remove `debug_llm`, fix inline imports, wire system prompt |
| `backend/app/prompts/insurance_agent.py` | Modified | Actually imported and used by webhook |
| `backend/app/agents/configs/` | New | Canonical agent config directory |
| `backend/test_output/` | Removed | Test MP3 artifacts |
| `backend/callcenter.db` | Removed | Stale V1 database |
| `backend/fallback_audio/` | Removed | Empty placeholder |
| `backend/README.md` | Modified | Rewritten for QORA |
| `docs/` | New | `architecture.md` + `running-locally.md` |
| `backend/tests/` | Modified | Fix 3 failures, update arch references |
| `.sdd/` | Modified | Archive 4 completed change folders |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Prompt refactor breaks live webhook | Med | Test webhook locally with ngrok before merging |
| Removing `callcenter.db` loses data needed by someone | Low | It's V1 only; qora.db is current |
| Test fixes introduce regressions | Low | Run full suite before and after each fix |

## Rollback Plan

All deletions are from git history. `git revert` or restore from last commit. The `insurance_agent.py` prompt is already written — reverting webhook.py to inline prompt is a one-line change.

## Dependencies

- No external dependencies
- Requires active `qora.db` to stay untouched

## Success Criteria

- [ ] `pytest backend/tests/` passes with 0 failures
- [ ] `webhook.py` has no inline imports and no `debug_llm` endpoint
- [ ] `insurance_agent.py` is imported and used by the webhook at runtime
- [ ] `backend/app/agents/configs/quintana-seguros.json` is the single agent config source
- [ ] `docs/architecture.md` and `docs/running-locally.md` exist and are accurate
- [ ] README.md describes QORA, not Twilio V1
- [ ] No V1 artifacts remain (`sales-agent-01.json`, `test_output/`, `callcenter.db`, `fallback_audio/`)
- [ ] `.sdd/` archived folders are marked complete
