# Design: QORA Cleanup & Documentation

## Technical Approach

Surgical cleanup: delete dead artifacts, rewire the system prompt path, harden the WS close handler, fix 3 test failures by removing Pydantic defaults, and add docs. Zero new features — every change makes the existing code more honest.

## Architecture Decisions

| # | Decision | Choice | Alternatives Rejected | Rationale |
|---|----------|--------|-----------------------|-----------|
| AD-1 | System prompt source | `webhook.py` imports `render_system_prompt()` from `app.prompts.insurance_agent` — replaces inline `_build_default_system_prompt()` | (a) Keep both and pick at runtime (b) Move prompt into JSON config | `insurance_agent.py` already exists, is tested, and has the full Jaumpablo flow. One import eliminates 15 lines of dead code. JSON can't express the template logic (returning-caller context). |
| AD-2 | Agent config remains in DB, NOT JSON files | Keep `clients` table as canonical config. Do NOT create `backend/app/agents/configs/` directory or loader. | (a) JSON files in `configs/` dir | The `Client` model already has every field the spec lists (model, temperature, max_tokens, tools_enabled, voice_id, language via broker). `seed_quintana()` populates it. Adding a parallel JSON source creates two truths. Phase 1 multi-tenant can add a JSON import CLI later. |
| AD-3 | `client_id` required, no default | Remove `= "quintana-seguros"` default from `ElevenLabsExtraBody.client_id` and from the fallback chain in `custom_llm_webhook` | (a) Keep default for backwards compat | Tests expect 422 on missing `client_id`. Silent defaults mask misconfig in production. ElevenLabs always sends `elevenlabs_extra_body` if configured correctly. |
| AD-4 | WS 1006 handling | In `ws.onclose`, branch on `e.code`: 1000 → "Finalizada", else → "Se perdió la conexión" + reconnect button | (a) Auto-reconnect silently | User must see the disconnect and choose to retry. Auto-reconnect can loop on server-side errors. |
| AD-5 | Inline imports → module-level | Move `import structlog`, `import uuid` to top of `webhook.py`. Remove `import structlog as _sl` inside `custom_llm_webhook` and `generate()`. | (a) Leave as-is | PEP 8. Inline imports hide dependencies and break linting. |

## Data Flow

No changes to the core data flow. The only wiring change:

```
webhook.py::custom_llm_webhook
     │
     │  BEFORE: _build_default_system_prompt(client, lead)  ← inline, 6 lines
     │  AFTER:  render_system_prompt(client, lead)           ← from app.prompts.insurance_agent
     │
     ▼
OpenAIStreamingClient.stream_events(messages=[{system_prompt}, ...])
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/voice/webhook.py` | Modify | (1) Delete `debug-llm` endpoints (lines 85–100). (2) Delete `_build_default_system_prompt` (lines 523–536). (3) Replace call site with `render_system_prompt(client, lead)` import. (4) Move inline `import structlog`, `import uuid` to module-level. (5) Remove `= "quintana-seguros"` default from `ElevenLabsExtraBody.client_id`. (6) Remove fallback `or "quintana-seguros"` from client_id resolution chain (line 373). |
| `backend/app/voice/webhook.py` — `ElevenLabsExtraBody` | Modify | `client_id: str` (no default). `CustomLLMRequest.elevenlabs_extra_body` keeps `Field(default_factory=...)` but the factory now requires `client_id`. |
| `backend/app/prompts/insurance_agent.py` | No change | Already correct — `render_system_prompt(client, lead)` is ready. |
| `backend/app/static/index.html` | Modify | `ws.onclose`: branch on `e.code === 1000` vs else. Add reconnect button that calls `startConversation()` and self-removes. |
| `backend/agents/configs/sales-agent-01.json` | Delete | V1 dead config. |
| `backend/test_output/` | Delete | 3 MP3 artifacts, not source. |
| `backend/callcenter.db` | Delete | Stale V1 database. |
| `backend/fallback_audio/` | Delete | Contains only a README placeholder. |
| `backend/tests/test_spec_coverage.py` | No change | Test at line 82 already expects `ValidationError` on `ElevenLabsExtraBody()` — will PASS once default is removed. |
| `backend/tests/integration/voice/test_custom_llm.py` | No change | Tests at lines 197 and 222 already expect 422 — will PASS once default is removed. |
| `docs/architecture.md` | Create | Component diagram, data flow (UI → ElevenLabs → webhook → GPT-4o → tools). |
| `docs/running-locally.md` | Create | Env vars, `uvicorn`, ngrok steps. |
| `README.md` | Modify | Rewrite for QORA (remove Twilio/V1 references). |

## Interfaces / Contracts

```python
# webhook.py — ElevenLabsExtraBody AFTER cleanup
class ElevenLabsExtraBody(BaseModel):
    client_id: str                        # REQUIRED, no default
    lead_id: str | None = None
    conversation_id: str | None = None
```

```python
# webhook.py — system prompt wiring AFTER cleanup
from app.prompts.insurance_agent import render_system_prompt

system_content = (
    client.system_prompt_override
    if client.system_prompt_override is not None
    else render_system_prompt(client, lead)
)
```

```javascript
// index.html — ws.onclose AFTER cleanup
ws.onclose = (e) => {
  if (e.code === 1000) {
    setStatus('Conversación finalizada', '');
  } else {
    setStatus('Se perdió la conexión', 'error');
    const btn = document.createElement('button');
    btn.className = 'btn btn-primary';
    btn.textContent = '🔄 Reconectar';
    btn.onclick = () => { btn.remove(); startConversation(); };
    document.querySelector('.status-bar').appendChild(btn);
  }
  cleanup();
};
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `ElevenLabsExtraBody()` raises `ValidationError` | Existing test (`test_spec_coverage.py:82`) — now passes |
| Integration | Missing `client_id` → 422 | Existing tests (`test_custom_llm.py:197,222`) — now pass |
| Integration | `render_system_prompt` is called (not inline builder) | Add assertion: mock `render_system_prompt`, verify it was called during webhook request |
| Manual | WS 1006 reconnect button | Kill ngrok mid-conversation, verify red dot + reconnect button appears |
| Manual | WS 1000 clean close | End conversation normally, verify "Finalizada" with no reconnect button |

## Migration / Rollout

No migration required. All changes are backwards-compatible deletions and rewirings. The DB schema (`clients` table) is untouched. `qora.db` is not modified.

## Open Questions

- [x] ~~Do we need `backend/app/agents/configs/` JSON files?~~ → **No.** DB `clients` table is already the canonical source (AD-2).
- [ ] Should `ElevenLabsExtraBody` require `conversation_id` too? Current: optional. Recommend keeping optional — ElevenLabs may not always send it.
