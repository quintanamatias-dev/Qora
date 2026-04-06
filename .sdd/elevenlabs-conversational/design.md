# Design: ElevenLabs Conversational AI Integration

## Technical Approach

Replace the ~15s DIY audio pipeline (VAD→STT→LLM→TTS) with ElevenLabs Conversational AI handling VAD, STT, and TTS natively via WebRTC. Our FastAPI backend contributes only the **Custom LLM Webhook** — a stateless SSE endpoint that ElevenLabs calls as an OpenAI-compatible `/v1/chat/completions` proxy, forwarding to GPT-4o streaming. The existing DIY pipeline stays untouched.

## Architecture Decisions

### Decision: Stateless Custom LLM Webhook (no server-side history)

**Choice**: The webhook is completely stateless — ElevenLabs sends the full message context (system + history + latest user turn) in each POST request.
**Alternatives**: Maintain session state server-side (redis/dict keyed by session_id from `elevenlabs_extra_body`).
**Rationale**: ElevenLabs already manages history and sends complete context. Duplicating history server-side adds complexity and the risk of divergence. Stateless = simpler, horizontally scalable, zero cleanup.

### Decision: Reuse existing `GPT4oClient` for streaming

**Choice**: Create a new `ElevenLabsStreamingClient` that wraps `AsyncOpenAI` streaming calls directly, rather than extending the existing `GPT4oClient`.
**Alternatives**: Fork `GPT4oClient.generate()` to support streaming.
**Rationale**: The existing client does non-streaming `chat.completions.create()` and manages `_history` (which we don't need here). A lean streaming-only client avoids mutating shared state and keeps the new module focused.

### Decision: `@elevenlabs/client` SDK via CDN (not npm)

**Choice**: Load the ElevenLabs SDK via CDN script tag in the static HTML.
**Alternatives**: Bundle via npm + build step.
**Rationale**: Single static HTML file served directly — no build pipeline, no bundler config. Simpler for a demo. Tradeoff: less tree-shaking, but the SDK is small.

### Decision: Buffer words for slow LLM responses

**Choice**: Emit `"Déjame ver... "` as the first SSE chunk if GPT-4o hasn't produced output within 500ms.
**Alternatives**: Show a typing indicator only; block until first token.
**Rationale**: ElevenLabs TTS needs audio to play while the LLM thinks. Buffer words keep the conversation feeling natural. The phrase is short, sounds natural spoken aloud, and buys ~500ms of TTS audio buffer.

## Data Flow

```
Browser (mic)
    │
    ▼ WebRTC (browser → ElevenLabs)
    ElevenLabs (VAD → STT → TTS)
    │
    ▼ POST /api/v1/elevenlabs/custom-llm (HTTPS)
    FastAPI ──stream──► GPT-4o (OpenAI)
    │
    ▼ SSE text/event-stream
    ElevenLabs (receives text → TTS)
    │
    ▼ WebRTC audio back to browser
Browser (speaker)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/api/routes/elevenlabs_conversational.py` | **CREATE** | Router with `POST /custom-llm` (SSE streaming) and `GET /elevenlabs-demo` (serve HTML) |
| `backend/app/ai/llm_streaming.py` | **CREATE** | `OpenAIStreamingClient` — lean async streaming client using `AsyncOpenAI.chat.completions.create(stream=True)` |
| `backend/app/static/elevenlabs-demo.html` | **CREATE** | Single static HTML page with ElevenLabs SDK, connect/disconnect UI, transcription display |
| `backend/app/config.py` | **MODIFY** | Add `elevenlabs_conversational_agent_id`, `elevenlabs_conversational_api_key`, `custom_llm_webhook_url`, `broker_name` fields |
| `backend/app/main.py` | **MODIFY** | Import and register `elevenlabs_router` under `api_v1_router` |
| `backend/.env.example` | **MODIFY** | Document all four new env vars with comments |

## Custom LLM Webhook Design

**Route**: `POST /api/v1/elevenlabs/custom-llm`
**Request**: `application/json` — OpenAI Chat Completions schema (ElevenLabs sends this)

```python
# Request body shape (simplified)
{
  "messages": [{"role": "system", "content": "..."}, ...],
  "model": "gpt-4o",
  "stream": true,
  "tools": [...],           # forwarded as-is to GPT-4o
  "elevenlabs_extra_body": {"session_id": "..."}  # stripped before OpenAI call
}
```

**Response**: `text/event-stream`

```
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"Buen"},"index":0,"finish_reason":null}]}

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"delta":{"content":"o!"},"index":0,"finish_reason":null}]}

...
data: [DONE]
```

**Validation**: HTTP 400 if `messages` missing/empty, if `stream` is false, or if no system prompt present.

**Buffer words**: If GPT-4o hasn't emitted a chunk within 500ms, emit `data: {"id":"...","choices":[{"delta":{"content":"Déjame ver... "}}]}` then continue normally.

**Error events**: On GPT-4o failure, emit `data: {"error": "..."}` before closing the stream. Return HTTP 502 only if the stream cannot be established at all.

**Logging**: Structured JSON per request — `session_id`, `user_message`, `first_chunk_latency_ms`, `total_duration_ms`, `response_length_chars`.

## Web Demo Design

Static file at `/elevenlabs-demo` (via `FileResponse` in the router, served under `/demo` mount from `main.py`).

**SDK**: `<script src="https://cdn.jsdelivr.net/npm/@elevenlabs/client@1/dist/index.umd.cjs"></script>`
**Config injection**: `ELEVENLABS_CONFIG` object with `agentId`, `apiKey`, `customLlmUrl` from URL query params or backend template injection.

**UI components**: Connect button, status pill (disconnected/connecting/connected/error), user transcription panel, agent response panel, disconnect button.

**Event handlers**: `onMessage`, `onConnect`, `onDisconnect`, `onError`, `onModeChange`.

## System Prompt Module

New file `backend/app/agents/prompts/insurance_agent.py` — exports `INSURANCE_AGENT_PROMPT` template string with `{broker_name}` substitution placeholder. This file documents the Jaumpablo persona. The actual system prompt lives in the ElevenLabs dashboard (as per spec §6.6 — substitution happens at agent config time, not at runtime).

## Testing Strategy

| Layer | What | How |
|-------|------|-----|
| Unit | `OpenAIStreamingClient` chunk parsing, buffer-word timer logic, request validation | `pytest` with `httpx` async mock |
| Integration | Full webhook: POST with messages → SSE response stream | `pytest-asyncio` + `TestClient` sending real OpenAI requests (or mocked) |
| E2E | WebRTC connection + full turn in browser | Manual test with ngrok; automated via Playwright browser test |

## Performance Targets

- First-chunk latency: < 500ms (buffer words cover up to 1s LLM delay)
- Total turn latency (user speaks → agent audio): < 3s
- Webhook P95 response time: < 1.5s (GPT-4o streaming overhead)

## Migration / Rollout

**No data migration required.** This is an additive path — no existing components are modified or removed. Rollout:
1. Set new env vars (`ELEVENLABS_CONVERSATIONAL_AGENT_ID`, `ELEVENLABS_CONVERSATIONAL_API_KEY`, `CUSTOM_LLM_WEBHOOK_URL`, `BROKER_NAME`)
2. Register router in `main.py` (one import + one `include_router` call)
3. Serve `elevenlabs-demo.html` via the static mount
4. Create ElevenLabs agent in dashboard, point Custom LLM to webhook URL

**Rollback**: Remove the two lines from `main.py`, delete the two new Python/HTML files, remove the four fields from `config.py`. Existing pipeline is untouched.

## Open Questions

- [ ] Should the webhook validate an ElevenLabs API key in the `Authorization` header, or rely entirely on the agent-level secret ElevenLabs uses?
- [ ] Do we log full message history (including prior turns) per request for debugging, or only the latest user message?
- [ ] Should the web demo use a signed URL (backend generates it) instead of embedding the API key in client-side JS for production?
