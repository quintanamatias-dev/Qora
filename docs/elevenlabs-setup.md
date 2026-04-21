# ElevenLabs Agent Setup

How to configure a new ElevenLabs Conversational AI agent to route through QORA's multi-tenant backend.

## Prerequisites

- ngrok tunnel (or public HTTPS endpoint) pointing to your QORA backend on port 8000
- An ElevenLabs account + agent created at https://elevenlabs.io/app/agents
- A registered client (tenant) in QORA — see `backend/clients/{client_id}/`

## Dashboard Configuration

### 1. Custom LLM URL

Navigate to your agent → **LLM** panel → **URL del servidor** (Server URL).

**URL template** (REPLACE `<tenant>` with your client_id):

```
https://<YOUR-NGROK-SUBDOMAIN>.ngrok-free.dev/api/v1/voice/<tenant>/custom-llm
```

Example for `quintana-seguros`:

```
https://bristol-unedacious-carmelina.ngrok-free.dev/api/v1/voice/quintana-seguros/custom-llm
```

**Important**: DO NOT include `/chat/completions` at the end — ElevenLabs appends it automatically.

- **ID del modelo**: `gpt-4o` (or whatever model your backend is configured for)
- **Clave de API**: any placeholder (e.g., `dummy-key`) — the backend uses its own OpenAI key

### 2. Initiation Webhook

Navigate to the **Security / Anulación de webhook de datos de inicio** section.

**URL template**:

```
https://<YOUR-NGROK-SUBDOMAIN>.ngrok-free.dev/api/v1/voice/initiation?client_id=<tenant>&lead_id={{lead_id}}
```

The `{{lead_id}}` placeholder is filled by ElevenLabs from the conversation's dynamic_variables when the call is initiated.

### 3. Post-Call Webhook (optional but recommended for Phase 2 memory)

Navigate to the **Webhook posterior a la llamada** section.

```
https://<YOUR-NGROK-SUBDOMAIN>.ngrok-free.dev/api/v1/calls/elevenlabs-postcall
```

## How memory reaches the agent

The agent's system prompt includes memory placeholders:
- `{{call_history}}` — up to 3 prior call summaries
- `{{confirmed_facts}}` — extracted facts like current insurance, interest level, suggested action
- `{{is_returning_caller}}` — `"true"` if the lead has at least one completed session
- `{{call_number}}` — the number of this call for the lead (1 = first)

These are populated by the BACKEND at custom-LLM render time. Every time ElevenLabs calls the custom-LLM webhook, the `PromptLoader` queries the database for the lead's history and substitutes the placeholders.

### Why memory is populated at render time, not via ElevenLabs

ElevenLabs' `conversation_initiation_client_data.dynamic_variables` is one way to pass variables to the agent prompt. The backend also exposes an `/api/v1/voice/initiation` webhook that ElevenLabs calls for Twilio/SIP inbound flows.

However, in the WebSocket-direct flow (browser demo, web widget), ElevenLabs does NOT call the initiation webhook — it uses only the `dynamic_variables` the client sends in the WebSocket message. Since we don't want the browser to have direct access to the database, we populate memory on the backend at render time. This ensures memory is available regardless of which flow brings the conversation into the agent.

### What each flow uses

| Flow | Initiation webhook called? | Memory source |
|------|---------------------------|---------------|
| Browser WebSocket (demo) | No | Backend render via `build_memory_context` |
| Widget embedded in website | No | Backend render via `build_memory_context` |
| Twilio inbound | Yes | Initiation webhook response (same `build_memory_context`) |
| SIP trunk inbound | Yes | Initiation webhook response (same `build_memory_context`) |

Both paths ultimately use the SAME `build_memory_context()` function in `backend/app/memory.py`, so memory is consistent across flows.

## Session Continuity & `custom_llm_extra_body`

QORA passes a minimal metadata object from the frontend to ElevenLabs that gets forwarded to every custom-LLM request. This links each conversation turn back to the correct Lead for memory persistence and analytics.

### How it works

1. **Frontend → ElevenLabs (WebSocket)**: When the browser opens the WS to EL, it sends a `conversation_initiation_client_data` message. This message includes a `custom_llm_extra_body` field:

   ```json
   {
     "type": "conversation_initiation_client_data",
     "dynamic_variables": { ... },
     "custom_llm_extra_body": {
       "lead_id": "lead-quintana-001"
     }
   }
   ```

   NOTE: We do NOT include `client_id` in `custom_llm_extra_body` — it's already carried via the Custom LLM URL path (`/api/v1/voice/{client_id}/custom-llm`). Sending it twice would trigger a `client_id_mismatch` warning on every request.

2. **ElevenLabs → Custom LLM**: EL forwards `custom_llm_extra_body` as `elevenlabs_extra_body` in every OpenAI-format request it sends to your custom LLM endpoint. The backend reads it to populate `CallSession.lead_id`.

3. **Frontend → /end**: When the call ends, the browser POSTs to `/api/v1/calls/{conversation_id}/end` with `client_id` and `lead_id` in the body. These allow the backend to reconcile orphan sessions if the `conversation_id` doesn't match (for example, if EL generates the conversation_id AFTER the initial handshake).

### Reconciliation fallback

If `/end` receives a `conversation_id` that isn't persisted on any CallSession, the backend falls back to a reconciliation lookup:

- Match on `(client_id, lead_id)` from the request body
- Look for an "initiated" session with NULL `elevenlabs_conversation_id` started within the last 120 seconds
- Match found → complete that session in-place and emit `end_session_reconciled` log event
- No match → return 404 as before

This is a safety net; under normal operation the `conversation_id` is already persisted at custom-LLM time.

### References

- [ElevenLabs Custom LLM docs](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm)
- [WebSocket API reference — `conversation_initiation_client_data`](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket)

## Common Gotchas

- **ngrok URL changes on restart**: The free ngrok tier assigns a new subdomain every session. Update both URLs above when you restart ngrok, OR use a fixed subdomain with `ngrok http 8000 --domain=your-fixed.ngrok-free.dev`.
- **HTTPS required**: ElevenLabs rejects `http://` URLs. Must be `https://`.
- **No `/chat/completions` suffix on Custom LLM URL**: ElevenLabs appends it automatically. If you include it, the path becomes `/chat/completions/chat/completions` → 404.
- **Legacy URL still works**: `https://<subdomain>/api/v1/voice/custom-llm/chat/completions` with `elevenlabs_extra_body.client_id` set. Logs `custom_llm_legacy_route_used` warning. Plan to migrate.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `custom_llm_error: Failed to generate response` on WebSocket close | Dashboard URL is wrong or backend not reachable | Verify `curl https://<subdomain>/api/v1/health` returns 200 |
| `POST /voice/<tenant>/custom-llm/chat/completions 404` in ngrok | Tenant not registered in `backend/clients/` | Add the client config and restart backend |
| `POST ... 403 "Tenant disabled"` | Tenant exists but `is_active=False` | Update the Client record to `is_active=True` |
| Initiation returns 422 | Missing `client_id` query param in dashboard URL | Ensure URL includes `?client_id=<tenant>` |
