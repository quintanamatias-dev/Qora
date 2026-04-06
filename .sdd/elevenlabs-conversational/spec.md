# Spec: Migrate to ElevenLabs Conversational AI with Custom LLM

**Change ID**: `elevenlabs-conversational`  
**Status**: `draft`  
**Date**: 2026-04-01  
**Author**: SDD Spec Agent  

---

## 1. Executive Summary

This specification defines the requirements for integrating ElevenLabs Conversational AI as a low-latency voice conversation path alongside the existing DIY pipeline (VAD → STT → LLM → TTS). The integration consists of three deliverables:

1. **Custom LLM Webhook** — A FastAPI SSE endpoint that receives OpenAI-compatible chat completion requests from ElevenLabs and streams GPT-4o responses back via Server-Sent Events.
2. **Web Demo** — A single-page HTML application using the `@elevenlabs/client` SDK that connects directly to ElevenLabs Conversational AI via WebRTC for real-time voice conversations.
3. **Mega System Prompt** — A comprehensive insurance sales agent persona ("Jaumpablo") for outbound lead calls, written in Spanish Rioplatense.

**Target latency**: End-to-end (user speaks → agent responds audibly) under **3 seconds**, down from the current ~15s DIY pipeline.

---

## 2. RFC 2119 Keywords

The keywords **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, **RECOMMENDED**, **MAY**, and **OPTIONAL** in this document are to be interpreted as described in [RFC 2119](https://www.ietf.org/rfc/rfc2119.txt).

---

## 3. Terminology

| Term | Definition |
|------|------------|
| **ElevenLabs Conversational AI** | ElevenLabs managed service handling VAD, STT, LLM orchestration, and TTS in a single WebRTC/WebSocket connection |
| **Custom LLM Webhook** | Our FastAPI endpoint that ElevenLabs calls as an OpenAI-compatible `/v1/chat/completions` endpoint |
| **Agent** | An ElevenLabs Conversational AI agent configured in the ElevenLabs dashboard |
| **Jaumpablo** | The insurance sales agent persona (Spanish Rioplatense) |
| **DIY Pipeline** | The existing V1-CallCenter voice pipeline (Twilio → VAD → STT → LLM → TTS) |
| **WebRTC Demo** | Browser-based demo using `@elevenlabs/client` SDK |

---

## 4. Custom LLM Webhook

### 4.1 Endpoint Definition

**Route**: `POST /api/v1/elevenlabs/custom-llm`  
**Content-Type**: `application/json` (request), `text/event-stream` (response)  
**Authentication**: None (ElevenLabs authenticates via its own agent-level secrets; the endpoint SHOULD validate `Authorization` header if an API key is configured in env)

### 4.2 Request Format

The endpoint MUST accept requests conforming to the OpenAI Chat Completions API schema, as sent by ElevenLabs Conversational AI:

```json
{
  "messages": [
    { "role": "system", "content": "<system prompt>" },
    { "role": "user", "content": "<transcribed user utterance>" }
  ],
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 5000,
  "stream": true,
  "tools": [
    // Optional: system tools configured in ElevenLabs agent
  ],
  "elevenlabs_extra_body": {
    // Optional: custom parameters from ElevenLabs conversation config
  }
}
```

**Validation rules**:
- The `messages` field MUST be present and be a non-empty array.
- The `messages` array MUST contain at least one message with `role: "system"` (injected by ElevenLabs from agent config).
- The `stream` field MUST be `true`; the endpoint SHALL reject non-streaming requests with HTTP 400.
- The `model` field MAY be ignored (the endpoint always uses GPT-4o configured in settings).

### 4.3 Response Format (SSE)

The endpoint MUST return a `StreamingResponse` with `Content-Type: text/event-stream`. Each chunk MUST follow the OpenAI Chat Completions streaming format:

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o","choices":[{"delta":{"content":"Hola"},"index":0,"finish_reason":null}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"gpt-4o","choices":[{"delta":{"content":", ¿cómo"},"index":0,"finish_reason":null}]}

...

data: [DONE]
```

**Error handling**: If an error occurs during streaming, the endpoint MUST emit a final SSE event with an error payload before closing:

```
data: {"error": "Internal error occurred!"}
```

### 4.4 Internal Processing Flow

```
ElevenLabs POST request
    ↓
Validate request schema
    ↓
Extract messages (system prompt + conversation history + latest user message)
    ↓
Forward to GPT-4o via AsyncOpenAI streaming API
    ↓
Stream OpenAI response chunks as SSE events back to ElevenLabs
    ↓
Emit data: [DONE] when stream completes
```

### 4.5 Buffer Words for Slow LLM

**SHOULD** implement buffer words: If GPT-4o takes more than 500ms to produce the first chunk, the endpoint SHOULD emit an initial SSE chunk with content `"Déjame ver... "` (ellipsis followed by space) to maintain natural speech prosody while the LLM processes.

### 4.6 Conversation History Management

- ElevenLabs Conversational AI **manages conversation history** and sends the full message context (system prompt + history + latest user message) in each request.
- The webhook endpoint MUST NOT maintain its own conversation history state — it is **stateless** per request.
- The endpoint MUST forward the complete `messages` array to GPT-4o as-is, preserving the system prompt and all prior turns.

### 4.7 System Prompt Handling

- The system prompt is injected by ElevenLabs from the agent configuration and arrives as the first message with `role: "system"`.
- The endpoint MUST forward this system prompt to GPT-4o unchanged.
- The endpoint MUST NOT modify, append, or override the system prompt.

### 4.8 System Tools Support

- When system tools (end_call, skip_turn, language_detection, etc.) are configured in the ElevenLabs agent, ElevenLabs includes them in the `tools` array of the request.
- The endpoint MUST forward the `tools` array to GPT-4o unchanged.
- Function call responses from GPT-4o MUST be forwarded back in the standard OpenAI format via SSE.
- The endpoint MUST NOT interpret or execute tool calls — ElevenLabs handles tool execution.

### 4.9 Custom Parameters

- ElevenLabs MAY send additional parameters in `elevenlabs_extra_body`.
- The endpoint MUST accept and safely ignore `elevenlabs_extra_body` (strip it before forwarding to OpenAI).

### 4.10 Logging and Telemetry

Each request MUST be logged with structured JSON including:
- `session_id` (from `elevenlabs_extra_body` or generated)
- `user_message` (latest user utterance)
- `response_length` (character count of full response)
- `latency_ms` (time from request receipt to first SSE chunk)
- `total_duration_ms` (time from request receipt to `[DONE]`)

---

## 5. Web Demo

### 5.1 Overview

A single static HTML page served at `/elevenlabs-demo` that uses the `@elevenlabs/client` JavaScript SDK (loaded via CDN) to establish a WebRTC connection directly to ElevenLabs Conversational AI.

### 5.2 Technical Requirements

- **File**: `backend/app/static/elevenlabs-demo.html`
- **SDK**: `@elevenlabs/client` v1.x loaded via CDN (`https://cdn.jsdelivr.net/npm/@elevenlabs/client@1/dist/index.umd.cjs`)
- **No backend media relay**: All audio processing is handled by ElevenLabs; the backend only serves the static HTML file.
- **Browser requirements**: WebRTC support (Chrome 90+, Firefox 88+, Safari 14.1+)

### 5.3 UI Components

The page MUST include:

| Component | Description |
|-----------|-------------|
| **Connect Button** | Primary CTA labeled "Iniciar Conversación" — triggers WebRTC connection |
| **Status Indicator** | Shows connection state: `disconnected`, `connecting`, `connected`, `error` |
| **User Transcription** | Live display of what the user said (from ElevenLabs `onMessage` event) |
| **Agent Response** | Live display of the agent's text response |
| **Disconnect Button** | Stops the conversation and closes WebRTC connection |
| **Timing Display** | Shows round-trip latency for each turn (optional) |

### 5.4 Connection Flow

```
User clicks "Iniciar Conversación"
    ↓
Request microphone permission (browser)
    ↓
Initialize ElevenLabs Conversation with:
  - agentId (from env/config)
  - signedUrl or apiKey
    ↓
Establish WebRTC connection to ElevenLabs
    ↓
Status → "connected"
    ↓
User speaks → ElevenLabs handles STT → Custom LLM webhook → TTS → audio playback
    ↓
onMessage events update transcription and response displays
    ↓
User clicks "Finalizar" → conversation.signOut() → status → "disconnected"
```

### 5.5 Event Handling

The demo MUST handle these ElevenLabs client events:

| Event | Handler Action |
|-------|---------------|
| `onMessage(message)` | Display `message.message` (agent text) and `message.source` (user/assistant) |
| `onConnect()` | Update status to "connected" |
| `onDisconnect()` | Update status to "disconnected" |
| `onError(error)` | Display error message, update status to "error" |
| `onModeChange(mode)` | Update UI to reflect speaking/listening mode |

### 5.6 Configuration

The demo MUST read configuration from a `<script>` block injected by the backend (or from URL query parameters for flexibility):

```javascript
const ELEVENLABS_CONFIG = {
  agentId: "{{ agent_id }}",        // ElevenLabs agent ID
  apiKey: "{{ api_key }}",          // ElevenLabs API key (or use signed URL)
  customLlmUrl: "{{ webhook_url }}" // Our Custom LLM webhook URL
};
```

**Security note**: For production, the API key SHOULD be exchanged for a signed URL via a backend endpoint rather than exposed in client-side code.

### 5.7 Static File Serving

The existing static file mount at `/demo` (configured in `main.py`) MUST continue to serve `elevenlabs-demo.html`. A new route MAY be added for convenience:

```python
# In elevenlabs_conversational.py router
@router.get("/elevenlabs-demo")
async def serve_elevenlabs_demo():
    """Serve the ElevenLabs Conversational AI web demo page."""
    return FileResponse("app/static/elevenlabs-demo.html")
```

---

## 6. Mega System Prompt — Jaumpablo

### 6.1 Agent Identity

| Attribute | Value |
|-----------|-------|
| **Name** | Jaumpablo |
| **Gender** | Male |
| **Broker** | `{{ BROKER_NAME }}` (default: "Quintana Seguros") — configurable via environment variable |
| **Use Case** | Outbound calls to leads who requested auto insurance quotes |
| **Language** | Spanish Rioplatense (voseo) |
| **Max Response Length** | 2-3 sentences per turn |

### 6.2 Personality Traits

- **Warm and approachable**: Speaks like a trusted friend, not a salesperson
- **Professional but natural**: Uses conversational Spanish, not corporate jargon
- **Patient listener**: Lets the lead express concerns without interrupting
- **Confident but not pushy**: Sells through likability, not pressure
- **Empathetic**: Acknowledges objections genuinely before responding

### 6.3 Conversation Flow

The agent MUST follow this natural progression:

#### Phase 1: Greeting (Saludo)
- Introduce self as Jaumpablo from the broker
- Confirm speaking with the right person
- Reference the quote request naturally
- Keep it brief and warm

#### Phase 2: Discovery (Descubrimiento)
- Ask about the vehicle (make, model, year)
- Ask about current insurance situation
- Ask about driving habits (daily commute, annual mileage)
- Ask about coverage priorities (price, coverage breadth, service)

#### Phase 3: Proposal (Propuesta)
- Present 2-3 coverage options (terceros completo, todo riesgo)
- Highlight the most relevant option based on discovery
- Mention key differentiators of the broker
- Keep numbers approximate (direct to broker for exact quote)

#### Phase 4: Objection Handling (Manejo de Objeciones)
- **Price objection**: Acknowledge, reframe value, offer to compare
- **Already insured**: Respect, offer to review at renewal, leave door open
- **Need to think**: Validate, offer to send info, schedule follow-up
- **Not interested**: Respectful close, leave positive impression

#### Phase 5: Close (Cierre)
- Summarize next steps clearly
- Confirm contact information
- Thank the lead warmly
- End call gracefully

### 6.4 Response Constraints

- **Length**: Every response MUST be 2-3 sentences maximum
- **Language**: MUST use Spanish Rioplatense (voseo: "tenés", "querés", "podés", "contame")
- **Format**: MUST NOT use markdown, lists, or formatting — plain conversational text only
- **Tone**: MUST sound like a real phone conversation, not a chatbot
- **Questions**: MUST ask one question at a time — never stack multiple questions
- **Numbers**: Should use approximate ranges, not exact figures (unless provided)

### 6.5 Full System Prompt Template

```
Sos Jaumpablo, un agente de seguros de {broker_name}. 
Estás hablando por teléfono con una persona que pidió una cotización 
de seguro de auto. Tu trabajo es conocer sus necesidades, ofrecerle 
las mejores opciones y cerrar la venta de forma natural.

PERSONALIDAD:
- Cálido, profesional y cercano — vendés por simpatía, no por presión
- Hablás como en una charla real, no como un robot ni un vendedor agresivo
- Escuchás con paciencia y respondés con empatía
- Usás español rioplatense con voseo: "tenés", "querés", "contame", "dale"

REGLAS DE RESPUESTA:
- Máximo 2-3 oraciones por respuesta
- Una pregunta a la vez — nunca hagas dos preguntas juntas
- Sin formato markdown, sin listas, sin viñetas
- Números aproximados, no exactos
- Si no sabés algo, decilo con naturalidad y ofrecé averiguar

FLUJO DE CONVERSACIÓN:
1. Saludo: Presentate como Jaumpablo de {broker_name}, confirmá que hablás 
   con la persona correcta, mencioná que viste que pidió cotización de seguro de auto
2. Descubrimiento: Preguntá sobre el auto (marca, modelo, año), seguro actual, 
   uso diario, qué le importa más (precio, cobertura, atención)
3. Propuesta: Ofrecé 2-3 opciones (terceros completo, todo riesgo), destacá 
   la que mejor se ajusta, mencioná que {broker_name} tiene buenas condiciones
4. Objeciones: Si dice que es caro, reencuadrá el valor. Si ya tiene seguro, 
   ofrecé revisar en la renovación. Si necesita pensar, validá y dejá la puerta abierta
5. Cierre: Confirmá próximos pasos, agradecé, despedite con calidez

OBJECIONES COMUNES:
- "Es muy caro": "Te entiendo perfecto, mirá que el precio depende de la cobertura 
  que elijas. A veces uno piensa que es más caro y después comparando no es tanto. 
  ¿Querés que te arme una opción más básica?"
- "Ya tengo seguro": "Genial, me alegro que estés cubierto. ¿Cuándo te vence? 
  A veces podemos mejorar lo que ya tenés. Si querés, te llamo cerca del vencimiento"
- "Necesito pensarlo": "Obvio, es una decisión importante. ¿Te parece si te mando 
  un resumen por WhatsApp y lo vemos con calma?"
- "No me interesa": "No hay problema, te agradezco igual el tiempo. Si en algún 
  momento necesitás, estamos. ¡Que tengas un buen día!"

IMPORTANTE:
- Tu broker es {broker_name}
- NUNCA inventes precios exactos — decí "aproximadamente" o "desde"
- NUNCA digas que sos una IA o un asistente virtual
- NUNCA respondas en inglés
- Si te preguntan algo fuera de seguros, derivá amablemente al tema
```

### 6.6 Broker Name Configuration

The broker name MUST be configurable via the environment variable `BROKER_NAME` (default: "Quintana Seguros"). The system prompt template MUST substitute `{broker_name}` with this value at agent configuration time (in the ElevenLabs dashboard), NOT at runtime.

---

## 7. Configuration

### 7.1 New Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ELEVENLABS_CONVERSATIONAL_AGENT_ID` | Yes | — | ElevenLabs Conversational AI agent ID |
| `ELEVENLABS_CONVERSATIONAL_API_KEY` | Yes | — | ElevenLabs API key with Conversational AI access |
| `CUSTOM_LLM_WEBHOOK_URL` | Yes | — | Public URL of our Custom LLM webhook (for ElevenLabs agent config) |
| `BROKER_NAME` | No | `Quintana Seguros` | Insurance broker name used in system prompt |

### 7.2 Config Changes

The `Settings` class in `backend/app/config.py` MUST be extended with:

```python
# ElevenLabs Conversational AI
elevenlabs_conversational_agent_id: str = ""
elevenlabs_conversational_api_key: SecretStr | None = None
custom_llm_webhook_url: str = ""
broker_name: str = "Quintana Seguros"
```

### 7.3 .env.example Updates

The `.env.example` file MUST include documentation for all new variables with examples and comments.

---

## 8. Coexistence with DIY Pipeline

### 8.1 Non-Interference

- The existing DIY pipeline (VAD → STT → LLM → TTS) MUST remain fully functional and unchanged.
- The new ElevenLabs path is **additive** — accessed via separate routes (`/api/v1/elevenlabs/custom-llm`, `/elevenlabs-demo`).
- No existing route, component, or configuration SHALL be modified except:
  - `config.py` (additive fields only)
  - `main.py` (new router registration)
  - `.env.example` (additive documentation)

### 8.2 Router Registration

A new router MUST be registered in `main.py`:

```python
from app.api.routes.elevenlabs_conversational import router as elevenlabs_router
api_v1_router.include_router(elevenlabs_router)
```

---

## 9. Scenarios (Given/When/Then)

### Scenario 1: Successful Custom LLM Webhook Call

**Given** ElevenLabs Conversational AI is configured with our Custom LLM webhook URL  
**And** a user is speaking to the Jaumpablo agent  
**When** ElevenLabs sends a POST request to `/api/v1/elevenlabs/custom-llm` with transcribed user text  
**Then** the endpoint MUST return HTTP 200 with `Content-Type: text/event-stream`  
**And** stream GPT-4o response chunks in OpenAI Chat Completions format  
**And** end the stream with `data: [DONE]`  
**And** the total response time SHOULD be under 2 seconds

### Scenario 2: Invalid Request to Custom LLM Webhook

**Given** the Custom LLM webhook is running  
**When** a request is received without a `messages` field  
**Then** the endpoint MUST return HTTP 400 with a descriptive error message  
**And** log the validation failure with structured JSON

### Scenario 3: GPT-4o API Failure

**Given** the Custom LLM webhook receives a valid request  
**When** the GPT-4o API call fails (timeout, rate limit, or connection error)  
**Then** the endpoint MUST emit an SSE error event  
**And** log the failure with error type and message  
**And** return HTTP 502 if the stream cannot be established

### Scenario 4: Web Demo Connection

**Given** the web demo page is loaded in a supported browser  
**When** the user clicks "Iniciar Conversación"  
**Then** the browser MUST request microphone permission  
**And** upon grant, establish a WebRTC connection to ElevenLabs  
**And** the status indicator MUST show "connected"  
**And** the agent MUST greet the user as Jaumpablo

### Scenario 5: Web Demo Conversation

**Given** the web demo is connected to ElevenLabs  
**When** the user speaks a sentence  
**Then** the user's transcription MUST appear in the transcription display  
**And** Jaumpablo's text response MUST appear in the agent response display  
**And** the audio response MUST play automatically through the browser  
**And** the round-trip latency SHOULD be under 3 seconds

### Scenario 6: Web Demo Disconnection

**Given** the web demo is in a connected state  
**When** the user clicks "Finalizar"  
**Then** the WebRTC connection MUST be closed  
**And** the status indicator MUST show "disconnected"  
**And** the connect button MUST become available again

### Scenario 7: Broker Name Configuration

**Given** the environment variable `BROKER_NAME` is set to "Seguros del Sur"  
**When** the Jaumpablo agent is configured in ElevenLabs  
**Then** the system prompt MUST reference "Seguros del Sur" as the broker  
**And** Jaumpablo MUST introduce itself as an agent from "Seguros del Sur"

### Scenario 8: System Tool — End Call

**Given** the ElevenLabs agent has the `end_call` system tool configured  
**And** the user says "Gracias, eso es todo"  
**When** GPT-4o generates a function call for `end_call`  
**Then** the function call MUST be returned in standard OpenAI format via SSE  
**And** ElevenLabs MUST process the tool call and terminate the conversation

### Scenario 9: Buffer Words for Slow Response

**Given** GPT-4o takes more than 500ms to produce the first chunk  
**When** the Custom LLM webhook is streaming a response  
**Then** the endpoint SHOULD emit an initial SSE chunk with content `"Déjame ver... "`  
**And** the TTS system SHOULD produce natural-sounding audio for the buffer phrase  
**And** subsequent chunks SHOULD append seamlessly

### Scenario 10: DIY Pipeline Unaffected

**Given** the existing DIY pipeline is operational  
**When** a call is made through the existing `/api/v1/calls` route  
**Then** the call MUST be processed through the DIY pipeline (VAD → STT → LLM → TTS)  
**And** the ElevenLabs Conversational AI components MUST NOT interfere  
**And** the existing web demo at `/demo` MUST continue to function

---

## 10. File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/api/routes/elevenlabs_conversational.py` | **NEW** | Custom LLM webhook endpoint + demo page route |
| `backend/app/static/elevenlabs-demo.html` | **NEW** | WebRTC demo HTML page |
| `backend/app/config.py` | **MODIFY** | Add ElevenLabs Conversational AI settings |
| `backend/app/main.py` | **MODIFY** | Register new router |
| `backend/.env.example` | **MODIFY** | Document new environment variables |

---

## 11. Acceptance Criteria

| # | Criterion | Priority |
|---|-----------|----------|
| AC-1 | Custom LLM webhook receives POST requests from ElevenLabs and returns valid SSE stream | **MUST** |
| AC-2 | SSE stream follows OpenAI Chat Completions format with `data: [DONE]` terminator | **MUST** |
| AC-3 | Web demo connects to ElevenLabs via WebRTC and completes full conversation loop | **MUST** |
| AC-4 | End-to-end latency (user speaks → agent audio response) is under 3 seconds | **SHOULD** |
| AC-5 | Jaumpablo system prompt correctly identifies as agent from configured broker | **MUST** |
| AC-6 | Broker name is configurable via `BROKER_NAME` environment variable | **MUST** |
| AC-7 | All responses are in Spanish Rioplatense (voseo) | **MUST** |
| AC-8 | Responses are limited to 2-3 sentences maximum | **MUST** |
| AC-9 | Existing DIY pipeline continues to function without modification | **MUST** |
| AC-10 | System tools (end_call, skip_turn) are forwarded to GPT-4o unchanged | **SHOULD** |
| AC-11 | Buffer words are implemented for slow LLM responses | **SHOULD** |
| AC-12 | Structured logging captures latency metrics for each webhook call | **SHOULD** |
| AC-13 | Web demo displays user transcription and agent response text | **MUST** |
| AC-14 | Web demo has connect/disconnect controls with status indicator | **MUST** |
| AC-15 | New environment variables are documented in `.env.example` | **MUST** |

---

## 12. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| ElevenLabs agent requires manual dashboard setup | High | Medium | Document step-by-step agent creation; agent ID stored in env |
| Custom LLM webhook must be publicly accessible | High | High | Use ngrok for local dev; document production URL requirements |
| SSE streaming format mismatch with ElevenLabs | Medium | High | Follow ElevenLabs docs precisely; add request/response validation |
| Browser WebRTC connectivity issues (firewalls/NAT) | Low | Medium | WebRTC handles NAT traversal; test on multiple browsers |
| GPT-4o latency exceeds budget (>2s) | Medium | High | Implement buffer words; consider model fallback to gpt-4o-mini |
| ElevenLabs Conversational AI pricing exceeds budget | Medium | Medium | Test with free tier; monitor usage metrics before production |
| `@elevenlabs/client` SDK breaking changes | Low | Low | Pin to v1.x; test before SDK upgrades |

---

## 13. Rollback Plan

1. The existing DIY pipeline remains fully functional — no components are removed or modified.
2. Remove the new `/api/v1/elevenlabs/custom-llm` route registration from `main.py`.
3. Delete `elevenlabs_conversational.py` and `elevenlabs-demo.html`.
4. Remove new env vars from `.env` and `config.py`.
5. Web demo users simply revert to the existing `/demo` route.

---

## 14. Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| ElevenLabs API key with Conversational AI access | Required | Must be provisioned before testing |
| ElevenLabs agent created (dashboard or API) | Required | Must point Custom LLM to our webhook URL |
| OpenAI API key for GPT-4o | Already configured | Reuse existing key |
| `@elevenlabs/client` npm package v1.x | Required | Loaded via CDN for web demo |
| Public URL for webhook (ngrok/domain) | Required | ElevenLabs must be able to reach our endpoint |

---

## 15. Out of Scope

- Twilio SIP integration with ElevenLabs Conversational AI (future phase)
- n8n/Hume AI sentiment analysis pipeline (future phase)
- Migration or removal of existing DIY pipeline components
- Call recording through ElevenLabs (handled separately)
- Signed URL authentication for web demo (future security enhancement)
- Multi-agent transfer configuration
- Production-grade authentication for the webhook endpoint
