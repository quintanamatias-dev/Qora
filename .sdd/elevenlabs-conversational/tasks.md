# Tasks: ElevenLabs Conversational AI Integration

**Change ID**: `elevenlabs-conversational`  
**Status**: `draft`  
**Date**: 2026-04-01  
**Author**: SDD Tasks Agent  

---

## Phase 1: Configuration

### T001 — Add ElevenLabs Conversational AI settings to `Settings` class
- **File**: `backend/app/config.py`
- **Action**: Add four new fields to the `Settings` class (pydantic `BaseSettings`):
  - `elevenlabs_conversational_agent_id: str = ""` — ElevenLabs Conversational AI agent ID
  - `elevenlabs_conversational_api_key: SecretStr | None = None` — API key with Conversational AI access
  - `custom_llm_webhook_url: str = ""` — Public URL of our Custom LLM webhook
  - `broker_name: str = "Quintana Seguros"` — Insurance broker name for system prompt
- **Details**:
  - Place fields in a new section `# ElevenLabs Conversational AI` after the existing ElevenLabs TTS section
  - `elevenlabs_conversational_api_key` must be typed as `SecretStr | None = None` (optional at startup since it's only needed for the demo)
  - No existing fields should be modified or removed
- **Acceptance**:
  - `Settings()` instantiates without error when new vars are absent (all have defaults)
  - `Settings(elevenlabs_conversational_agent_id="abc", broker_name="Test")` works correctly
  - `elevenlabs_conversational_api_key` is properly wrapped as `SecretStr` when provided

---

## Phase 2: Custom LLM Webhook

### T002 — Create `OpenAIStreamingClient` for async streaming
- **File**: `backend/app/ai/llm_streaming.py` (NEW)
- **Action**: Create a lean async streaming client that wraps `AsyncOpenAI.chat.completions.create(stream=True)`
- **Details**:
  - Class `OpenAIStreamingClient` with:
    - `__init__(self, api_key: str, model: str = "gpt-4o")` — initializes `AsyncOpenAI` client
    - `async def stream_completion(self, messages: list[dict], tools: list | None = None) -> AsyncGenerator[str, None]` — yields raw text content tokens from GPT-4o streaming response
  - Method must:
    - Accept `messages` list (system prompt + history + user message)
    - Accept optional `tools` array (forwarded as-is to GPT-4o)
    - Set `stream=True` on the OpenAI API call
    - Yield only the `delta.content` string from each chunk (skip `None` content)
    - Handle `APIConnectionError`, `APITimeoutError`, `RateLimitError` — raise a custom `StreamingError` with context
  - Do NOT maintain conversation history (stateless by design per spec §4.6)
  - Do NOT extend or modify the existing `GPT4oClient` — this is a separate, focused module
- **Acceptance**:
  - Client yields text tokens from a real or mocked GPT-4o streaming response
  - Tools array is forwarded unchanged when provided
  - API errors are wrapped in `StreamingError` with the original exception attached
  - No state is stored between calls

### T003 — Create Custom LLM webhook endpoint
- **File**: `backend/app/api/routes/elevenlabs_conversational.py` (NEW)
- **Action**: Create a FastAPI router with `POST /custom-llm` endpoint
- **Details**:
  - Router prefix: `/elevenlabs` (full route: `POST /api/v1/elevenlabs/custom-llm`)
  - Request model (Pydantic):
    - `messages: list[dict[str, str]]` — required, non-empty
    - `model: str | None = None` — optional, ignored (always uses GPT-4o)
    - `temperature: float = 0.7` — optional
    - `max_tokens: int = 5000` — optional
    - `stream: bool = True` — must be true; reject with HTTP 400 if false
    - `tools: list[dict] | None = None` — optional, forwarded to GPT-4o
    - `elevenlabs_extra_body: dict | None = None` — optional, stripped before OpenAI call
  - Validation:
    - Return HTTP 400 if `messages` is missing, empty, or has no system prompt (no message with `role: "system"`)
    - Return HTTP 400 if `stream` is `false`
  - Response:
    - Return `StreamingResponse` with `media_type="text/event-stream"`
    - Each SSE event: `data: {json_chunk}\n\n` following OpenAI Chat Completions streaming format
    - Generate a unique `chatcmpl-<uuid>` ID for the response
    - Final event: `data: [DONE]\n\n`
    - On error during streaming: emit `data: {"error": "..."}` before closing
  - Processing flow:
    1. Validate request
    2. Extract `messages` and `tools`
    3. Strip `elevenlabs_extra_body` before forwarding
    4. Create `OpenAIStreamingClient` with API key from `app.state.settings`
    5. Stream GPT-4o tokens as SSE events
    6. Emit `[DONE]` when complete
- **Acceptance**:
  - Valid request returns HTTP 200 with `Content-Type: text/event-stream`
  - SSE stream contains properly formatted OpenAI chat completion chunks
  - Stream ends with `data: [DONE]`
  - Invalid request (missing messages, stream=false) returns HTTP 400
  - GPT-4o API error emits SSE error event and closes stream

### T004 — Implement buffer words for slow LLM responses
- **File**: `backend/app/api/routes/elevenlabs_conversational.py` (modify T003 output)
- **Action**: Add buffer words logic to the SSE streaming generator
- **Details**:
  - Track time from request start to first GPT-4o token
  - If no token arrives within 500ms, emit an initial SSE chunk:
    ```
    data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":<timestamp>,"model":"gpt-4o","choices":[{"delta":{"content":"Déjame ver... "},"index":0,"finish_reason":null}]}
    ```
  - After buffer words are emitted, continue streaming GPT-4o tokens normally
  - Buffer words should only be emitted once per request
  - Use `asyncio.wait_for` or a background task with `asyncio.Event` to implement the timeout
- **Acceptance**:
  - When GPT-4o responds within 500ms, NO buffer words are emitted
  - When GPT-4o takes >500ms for first token, buffer words chunk is emitted first
  - Buffer words are emitted exactly once per request
  - Subsequent tokens append seamlessly after buffer words

### T005 — Add structured logging and telemetry to webhook
- **File**: `backend/app/api/routes/elevenlabs_conversational.py` (modify T003 output)
- **Action**: Add structured JSON logging per webhook request
- **Details**:
  - Log at request start: `elevenlabs_webhook_received` with `session_id` (from `elevenlabs_extra_body.session_id` or `"unknown"`)
  - Log at first chunk: `elevenlabs_first_chunk` with `first_chunk_latency_ms`
  - Log at completion: `elevenlabs_webhook_completed` with:
    - `session_id`
    - `user_message` (latest user utterance from messages array)
    - `response_length_chars` (total character count of streamed response)
    - `first_chunk_latency_ms`
    - `total_duration_ms`
  - Log on error: `elevenlabs_webhook_error` with `error_type`, `error_message`
  - Use `structlog.get_logger()` (already configured in `main.py`)
- **Acceptance**:
  - Each webhook call produces structured JSON log entries
  - Latency metrics are accurately captured
  - Error logs include exception context

---

## Phase 3: System Prompt Module

### T006 — Create Jaumpablo insurance agent prompt
- **File**: `backend/app/agents/prompts/insurance_agent.py` (NEW)
- **Action**: Create a module exporting the Jaumpablo system prompt template
- **Details**:
  - Export `INSURANCE_AGENT_PROMPT` — a string template with `{broker_name}` placeholder
  - Export `render_insurance_agent_prompt(broker_name: str = "Quintana Seguros") -> str` — renders the template with the broker name
  - Prompt content must include (per spec §6.5):
    - Agent identity: Jaumpablo, male, from `{broker_name}`
    - Use case: Outbound calls to auto insurance quote leads
    - Personality: Warm, professional, patient, confident but not pushy, empathetic
    - Response constraints: 2-3 sentences max, Spanish Rioplatense (voseo), no markdown, one question at a time
    - Full conversation flow: Greeting → Discovery → Proposal → Objection Handling → Close
    - Common objection handlers with example responses
    - Important rules: never invent exact prices, never claim to be AI, never respond in English
  - The prompt is a documentation/reference artifact — the actual system prompt lives in the ElevenLabs dashboard (per spec §6.6)
- **Acceptance**:
  - `render_insurance_agent_prompt()` returns the full prompt with broker name substituted
  - `render_insurance_agent_prompt("Seguros del Sur")` replaces all instances of `{broker_name}`
  - Default broker name is "Quintana Seguros"
  - Prompt text is in Spanish Rioplatense

---

## Phase 4: Web Demo

### T007 — Create ElevenLabs Conversational AI web demo HTML page
- **File**: `backend/app/static/elevenlabs-demo.html` (NEW)
- **Action**: Create a single static HTML page with the ElevenLabs WebRTC demo
- **Details**:
  - Load `@elevenlabs/client` SDK via CDN:
    ```html
    <script src="https://cdn.jsdelivr.net/npm/@elevenlabs/client@1/dist/index.umd.cjs"></script>
    ```
  - Configuration block (read from URL query params for flexibility):
    ```javascript
    const CONFIG = {
      agentId: new URLSearchParams(window.location.search).get('agentId') || '',
      apiKey: new URLSearchParams(window.location.search).get('apiKey') || '',
      customLlmUrl: new URLSearchParams(window.location.search).get('customLlmUrl') || ''
    };
    ```
  - UI Components:
    - **Header**: "Jaumpablo — Quintana Seguros" (or configured broker name)
    - **Status pill**: Shows `disconnected` (gray), `connecting` (yellow), `connected` (green), `error` (red)
    - **Connect button**: "Iniciar Conversación" — primary CTA
    - **Disconnect button**: "Finalizar" — hidden until connected
    - **User transcription panel**: Shows what the user said (from `onMessage` with `source: "user"`)
    - **Agent response panel**: Shows Jaumpablo's text (from `onMessage` with `source: "assistant"`)
    - **Timing display** (optional): Shows round-trip latency per turn
  - Event handlers:
    - `onConnect()` → status = "connected", show disconnect button, hide connect button
    - `onDisconnect()` → status = "disconnected", show connect button, hide disconnect button
    - `onMessage(message)` → display `message.message` in appropriate panel based on `message.source`
    - `onError(error)` → status = "error", display error message
    - `onModeChange(mode)` → update UI to reflect speaking/listening mode
  - Connection flow:
    1. User clicks "Iniciar Conversación"
    2. Request microphone permission
    3. Initialize ElevenLabs Conversation with `agentId`, `apiKey`, `customLlmUrl`
    4. Establish WebRTC connection
    5. On "Finalizar" → `conversation.signOut()`
  - Styling: Clean, minimal CSS — no external frameworks. Use CSS variables for theming. Responsive layout.
- **Acceptance**:
  - Page loads without errors in Chrome 90+, Firefox 88+, Safari 14.1+
  - Clicking "Iniciar Conversación" requests mic permission and connects to ElevenLabs
  - User speech appears in transcription panel
  - Agent response appears in response panel
  - Clicking "Finalizar" disconnects and resets UI
  - Status indicator reflects connection state accurately
  - Configuration can be passed via URL query parameters

### T008 — Add route to serve the ElevenLabs demo page
- **File**: `backend/app/api/routes/elevenlabs_conversational.py` (modify T003 output)
- **Action**: Add `GET /elevenlabs-demo` endpoint to serve the static HTML file
- **Details**:
  - Route: `GET /api/v1/elevenlabs/elevenlabs-demo`
  - Return `FileResponse("app/static/elevenlabs-demo.html")`
  - The page is also accessible via the existing `/demo` static mount (per spec §5.7)
- **Acceptance**:
  - `GET /api/v1/elevenlabs/elevenlabs-demo` returns the HTML page with HTTP 200
  - `Content-Type` is `text/html`

---

## Phase 5: Registration & Wiring

### T009 — Register ElevenLabs router in `main.py`
- **File**: `backend/app/main.py`
- **Action**: Import and register the new `elevenlabs_router` under `api_v1_router`
- **Details**:
  - Add import: `from app.api.routes.elevenlabs_conversational import router as elevenlabs_router`
  - Add registration: `api_v1_router.include_router(elevenlabs_router)`
  - Place after existing router registrations (after `web_demo_router`)
  - Do NOT modify any existing router registrations or lifespan logic
- **Acceptance**:
  - Application starts without errors
  - `POST /api/v1/elevenlabs/custom-llm` is accessible
  - `GET /api/v1/elevenlabs/elevenlabs-demo` is accessible
  - Existing routes (`/api/v1/health`, `/api/v1/calls`, etc.) continue to work

### T010 — Update `.env.example` with new environment variables
- **File**: `backend/.env.example`
- **Action**: Add documentation for the four new environment variables
- **Details**:
  - Add a new section `# ElevenLabs Conversational AI (OPTIONAL)` after the existing ElevenLabs TTS section:
    ```
    # ---------------------------------------------------------------------------
    # ElevenLabs Conversational AI (OPTIONAL)
    # Used for the managed Conversational AI path (VAD → STT → Custom LLM → TTS)
    # ---------------------------------------------------------------------------
    ELEVENLABS_CONVERSATIONAL_AGENT_ID=    # ElevenLabs Conversational AI agent ID (from dashboard)
    ELEVENLABS_CONVERSATIONAL_API_KEY=     # ElevenLabs API key with Conversational AI access
    CUSTOM_LLM_WEBHOOK_URL=                # Public URL of our Custom LLM webhook (e.g., https://your-domain.com/api/v1/elevenlabs/custom-llm)
    BROKER_NAME=Quintana Seguros           # Insurance broker name used in Jaumpablo system prompt
    ```
  - Do NOT modify existing variable documentation
- **Acceptance**:
  - All four new variables are documented with comments
  - File structure and formatting matches existing style
  - No existing entries are modified

---

## Phase 6: Testing

### T011 — Unit tests for `OpenAIStreamingClient`
- **File**: `backend/tests/test_llm_streaming.py` (NEW)
- **Action**: Write unit tests for the streaming client
- **Details**:
  - Test: `test_stream_completion_yields_tokens` — mock `AsyncOpenAI` to return a streaming response; verify tokens are yielded
  - Test: `test_stream_completion_forwards_tools` — verify tools array is passed to the OpenAI API call
  - Test: `test_stream_completion_handles_api_error` — mock `APIConnectionError`; verify `StreamingError` is raised
  - Test: `test_stream_completion_skips_none_content` — mock response with chunks that have `delta.content = None`; verify they are skipped
  - Test: `test_stream_completion_no_state_between_calls` — verify client is stateless (no history accumulation)
  - Use `pytest` with `pytest-asyncio` and `unittest.mock.AsyncMock`
- **Acceptance**:
  - All tests pass with `pytest backend/tests/test_llm_streaming.py`
  - Tests run in under 5 seconds (no real API calls)
  - Coverage: all public methods of `OpenAIStreamingClient`

### T012 — Unit tests for Custom LLM webhook endpoint
- **File**: `backend/tests/test_elevenlabs_webhook.py` (NEW)
- **Action**: Write unit tests for the webhook endpoint
- **Details**:
  - Test: `test_webhook_valid_request_returns_sse_stream` — POST with valid messages; verify HTTP 200 and `text/event-stream` content type
  - Test: `test_webhook_missing_messages_returns_400` — POST without `messages`; verify HTTP 400
  - Test: `test_webhook_empty_messages_returns_400` — POST with empty `messages` array; verify HTTP 400
  - Test: `test_webhook_no_system_prompt_returns_400` — POST with messages but no system role; verify HTTP 400
  - Test: `test_webhook_stream_false_returns_400` — POST with `stream: false`; verify HTTP 400
  - Test: `test_webhook_strips_extra_body` — POST with `elevenlabs_extra_body`; verify it's not forwarded to OpenAI
  - Test: `test_webhook_forwards_tools_unchanged` — POST with tools; verify tools are forwarded to OpenAI
  - Test: `test_webhook_emits_done_event` — verify stream ends with `data: [DONE]`
  - Test: `test_webhook_emits_error_on_api_failure` — mock OpenAI failure; verify SSE error event is emitted
  - Use `httpx.AsyncClient` with FastAPI's `TestClient` or `async_test_client`
  - Mock `OpenAIStreamingClient` to avoid real API calls
- **Acceptance**:
  - All tests pass with `pytest backend/tests/test_elevenlabs_webhook.py`
  - Tests cover validation, streaming, error handling, and tool forwarding
  - No real external API calls during tests

### T013 — Unit tests for system prompt module
- **File**: `backend/tests/test_insurance_agent_prompt.py` (NEW)
- **Action**: Write unit tests for the Jaumpablo prompt module
- **Details**:
  - Test: `test_render_prompt_default_broker` — verify default broker name "Quintana Seguros" is used
  - Test: `test_render_prompt_custom_broker` — verify `{broker_name}` is replaced with custom value
  - Test: `test_render_prompt_all_instances_replaced` — verify ALL instances of `{broker_name}` are replaced (not just the first)
  - Test: `test_prompt_contains_required_sections` — verify prompt contains identity, personality, rules, flow, and objection handling sections
  - Test: `test_prompt_is_in_spanish` — verify prompt text is primarily in Spanish
  - Test: `test_prompt_mentions_voseo` — verify prompt instructs to use voseo forms
- **Acceptance**:
  - All tests pass with `pytest backend/tests/test_insurance_agent_prompt.py`
  - Prompt content matches spec §6.5 requirements

### T014 — Integration test for full webhook flow
- **File**: `backend/tests/test_elevenlabs_integration.py` (NEW)
- **Action**: Write integration test that exercises the full webhook flow with a mocked OpenAI client
- **Details**:
  - Test: `test_full_webhook_flow` — end-to-end test:
    1. POST valid request to `/api/v1/elevenlabs/custom-llm`
    2. Mock `OpenAIStreamingClient` to yield predetermined tokens
    3. Verify SSE stream contains all expected chunks
    4. Verify `[DONE]` event is emitted
    5. Verify structured log entries are produced
  - Test: `test_webhook_buffer_words_emitted_on_delay` — mock streaming client to delay first token by 600ms; verify buffer words chunk appears before actual tokens
  - Test: `test_webhook_no_buffer_words_on_fast_response` — mock streaming client to respond immediately; verify NO buffer words are emitted
  - Use `pytest-asyncio` with `httpx.AsyncClient`
- **Acceptance**:
  - All integration tests pass
  - Buffer words logic is verified for both slow and fast response scenarios
  - Structured logging is verified in log output

---

## Task Dependencies

```
T001 (Config) ──────────────────────────────────────────────────────────────┐
                                                                             ├── T009 (Register router)
T002 (Streaming Client) ──┬── T003 (Webhook endpoint) ──┬── T004 (Buffer)  │
                          │                              ├── T005 (Logging) │
                          │                              └── T008 (Demo route)
                          └── T011 (Streaming tests)                        │
                                                                             │
T006 (System Prompt) ─── T013 (Prompt tests)                                │
                                                                             │
T007 (Web Demo HTML) ────────────────────────────────────────────────────────┘

T003 + T002 ── T012 (Webhook tests) ── T014 (Integration tests)
T010 (.env.example) ── (no dependencies, can be done anytime)
```

## Recommended Execution Order

1. **T001** — Config (no dependencies, unlocks everything)
2. **T002** — Streaming client (needed by webhook)
3. **T006** — System prompt (independent, quick win)
4. **T003** — Webhook endpoint (depends on T002)
5. **T004** — Buffer words (extends T003)
6. **T005** — Logging (extends T003)
7. **T007** — Web demo HTML (independent of backend)
8. **T008** — Demo route (extends T003)
9. **T009** — Register router (depends on T003/T008)
10. **T010** — .env.example (independent, quick)
11. **T011** — Streaming client tests (depends on T002)
12. **T012** — Webhook tests (depends on T003)
13. **T013** — Prompt tests (depends on T006)
14. **T014** — Integration tests (depends on T003, T004)

## Effort Estimates

| Task | Complexity | Estimated Time |
|------|-----------|----------------|
| T001 | Low | 10 min |
| T002 | Medium | 45 min |
| T003 | High | 1.5 hrs |
| T004 | Medium | 30 min |
| T005 | Low | 20 min |
| T006 | Low | 15 min |
| T007 | Medium | 1 hr |
| T008 | Low | 10 min |
| T009 | Low | 5 min |
| T010 | Low | 5 min |
| T011 | Medium | 45 min |
| T012 | Medium | 45 min |
| T013 | Low | 15 min |
| T014 | Medium | 45 min |
| **Total** | | **~7 hours** |
