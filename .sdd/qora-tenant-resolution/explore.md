# Exploration: Tenant Resolution in Custom-LLM Webhook Flow

## Problem (Plain English)

QORA's voice pipeline has a broken link. When a user calls through ElevenLabs, the flow goes:

1. **Frontend** opens a WebSocket to ElevenLabs, sending `dynamic_variables` (including `client_id`) in the initial handshake.
2. **ElevenLabs** calls our **initiation webhook** (`POST /voice/initiation?client_id=quintana-seguros`) -- this works fine (200 OK).
3. **ElevenLabs** then calls our **custom-LLM webhook** (`POST /voice/custom-llm/chat/completions`) for each chat turn -- but this request arrives with `client_id: null`.
4. Backend returns **422 "client_id is required"** -- ElevenLabs closes the WebSocket with code 1002 -- the call dies.

**Root cause**: ElevenLabs does NOT forward `dynamic_variables` from the initiation response to the custom-LLM request body. The `elevenlabs_extra_body` mechanism requires a dashboard toggle ("Custom LLM Extra Body") that ElevenLabs' current UI (April 2026) does not visibly expose. The keys (`client_id`, `lead_id`, `conversation_id`) arrive in the body but with `null` values -- EL sends the schema shape but has no values to populate.

**Historical context**: In Phase 0, this worked because the webhook had a hardcoded fallback: `or _default_client_id` which resolved to `"quintana-seguros"`. The Phase 1 "Judgment Day" hardening commit (`0d250fc`) correctly removed this fallback for multi-tenant safety, but didn't account for EL's inability to pass `client_id` through the custom-LLM body.

## Current Flow (Where client_id Gets Lost)

```
                                    client_id OK here
                                         |
  Frontend (browser)                     v
  ┌──────────────┐    WS connect    ┌──────────────┐
  │  index.html  │ ───────────────> │  ElevenLabs  │
  │              │  sends:          │   Platform   │
  │              │  dynamic_vars {  │              │
  │              │    client_id:    │              │
  │              │    "quintana-    │              │
  │              │     seguros"    │              │
  │              │  }              │              │
  └──────────────┘                  └──────┬───────┘
                                           │
                    ┌──────────────────────-┤
                    │                       │
                    v                       v
         POST /voice/initiation    POST /voice/custom-llm/
         ?client_id=quintana-      chat/completions
         seguros                   
         ┌─────────────────┐       ┌──────────────────────┐
         │  200 OK         │       │ Body:                │
         │  dynamic_vars   │       │ {                    │
         │  returned       │       │   "model": "gpt-4o", │
         │                 │       │   "messages": [...],  │
         │  client_id      │       │   "elevenlabs_extra_ │
         │  resolved from  │       │    body": {          │
         │  query param    │       │     "client_id": null│ <-- LOST!
         └─────────────────┘       │     "lead_id": null  │
                                   │   },                 │
              THIS WORKS ✓         │   "client_id": null  │ <-- ALSO null
                                   │ }                    │
                                   └──────────────────────┘
                                          │
                                          v
                                   422 "client_id is
                                    required" ✗
                                          │
                                          v
                                   EL closes WS (1002)
                                   custom_llm_error
```

**The gap**: There is NO mechanism in ElevenLabs' current platform to pass data from the initiation webhook response (or from `dynamic_variables`) into the custom-LLM HTTP request body. The `customLlmExtraBody` feature requires explicit dashboard configuration that the EL UI doesn't currently expose as a toggle.

## Current State

### Files Involved

| File | Role |
|------|------|
| `backend/app/voice/webhook.py` | Custom-LLM endpoint. Resolves `client_id` from `elevenlabs_extra_body` -> top-level field -> `model_extra`. Returns 422 if all are null. |
| `backend/app/voice/initiation.py` | Initiation webhook. Resolves `client_id` from query param `?client_id=...` or body. Works correctly. |
| `backend/app/static/index.html` | Frontend demo. Sends `client_id` as a `dynamic_variable` in the WS handshake. Also the initiation URL includes `?client_id=...` as a query param. |
| `backend/app/voice/filler.py` | In-memory `SessionStore` keyed by `conversation_id`. Stores `client_id` once a session is created. |
| `backend/app/tenants/models.py` | `Client` model. No `elevenlabs_agent_id` field currently. |
| `backend/app/core/config.py` | Settings. Has `elevenlabs_agent_id` (global, single-agent). No `default_client_id` anymore. |
| `backend/app/calls/models.py` | `CallSession` model. Has `elevenlabs_conversation_id` (nullable). |

### How It Used to Work (Phase 0)

```python
# Phase 0 — webhook.py line 348-358 (commit 6d76ecf)
try:
    _default_client_id = request.app.state.settings.default_client_id
except AttributeError:
    _default_client_id = "quintana-seguros"

client_id = (
    extra.client_id
    or body.client_id
    or (body.model_extra or {}).get("client_id")
    or _default_client_id  # <-- THIS was the safety net
)
```

This was a single-tenant hack. Phase 1 correctly removed it for multi-tenant support, but the replacement mechanism (EL `customLlmExtraBody`) doesn't actually work with EL's current UI.

## Approaches Evaluation

### Option A: Tenant in URL Path

**Mechanism**: Change custom-LLM URL from `/voice/custom-llm/chat/completions` to `/voice/{client_id}/chat/completions`.

Each ElevenLabs agent is configured with a tenant-specific URL:
- Agent for Quintana Seguros: `https://qora.example.com/api/v1/voice/quintana-seguros/chat/completions`
- Agent for Demo Inmobiliaria: `https://qora.example.com/api/v1/voice/demo-inmobiliaria/chat/completions`

Backend extracts `client_id` from the URL path parameter. Zero dependency on EL body fields.

| Dimension | Assessment |
|-----------|------------|
| **Pros** | No dashboard toggle needed. Explicit per-agent routing. Dead simple implementation. Works with any EL version. Self-documenting URLs. |
| **Cons** | Requires updating the Custom LLM URL in EL dashboard per agent (one-time config). Changes public URL shape. Old URL becomes a 422. |
| **Effort** | **Low** (add path param to route decorator, extract in handler, ~15 lines changed) |
| **Risk** | **Very Low** -- path params are FastAPI's strongest pattern. Old routes can coexist during migration. |
| **Multi-tenant** | Fully scalable -- each new client just needs a new EL agent with its own URL. |
| **Reliability** | 10/10 -- URL path is the most reliable data channel; never lost, never null. |

### Option B: agent_id -> client_id Mapping

**Mechanism**: ElevenLabs sends `agent_id` somewhere in the custom-LLM payload. Backend maintains a `agent_id -> client_id` lookup table.

| Dimension | Assessment |
|-----------|------------|
| **Pros** | Zero dashboard config after initial mapping. Auto-discovery possible. |
| **Cons** | **BLOCKER**: EL does NOT send `agent_id` in the custom-LLM HTTP body. The structlog output shows body keys: `["model", "messages", "stream", "temperature", "max_tokens", "tools", "elevenlabs_extra_body", "client_id", "lead_id", "conversation_id", "stream_options"]` -- no `agent_id`. Would need a DB table + migration. Coupling between EL agent IDs and tenant identity. |
| **Effort** | **Medium** (new DB table, migration, seed logic, lookup on every request) |
| **Risk** | **High** -- based on an UNVERIFIED assumption that agent_id arrives in the body. If it doesn't, this approach is dead. |
| **Multi-tenant** | Scales, but requires maintaining a mapping table per deployment. |
| **Reliability** | 3/10 -- depends on EL sending data they may not send. |

### Option C: Session-Based Resolution via conversation_id

**Mechanism**: When initiation fires (with `client_id` in query param), cache `conversation_id -> client_id` in memory. When custom-LLM fires, look up by `conversation_id`.

| Dimension | Assessment |
|-----------|------------|
| **Pros** | Transparent to dashboard. Works with existing EL flow (initiation already works). Leverages existing `SessionStore`. |
| **Cons** | **BLOCKER**: `conversation_id` arrives as `null` in the custom-LLM body (confirmed in logs: `"conversation_id": null`). EL does NOT forward the conversation ID from WS to the HTTP custom-LLM call. Without a `conversation_id`, there's no key to look up. The initiation webhook also doesn't receive a `conversation_id` -- it returns *before* EL assigns one. |
| **Effort** | **Low** if conversation_id was available (just a dict lookup) |
| **Risk** | **FATAL** -- the premise is broken. conversation_id is null on the custom-LLM call. |
| **Multi-tenant** | Would scale if it worked. |
| **Reliability** | 0/10 -- key data is null. |

### Option D: Default Tenant Fallback (Single-Tenant)

**Mechanism**: If `client_id` is null and the DB has only one active client, use it as the default.

| Dimension | Assessment |
|-----------|------------|
| **Pros** | Works immediately for single-tenant demo. Zero config. Backward-compatible. |
| **Cons** | Doesn't scale past one client. Hides the real problem. Contradicts Phase 1's explicit design decision to REMOVE this exact pattern. Query-per-request to count clients. |
| **Effort** | **Very Low** (~5 lines) |
| **Risk** | **Medium** -- tactical debt that will bite when adding client #2. |
| **Multi-tenant** | Does not scale. By definition. |
| **Reliability** | 7/10 for single-tenant, 0/10 for multi-tenant. |

### Option E: Frontend-Mediated Signed URL

**Mechanism**: Frontend requests a signed URL from backend that embeds `client_id` in a JWT or query param. Backend resolves tenant on custom-LLM call via that token.

| Dimension | Assessment |
|-----------|------------|
| **Pros** | Clean separation of concerns. Cryptographic tenant binding. |
| **Cons** | **BLOCKER**: The signed URL flow generates a WS URL to ElevenLabs (`wss://api.elevenlabs.io/...`). ElevenLabs then makes an HTTP call to OUR custom-LLM URL. There is NO mechanism to pass a header/cookie/token from the frontend's signed URL to EL's outbound HTTP call to our backend. EL controls that HTTP request entirely. |
| **Effort** | **High** (JWT generation, validation, new endpoint, complex flow) |
| **Risk** | **FATAL** -- the transport channel doesn't exist. |
| **Multi-tenant** | Theoretically scalable, but technically impossible with EL's architecture. |
| **Reliability** | 0/10 -- can't bridge the gap. |

## Comparison Table

| Option | Works Now | Multi-Tenant | Effort | Risk | Reliability | Recommendation |
|--------|-----------|-------------|--------|------|-------------|----------------|
| **A: URL Path** | Yes | Yes | Low | Very Low | 10/10 | **RECOMMENDED** |
| **B: agent_id map** | Unverified | Yes | Medium | High | 3/10 | Needs verification |
| **C: conversation_id** | No | Would | Low | Fatal | 0/10 | BLOCKED (null) |
| **D: Default fallback** | Single only | No | Very Low | Medium | 7/10 | Tactical only |
| **E: Signed URL** | No | Would | High | Fatal | 0/10 | BLOCKED (no channel) |

## Recommendation: Option A (Tenant in URL Path)

### Why Option A is the clear winner:

1. **It's the only approach that works with 100% certainty today**. URL path parameters are the most reliable data channel in HTTP -- they cannot be null, cannot be stripped, cannot be misconfigured by a third party.

2. **Zero dependency on ElevenLabs' feature roadmap**. We stop relying on EL's dashboard toggles, body forwarding behavior, or conversation ID propagation. Our routing is self-contained.

3. **Minimal implementation effort**. The change is roughly:
   ```python
   # FROM:
   @router.post("/custom-llm/chat/completions")
   async def custom_llm_webhook(body: CustomLLMRequest, request: Request):
       client_id = extra.client_id or body.client_id or ...  # all null
   
   # TO:
   @router.post("/{client_id}/chat/completions")
   async def custom_llm_webhook(client_id: str, body: CustomLLMRequest, request: Request):
       # client_id guaranteed by URL routing -- never null
   ```

4. **Natural multi-tenant scaling**. Each ElevenLabs agent gets its own URL. Adding a client is: (1) create DB record, (2) set URL in EL dashboard. No code deploy.

5. **Backward-compatible rollout**. Keep old routes temporarily with deprecation warnings. New route works immediately.

6. **The initiation webhook ALREADY does this** -- it accepts `client_id` as a query param. Option A is the same pattern applied to the custom-LLM webhook.

### Implementation sketch for Option A

1. Add new route: `@router.post("/{client_id}/chat/completions")`
2. Keep old routes with fallback logic (try body first, then 422 with helpful error message pointing to new URL)
3. Validate `client_id` against DB (existing `get_client()` call)
4. Update ElevenLabs dashboard: set Custom LLM URL to `https://qora.example.com/api/v1/voice/quintana-seguros/chat/completions`
5. Update initiation webhook URL pattern to match: `https://qora.example.com/api/v1/voice/initiation?client_id=quintana-seguros` (already works this way)

### What about Option D as an interim fix?

Option D (single-tenant fallback) could be a **5-minute tactical fix** while Option A is implemented properly. But given Option A is also ~30 minutes of work, I'd go straight to Option A to avoid the tech debt.

## Key Unknowns / Assumptions to Verify

| # | Unknown | Impact | How to Verify |
|---|---------|--------|---------------|
| 1 | Does EL send `agent_id` anywhere in the custom-LLM body? | Would make Option B viable as a complement | Add logging for ALL request headers + full body dump on next test call |
| 2 | Does EL ever populate `conversation_id` in custom-LLM body? | Would make Option C viable | Same logging -- check headers too (e.g. `X-ElevenLabs-Conversation-Id`) |
| 3 | Does changing the custom-LLM URL to include a path segment break EL's `/chat/completions` suffix appending? | Could break Option A | Test: set EL base URL to `https://host/api/v1/voice/quintana-seguros` -- EL should append `/chat/completions` to make `https://host/api/v1/voice/quintana-seguros/chat/completions` |
| 4 | Are there existing EL agents in production pointing to the old URL? | Migration coordination needed | Check EL dashboard |

**Unknown #3 is the only real risk for Option A**, and it's trivially verifiable with one test call. ElevenLabs documentation states they append `/chat/completions` to whatever base URL you provide, so setting the base URL to `.../voice/quintana-seguros` should produce `.../voice/quintana-seguros/chat/completions` -- which matches our new route.

## Risks

- **Option A only risk**: If ElevenLabs does NOT cleanly append `/chat/completions` to a URL that already has path segments, the URL might get mangled. Mitigation: register multiple route patterns (with and without the suffix).
- **General risk**: Any solution that depends on ElevenLabs' undocumented behavior (Options B, C, E) is fragile and will break without warning when EL updates their platform.

## Ready for Proposal

**Yes** -- Option A is well-understood, low-effort, and has a clear implementation path. The proposal should cover:
1. New URL pattern with FastAPI path param
2. Backward-compatible old routes (deprecation period)
3. EL dashboard configuration change (one-time per agent)
4. Updated initiation URL to use same pattern (optional, already works with query params)
