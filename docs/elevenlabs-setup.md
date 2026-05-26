# ElevenLabs Agent Setup

How to configure a new ElevenLabs ElevenAgents agent to route through QORA's multi-tenant backend.

## Prerequisites

- ngrok tunnel (or public HTTPS endpoint) pointing to your QORA backend on port 8000
- An ElevenLabs account + agent created at https://elevenlabs.io/app/agents
- A registered client (tenant) in QORA — see `backend/clients/{client_id}/`
- An ElevenLabs API key configured in the backend when using programmatic sync

## Dashboard Configuration

### 1. Custom LLM URL

Navigate to your agent → **LLM** panel → **URL del servidor** (Server URL).

**URL template** (REPLACE `<tenant>` with your client_id):

```text
https://<YOUR-NGROK-SUBDOMAIN>.ngrok-free.dev/api/v1/voice/<tenant>/custom-llm
```

Example for `quintana-seguros`:

```text
https://bristol-unedacious-carmelina.ngrok-free.dev/api/v1/voice/quintana-seguros/custom-llm
```

**Important**: DO NOT include `/chat/completions` at the end — ElevenLabs appends it automatically for Chat Completions.

- **ID del modelo**: `gpt-4o` (or whatever model your backend is configured for)
- **Clave de API**: any placeholder (e.g., `dummy-key`) — the backend uses its own OpenAI key
- **API format**: Chat Completions today; ElevenLabs also supports Responses API (`/v1/responses`) when the backend endpoint implements it

### 2. Conversation behavior

Configure turn behavior in the agent dashboard:

| Setting | Recommended Qora usage |
|---------|------------------------|
| `turn_timeout` | Use `1`-`30` seconds depending on channel. Phone usually tolerates shorter waits than web demos. |
| `soft_timeout_config.timeout_seconds` | Use `0.5`-`8.0` seconds; disabled default is `-1`. |
| `soft_timeout_config.message` | Short presence message like "Sigo acá" or tenant-specific copy. |
| `soft_timeout_config.use_llm_generated_message` | Use `false` for deterministic regulated flows; `true` for warmer agents. |
| `turn_eagerness` | `patient`, `normal`, or `eager`. Start with `normal`; use `patient` for consultative flows. |

### 3. Background audio

Background music is supported through `conversation_config.conversation.background_music`.

Qora production baseline:

```json
{
  "source_type": "preset",
  "source_id": "office1",
  "volume": 0.15,
  "crossfade_loop": true
}
```

The documented default volume is `0.6`, but Qora uses `0.15` to avoid fighting the agent voice. Configure per tenant/agent; do not mix ambient audio in the browser unless there is a product reason to bypass ElevenLabs mixing.

### 4. Initiation Webhook

Navigate to the **Security / Anulación de webhook de datos de inicio** section.

**URL template**:

```text
https://<YOUR-NGROK-SUBDOMAIN>.ngrok-free.dev/api/v1/voice/initiation?client_id=<tenant>&lead_id={{lead_id}}
```

The `{{lead_id}}` placeholder is filled by ElevenLabs from the conversation's dynamic_variables when the call is initiated.

### 5. Post-Call Webhook (optional but recommended for Phase 2 memory)

Navigate to the **Webhook posterior a la llamada** section.

```text
https://<YOUR-NGROK-SUBDOMAIN>.ngrok-free.dev/api/v1/calls/elevenlabs-postcall
```

## Programmatic agent configuration via Qora backend

Qora has an ElevenLabs provisioning service at `backend/app/elevenlabs/service.py` with models in `backend/app/elevenlabs/models.py`.

Current implemented sync:

- `ElevenLabsService.sync_soft_timeout(agent)` sends a partial PATCH to `https://api.elevenlabs.io/v1/convai/agents/{agent_id}`.
- It only sends `conversation_config.turn.soft_timeout_config`.
- It skips agents without `elevenlabs_agent_id`.
- It skips when all soft timeout fields are `None`.
- It retries once on 5xx and returns `SyncResult` instead of raising.

Payload shape currently implemented:

```json
{
  "conversation_config": {
    "turn": {
      "soft_timeout_config": {
        "timeout_seconds": 2.5,
        "message": "Sigo acá.",
        "use_llm_generated_message": false
      }
    }
  }
}
```

Important: background audio is confirmed in ElevenLabs and used in production, but `backend/app/elevenlabs/service.py` currently only implements soft timeout sync. Add a dedicated PATCH builder before claiming backend-managed background music for all tenants.

Recommended next provisioning fields:

- `conversation_config.conversation.background_music`
- `conversation_config.turn.turn_timeout`
- `conversation_config.turn.turn_eagerness`
- `conversation_config.agent.prompt.knowledge_base`
- system tools configured per tenant/agent

## Knowledge base setup

ElevenAgents can attach KB documents to the agent prompt.

Supported sources:

- Files: PDF, TXT, DOCX, HTML, EPUB.
- URLs.
- Raw text.

Limits for non-enterprise accounts: 20MB or 300k characters.

API methods:

```python
client.conversational_ai.knowledge_base.documents.create_from_text(...)
client.conversational_ai.knowledge_base.documents.create_from_url(...)
client.conversational_ai.knowledge_base.documents.create_from_file(...)
```

Agent config path:

```json
{
  "conversation_config": {
    "agent": {
      "prompt": {
        "knowledge_base": [
          { "id": "kb_doc_id" }
        ]
      }
    }
  }
}
```

Use KB for relatively stable product/policy content. Keep lead-specific context in Qora memory/dynamic variables, not in global KB documents.

## System tools configuration for Custom LLM

Configure system tools in the ElevenLabs agent when the runtime should own call-level actions.

Tools to consider:

| Tool | Use in Qora |
|------|-------------|
| `end_call` | Let the agent end the call cleanly with reason/farewell. |
| `language_detection` | Switch language mid-call without custom routing. |
| `transfer_to_agent` | Handoff to another ElevenLabs AI agent. |
| `transfer_to_number` | Human handoff for phone flows. |
| `skip_turn` | Let user continue speaking without filler response. |
| `voicemail_detection` | Detect voicemail during outbound/phone flows. |

Custom LLM impact:

- ElevenLabs sends configured system tools as OpenAI-compatible entries in `tools`.
- Qora must preserve function-call semantics in the response.
- Tenant authorization still belongs in Qora: do not allow a tool result to perform business actions unless the tenant/agent is allowed to do it.

## Workflow configuration

Use Workflows for multi-step conversation flows that would otherwise become a fragile prompt.

Config path:

```json
{
  "conversation_config": {
    "workflow": {
      "nodes": [],
      "edges": []
    }
  }
}
```

Node types:

- start
- end
- subagent / override_agent
- dispatch tool
- agent transfer
- transfer to number

Edge types:

- forward
- backward
- unconditional
- LLM-condition
- expression-condition

Subagent nodes can override system prompt, LLM, voice, knowledge base and tools. Use this for clear stages like qualification → quote → objection handling → human handoff.

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

1. **Frontend → ElevenLabs (WebSocket)**: When the browser opens the WS to EL, it sends a `conversation_initiation_client_data` message. This message includes `dynamic_variables`, `custom_llm_extra_body`, and optionally `user_id`, `branch_id`, `environment`:

   ```json
   {
     "type": "conversation_initiation_client_data",
     "dynamic_variables": {
       "lead_id": "lead-quintana-001"
     },
     "custom_llm_extra_body": {
       "lead_id": "lead-quintana-001"
     },
     "user_id": "lead-quintana-001",
     "branch_id": "experiment-branch-a",
     "environment": "production"
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

## Experiments and environments

ElevenLabs supports branch-based experiments with deterministic routing by conversation ID. Use this only with agent versioning enabled.

Fields to pass when needed:

- `branch_id` to force a specific experiment branch.
- `environment` to separate production/staging behavior.
- `user_id` for per-user tracking.

Experiments can cover prompt, workflow, voice, tools, KB, LLM, evaluation criteria and language.

## Privacy and analytics setup

Review these settings before production launch:

- Transcript retention.
- Audio retention and audio saving toggle.
- Conversation history redaction for enterprise tenants.
- Success Evaluation criteria.
- Data Collection fields to extract from transcript.
- Smart Search access permissions.

For GDPR/HIPAA-sensitive clients, do not rely on defaults. Document the tenant-level retention policy in Qora and in the ElevenLabs agent.

## Phone setup updates

Supported phone capabilities:

- Native Twilio integration.
- SIP trunk integration.
- Batch calls API for programmatic outbound calls.
- `transfer_to_number` for human handoff during calls.

For outbound/batch flows, configure voicemail handling before enabling production volume.

## CLI and SDKs

CLI:

```bash
elevenlabs agents pull --agent "<name>"
elevenlabs agents push --agent "<name>"
```

Use the CLI to inspect and promote agent config changes, but review generated files for secrets and environment-specific IDs before committing.

SDKs/integrations:

- React SDK.
- Swift SDK for iOS.
- Kotlin SDK for Android.
- React Native SDK.
- ElevenLabs UI component library based on shadcn.

## References

- [ElevenLabs Custom LLM docs](https://elevenlabs.io/docs/eleven-agents/customization/llm/custom-llm)
- [WebSocket API reference — `conversation_initiation_client_data`](https://elevenlabs.io/docs/eleven-agents/api-reference/eleven-agents/websocket)
- [Widget customization](https://elevenlabs.io/docs/eleven-agents/customization/widget)
- [Twilio integration](https://elevenlabs.io/docs/eleven-agents/phone-numbers/twilio)

## Common Gotchas

- **ngrok URL changes on restart**: The free ngrok tier assigns a new subdomain every session. Update URLs above when you restart ngrok, OR use a fixed subdomain with `ngrok http 8000 --domain=your-fixed.ngrok-free.dev`.
- **HTTPS required**: ElevenLabs rejects `http://` URLs. Must be `https://`.
- **No `/chat/completions` suffix on Custom LLM URL**: ElevenLabs appends it automatically for Chat Completions. If you include it, the path becomes `/chat/completions/chat/completions` → 404.
- **Responses API requires backend support**: Do not switch the dashboard to `/v1/responses` until Qora implements that endpoint.
- **Legacy URL still works**: `https://<subdomain>/api/v1/voice/custom-llm/chat/completions` with `elevenlabs_extra_body.client_id` set. Logs `custom_llm_legacy_route_used` warning. Plan to migrate.
- **System tools are real tools**: If enabled, they appear in `tools`; make sure the Custom LLM response path handles tool calls correctly.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `custom_llm_error: Failed to generate response` on WebSocket close | Dashboard URL is wrong or backend not reachable | Verify `curl https://<subdomain>/api/v1/health` returns 200 |
| `POST /voice/<tenant>/custom-llm/chat/completions 404` in ngrok | Tenant not registered in `backend/clients/` | Add the client config and restart backend |
| `POST ... 403 "Tenant disabled"` | Tenant exists but `is_active=False` | Update the Client record to `is_active=True` |
| Initiation returns 422 | Missing `client_id` query param in dashboard URL | Ensure URL includes `?client_id=<tenant>` |
| System tool call loops or gets ignored | Custom LLM does not handle tool calls correctly | Inspect the incoming `tools` array and response format |
| Background music too loud | Default `volume` is high for voice calls | Start at `0.15` and test on phone + browser |

> Última revisión: 2026-05-26
