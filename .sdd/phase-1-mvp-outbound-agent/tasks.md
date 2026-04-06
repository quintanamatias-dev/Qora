# Implementation Tasks: Phase 1 — MVP Outbound Call Agent

**Change ID:** `phase-1-mvp-outbound-agent`  
**Status:** Draft  
**Version:** 1.0.0  
**Date:** 2026-03-31  
**Total Tasks:** 47  
**Estimated Sessions:** 12-15  

---

## Phase 0: Project Setup

### 0.1 — Create `pyproject.toml` with all dependencies
- [ ] Define project metadata (`name = "v1-callcenter"`, version, description)
- [ ] Add all runtime dependencies: `fastapi`, `uvicorn[standard]`, `websockets`, `pydantic`, `pydantic-settings`, `openai`, `twilio`, `pydub`, `onnxruntime`, `numpy`, `sqlalchemy[asyncio]`, `aiosqlite`, `structlog`
- [ ] Add dev/test dependencies: `pytest`, `pytest-asyncio`, `pytest-mock`, `httpx`, `respx`
- [ ] Configure Python version constraint (`>=3.11`)
- [ ] Add build system configuration (`hatchling` or `setuptools`)
- **Deliverable:** `backend/pyproject.toml` with complete dependency list
- **Dependencies:** None

### 0.2 — Create `.env.example` with all required variables
- [ ] Document all environment variables from spec §9.1
- [ ] Include: `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`, `DATABASE_URL`, `SESSION_TTL_SECONDS`, `HOST`, `PORT`, `LOG_LEVEL`, `VAD_SILENCE_THRESHOLD_MS`, `MAX_UTTERANCE_DURATION_S`, `MAX_HISTORY_MESSAGES`
- [ ] Mark required vs optional with comments
- [ ] Include sensible defaults for optional variables
- **Deliverable:** `backend/.env.example`
- **Dependencies:** None

### 0.3 — Create config/settings module
- [ ] Implement `Settings` class using `pydantic-settings` (matches design §3.10)
- [ ] Include all fields from design with correct types (`SecretStr` for keys)
- [ ] Configure `.env` file loading
- [ ] Add validation for required fields
- [ ] Create `backend/app/__init__.py` and `backend/app/config.py`
- **Deliverable:** `backend/app/config.py` with validated `Settings` class
- **Dependencies:** 0.1, 0.2

### 0.4 — Create FastAPI app skeleton (`main.py`)
- [ ] Create FastAPI application instance with title, version, description
- [ ] Implement lifespan context manager for startup/shutdown
- [ ] Wire up `Settings` loading in lifespan
- [ ] Mount placeholder router for `api/v1`
- [ ] Add structured logging setup with `structlog`
- [ ] Create `backend/app/main.py`
- **Deliverable:** `backend/app/main.py` that starts and responds to health check
- **Dependencies:** 0.3

### 0.5 — Create SQLite database setup with schema
- [ ] Create SQLAlchemy async engine and session factory (`backend/app/db/engine.py`)
- [ ] Define all ORM models: `Client`, `Agent`, `Conversation`, `TranscriptSegment`, `ConversationEvent` (`backend/app/db/models.py`)
- [ ] Implement `init_db()` function that creates all tables on startup
- [ ] Implement `close_db()` function for cleanup
- [ ] Wire DB lifecycle into FastAPI lifespan
- **Deliverable:** `backend/app/db/engine.py` + `backend/app/db/models.py` with all 5 tables
- **Dependencies:** 0.4

---

## Phase 1: Core Voice Pipeline

### 1.1 — Audio codec: mu-law ↔ PCM conversion
- [ ] Implement `mulaw_to_pcm(mulaw_bytes: bytes) -> bytes` using `audioop.ulaw2lin()`
- [ ] Implement `pcm_to_mulaw(pcm_bytes: bytes) -> bytes` using `audioop.lin2ulaw()`
- [ ] Implement `decode_twilio_payload(base64_string: str) -> bytes` (base64 decode + mu-law→PCM)
- [ ] Implement `encode_twilio_payload(pcm_bytes: bytes) -> str` (PCM→mu-law + base64 encode)
- [ ] Implement `transcode_elevenlabs_to_twilio(audio_bytes: bytes, input_format: str) -> bytes` using `pydub` (MP3/PCM → resample 8kHz → mu-law)
- [ ] Add unit tests for round-trip conversion (mu-law → PCM → mu-law should be lossy but acceptable)
- **Deliverable:** `backend/app/voice/audio_codec.py` with all conversion functions + tests
- **Dependencies:** 0.1

### 1.2 — VAD module: Silero VAD integration
- [ ] Create `SileroVAD` class with singleton model loading at startup
- [ ] Implement `process_frame(pcm_frame: bytes) -> float` that returns speech probability
- [ ] Implement state machine: `IDLE` → `SPEAKING` → `SILENT` (post-speech)
- [ ] Implement accumulation buffer: collect PCM frames while in `SPEAKING` state
- [ ] Implement `wait_for_utterance() -> bytes` async method that yields complete utterance buffer
- [ ] Configure silence threshold (default 500ms), speech threshold (0.5), debounce (300ms)
- [ ] Implement max utterance truncation at 30 seconds
- [ ] Emit `vad.speech_started` and `vad.speech_ended` events via event bus
- [ ] Add unit tests with mock ONNX model
- **Deliverable:** `backend/app/voice/vad.py` with `SileroVAD` class + tests
- **Dependencies:** 1.1, 0.5 (for event bus wiring later)

### 1.3 — STT client: Whisper API integration
- [ ] Create `WhisperClient` class with OpenAI async client initialization
- [ ] Implement `pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes` helper
- [ ] Implement `transcribe(pcm_audio: bytes) -> str` method
- [ ] Add 10-second timeout for API calls
- [ ] Implement exponential backoff retry (max 3 retries) for connection/timeout errors
- [ ] Handle empty/unintelligible results (return `None`)
- [ ] Emit `stt.completed` and `stt.error` events
- [ ] Define custom `STTError` exception
- [ ] Add unit tests with mocked OpenAI client
- **Deliverable:** `backend/app/voice/stt.py` with `WhisperClient` class + tests
- **Dependencies:** 1.1

### 1.4 — LLM client: GPT-4o with conversation history
- [ ] Create `GPT4oClient` class with OpenAI async client initialization
- [ ] Implement `generate(messages: list[dict]) -> str` method
- [ ] Implement conversation history management (append, truncate to max pairs)
- [ ] Prepend system prompt from agent config on every request
- [ ] Set `max_tokens: 300`, `temperature: 0.7`, 10-second timeout
- [ ] Implement exponential backoff retry (max 3 retries)
- [ ] Truncate responses at 2,500 chars before sending to TTS
- [ ] Emit `llm.completed` and `llm.error` events
- [ ] Define custom `LLMError` exception
- [ ] Add unit tests with mocked OpenAI client
- **Deliverable:** `backend/app/ai/llm.py` with `GPT4oClient` class + tests
- **Dependencies:** None (uses separate OpenAI client from STT)

### 1.5 — TTS client: ElevenLabs WebSocket streaming
- [ ] Create `ElevenLabsStreamingClient` class
- [ ] Implement WebSocket connection to `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`
- [ ] Implement `stream(text: str) -> AsyncIterator[tuple[bytes, int]]` yielding (audio_chunk, text_position)
- [ ] Send text input message with `generation_config` (model: `eleven_flash_v2_5`)
- [ ] Send flush message after complete text transmission
- [ ] Receive and yield streaming audio chunks as they arrive
- [ ] Implement `cancel()` method for interruption (close WebSocket, set cancelled flag)
- [ ] Handle 2,500 char limit: split text at sentence boundaries if exceeded
- [ ] Emit `tts.audio_chunk`, `tts.completed`, and `tts.error` events
- [ ] Define custom `TTSError` exception
- [ ] Add unit tests with mocked WebSocket
- **Deliverable:** `backend/app/voice/tts.py` with `ElevenLabsStreamingClient` class + tests
- **Dependencies:** 1.1 (for transcoding)

---

## Phase 2: Twilio Integration

### 2.1 — Channel adapter base class
- [ ] Create `ChannelAdapter` abstract base class (`backend/app/channels/base.py`)
- [ ] Define abstract methods: `connect()`, `send_audio()`, `clear_audio_buffer()`, `disconnect()`, `receive()`
- [ ] Add docstrings matching design §3.1
- **Deliverable:** `backend/app/channels/base.py` with `ChannelAdapter` ABC
- **Dependencies:** None

### 2.2 — Twilio adapter: WebSocket handler for Media Streams
- [ ] Create `TwilioAdapter` implementing `ChannelAdapter` (`backend/app/channels/twilio.py`)
- [ ] Accept FastAPI `WebSocket` connection in constructor
- [ ] Parse incoming Twilio JSON messages: `start`, `media`, `stop`, `close`
- [ ] Extract and store `streamSid` from `start` event
- [ ] Decode base64 mu-law payloads to raw bytes for `receive()` iterator
- [ ] Implement `send_audio()` that encodes mu-law bytes to base64 and sends JSON media message
- [ ] Implement `clear_audio_buffer()` that sends `clear` event to Twilio
- [ ] Implement `disconnect()` for graceful WebSocket close
- [ ] Handle WebSocket disconnection errors gracefully
- **Deliverable:** `backend/app/channels/twilio.py` with `TwilioAdapter` class
- **Dependencies:** 2.1, 1.1

### 2.3 — Outbound call initiation endpoint
- [ ] Create `POST /api/v1/calls/outbound` route (`backend/app/api/routes/calls.py`)
- [ ] Define request model: `phone_number`, `agent_id`, `client_id`
- [ ] Define response model: `session_id`, `status`, `twilio_call_sid`
- [ ] Validate E.164 phone number format (regex: `^\+[1-9]\d{1,14}$`)
- [ ] Use Twilio REST API to initiate outbound call (`client.calls.create()`)
- [ ] Generate TwiML URL that points to media stream endpoint
- [ ] Create `CallSession` via `SessionManager`
- [ ] Return 201 with session UUID and Twilio call SID
- [ ] Add unit tests with mocked Twilio client
- **Deliverable:** `backend/app/api/routes/calls.py` + request/response models + tests
- **Dependencies:** 2.2, 3.1 (session manager)

### 2.4 — TwiML generation for call routing
- [ ] Create TwiML response that instructs Twilio to open `<Stream>` WebSocket
- [ ] Stream URL format: `wss://{host}/api/v1/media-stream/{session_id}`
- [ ] Include custom parameters in TwiML: `session_id`, `agent_id`
- [ ] Create a helper endpoint or inline TwiML generation function
- [ ] Handle dynamic host/port from settings
- **Deliverable:** TwiML generation utility integrated into call initiation flow
- **Dependencies:** 2.3

### 2.5 — Media stream WebSocket endpoint
- [ ] Create `WebSocket /api/v1/media-stream/{session_id}` endpoint (`backend/app/api/routes/media_stream.py`)
- [ ] Accept WebSocket connection from Twilio
- [ ] Look up or create `CallSession` via `SessionManager`
- [ ] Instantiate `TwilioAdapter` with the WebSocket
- [ ] Hand off to `AgentOrchestrator` for conversation loop
- [ ] Handle WebSocket close and cleanup
- [ ] Add error handling that doesn't crash the service
- **Deliverable:** `backend/app/api/routes/media_stream.py` with WebSocket endpoint
- **Dependencies:** 2.2, 3.1, 3.3

---

## Phase 3: Agent Orchestrator

### 3.1 — Session manager with TTL cleanup
- [ ] Create `CallSession` dataclass with: `session_id`, `agent_config`, `channel`, `state`, `last_activity`, `history`, `resources`
- [ ] Create `SessionManager` class with `Dict[str, CallSession]` registry
- [ ] Implement `create_session(session_id, agent_config) -> CallSession`
- [ ] Implement `get_session(session_id) -> CallSession | None`
- [ ] Implement `remove_session(session_id)` with resource cleanup
- [ ] Implement `ttl_sweeper()` background task (checks every 60s, TTL default 300s)
- [ ] On TTL expiration: close WebSocket, persist partial transcript, emit `conversation.timed_out`, release resources
- [ ] Implement `update_activity(session_id)` called on each media message
- [ ] Add unit tests for session lifecycle
- **Deliverable:** `backend/app/agents/session_manager.py` with `CallSession` + `SessionManager` + tests
- **Dependencies:** 0.5, 3.2

### 3.2 — Agent configuration models
- [ ] Create `AgentConfig` Pydantic model matching spec §6.2
- [ ] Fields: `agent_id`, `name`, `system_prompt`, `voice_id`, `language`, `max_history_messages`, `max_response_tokens`, `speech_end_silence_ms`, `max_utterance_duration_s`, `fallback_language`
- [ ] Create `CallRequest` model for inbound API: `phone_number`, `agent_id`, `client_id`
- [ ] Create `CallResponse` model: `session_id`, `status`, `twilio_call_sid`
- [ ] Add validation for required fields and value ranges
- [ ] Create `backend/app/agents/models.py`
- **Deliverable:** `backend/app/agents/models.py` with all Pydantic models
- **Dependencies:** None

### 3.3 — Conversation state machine
- [ ] Create `CallState` enum: `INITIATED`, `CONNECTED`, `LISTENING`, `PROCESSING`, `SPEAKING`, `COMPLETED`, `FAILED`, `TIMED_OUT`
- [ ] Implement state transition validation (only allowed transitions per design §6.2)
- [ ] Implement `transition_to(new_state)` method with logging
- [ ] Emit events on state transitions
- [ ] Add unit tests for all valid and invalid transitions
- **Deliverable:** `backend/app/agents/state.py` with `CallState` enum and transition logic + tests
- **Dependencies:** 3.2

### 3.4 — Event bus implementation
- [ ] Create `EventType` enum with all event types from spec §6.6
- [ ] Create `Event` dataclass: `type`, `session_id`, `timestamp`, `payload`, `version`
- [ ] Create `EventBus` class with `subscribe(event_type, handler)` and `emit(event)` methods
- [ ] Implement structured JSON logging for all events
- [ ] Implement SQLite persistence for events (async write to `conversation_events` table)
- [ ] Handle subscriber errors gracefully (log but don't crash)
- [ ] Add unit tests for pub/sub behavior
- **Deliverable:** `backend/app/recording/events.py` with `EventBus` + tests
- **Dependencies:** 0.5

### 3.5 — Main conversation loop
- [ ] Create `AgentOrchestrator` class (`backend/app/agents/orchestrator.py`)
- [ ] Constructor accepts: `CallSession`, `ChannelAdapter`, `AudioCodec`, `SileroVAD`, `WhisperClient`, `GPT4oClient`, `ElevenLabsStreamingClient`, `EventBus`, `ConversationRecorder`
- [ ] Implement `run_conversation()` async method (matches design §3.7 pseudocode)
- [ ] Send initial greeting on connection
- [ ] Main loop: VAD → STT → LLM → TTS cycle
- [ ] Handle STT errors with fallback message (continue conversation)
- [ ] Handle LLM errors with fallback message (end call gracefully)
- [ ] Handle TTS errors with pre-recorded apology audio (continue conversation)
- [ ] Handle empty/unintelligible utterances with prompt to repeat
- **Deliverable:** `backend/app/agents/orchestrator.py` with `AgentOrchestrator` class
- **Dependencies:** 1.2, 1.3, 1.4, 1.5, 2.2, 3.3, 3.4, 4.1

### 3.6 — Interruption handling (barge-in)
- [ ] Implement `_speaking` flag and `_interrupted` flag in `AgentOrchestrator`
- [ ] Implement `_speak(text: str) -> str` method with interruption-aware delivery
- [ ] VAD speech-start callback checks `_speaking` flag → sets `_interrupted = True`
- [ ] On interruption: stop sending audio to Twilio immediately
- [ ] Send `clear` event to Twilio to flush audio buffer
- [ ] Close active ElevenLabs WebSocket connection
- [ ] Discard remaining chunks in delivery queue
- [ ] Emit `interruption.detected` event with delivered portion
- [ ] Process user's interrupting utterance as new conversational turn
- [ ] Only add delivered portion to conversation history
- [ ] Add unit tests for interruption scenarios
- **Deliverable:** Interruption logic in `AgentOrchestrator` + tests
- **Dependencies:** 3.5

### 3.7 — Streaming TTS → Twilio audio delivery
- [ ] Implement `asyncio.Queue`-based streaming pipeline for TTS chunks
- [ ] Producer task: receives chunks from ElevenLabs WebSocket
- [ ] Consumer task: transcodes (pydub → resample 8kHz → mu-law) and sends to Twilio
- [ ] Queue maxsize=5 for backpressure
- [ ] Both tasks check `cancelled` flag for interruption support
- [ ] Clear queue on interruption
- [ ] Emit `tts.audio_chunk` per chunk, `tts.completed` at end
- **Deliverable:** Streaming delivery pipeline integrated into `AgentOrchestrator._speak()`
- **Dependencies:** 3.5, 3.6, 1.1, 1.5

---

## Phase 4: Recording & Events

### 4.1 — Conversation recorder (SQLite persistence)
- [ ] Create `ConversationRecorder` class (`backend/app/recording/recorder.py`)
- [ ] Implement `record_segment(conversation_id, role, text, timestamp, metadata)` for transcript segments
- [ ] Implement `finalize_conversation(conversation_id, status, ended_at, duration, error_message)` for conversation metadata
- [ ] Implement `get_conversation(conversation_id) -> dict` for retrieval with full transcript
- [ ] Batch writes where possible (write user+agent pair together)
- [ ] Handle partial transcript persistence on session timeout
- [ ] Add unit tests with in-memory SQLite
- **Deliverable:** `backend/app/recording/recorder.py` with `ConversationRecorder` + tests
- **Dependencies:** 0.5, 3.2

### 4.2 — Event bus integration with post-conversation events
- [ ] Wire `EventBus` into `AgentOrchestrator` for all pipeline stage events
- [ ] Emit `conversation.completed` on normal call end (Twilio `stop`)
- [ ] Emit `conversation.failed` on unrecoverable error
- [ ] Emit `conversation.timed_out` on TTL expiration
- [ ] Include full transcript, duration, status, and error info in completion events
- [ ] Create subscriber for conversation completion that triggers final transcript persistence
- **Deliverable:** Event emission integrated throughout orchestrator lifecycle
- **Dependencies:** 3.4, 3.5, 4.1

### 4.3 — Agent model with configurable system prompt
- [ ] Create agent config JSON loader (`backend/agents/configs/`)
- [ ] Create sample `sales-agent-01.json` with spec §9.2 example
- [ ] Implement `load_agent_config(agent_id: str) -> AgentConfig` function
- [ ] Implement `list_agent_configs() -> list[AgentConfig]` function
- [ ] Validate config on load (required fields, valid voice_id format)
- [ ] Support hot-reload without service restart
- **Deliverable:** Agent config loading system + sample config file
- **Dependencies:** 3.2

### 4.4 — Fallback audio setup
- [ ] Create `backend/fallback_audio/` directory
- [ ] Generate or provide `apology_es.wav` pre-recorded audio file (Spanish apology message)
- [ ] Implement `play_fallback_audio(channel: ChannelAdapter, wav_path: str)` helper
- [ ] Integrate fallback audio playback into TTS error handling in orchestrator
- **Deliverable:** Fallback audio file + playback utility
- **Dependencies:** 2.2

---

## Phase 5: API & Testing

### 5.1 — FastAPI endpoints: complete API surface
- [ ] `POST /api/v1/calls/outbound` — initiate outbound call (already started in 2.3, finalize)
- [ ] `GET /api/v1/conversations/{conversation_id}` — retrieve conversation with full transcript
- [ ] `GET /api/v1/health` — health check with active sessions count and uptime
- [ ] `WebSocket /api/v1/media-stream/{session_id}` — media stream (already in 2.5, finalize)
- [ ] Register all routes in `main.py`
- [ ] Add OpenAPI documentation with descriptions and examples
- **Deliverable:** Complete API with all 4 endpoints documented
- **Dependencies:** 2.3, 2.5, 3.1, 4.1

### 5.2 — Mock-based integration tests
- [ ] Set up `conftest.py` with pytest fixtures (mock OpenAI, mock ElevenLabs, mock Twilio)
- [ ] Test `test_audio_codec.py`: round-trip mu-law ↔ PCM, Twilio payload encode/decode
- [ ] Test `test_vad.py`: speech detection state transitions with mock ONNX
- [ ] Test `test_stt.py`: successful transcription, API error, empty result, retry logic
- [ ] Test `test_llm.py`: response generation, history management, API error, truncation
- [ ] Test `test_tts.py`: streaming chunks, cancellation, char limit splitting, error handling
- [ ] Test `test_twilio_adapter.py`: message parsing, send/clear, WebSocket lifecycle
- [ ] Test `test_event_bus.py`: subscribe/emit, error handling, persistence
- [ ] Test `test_recorder.py`: segment recording, conversation finalization, retrieval
- [ ] Test `test_orchestrator.py`: happy path, interruption, error recovery flows
- **Deliverable:** 10 test files with comprehensive mock-based coverage
- **Dependencies:** All previous phases

### 5.3 — End-to-end test script
- [ ] Create `tests/e2e/test_full_conversation.py` script
- [ ] Simulate Twilio WebSocket connection using `websockets` client
- [ ] Send mock audio chunks (pre-recorded mu-law samples)
- [ ] Verify complete conversation flow with all mocked services
- [ ] Test interruption by sending audio while agent is "speaking"
- [ ] Verify transcript persistence in SQLite
- [ ] Verify event emission
- [ ] Create mock audio fixtures (mu-law sample files)
- **Deliverable:** E2E test script that runs full conversation cycle with mocks
- **Dependencies:** 5.2

### 5.4 — README with setup instructions
- [ ] Project overview and architecture description
- [ ] Prerequisites (Python 3.11+, ffmpeg for pydub)
- [ ] Installation steps (`pip install`, `ffmpeg` installation)
- [ ] Environment configuration (copy `.env.example`, fill in API keys)
- [ ] How to run the service (`uvicorn backend.app.main:app --reload`)
- [ ] How to run tests (`pytest`)
- [ ] API documentation reference (Swagger UI at `/docs`)
- [ ] Agent configuration guide (how to add new agents)
- [ ] Troubleshooting section (common issues: ffmpeg not found, API key errors)
- **Deliverable:** `backend/README.md`
- **Dependencies:** All previous phases

### 5.5 — System prompt templates
- [ ] Create `backend/app/agents/prompts/templates.py`
- [ ] Define base system prompt template with placeholders for agent name, company, role
- [ ] Define fallback messages in Spanish: STT fallback, LLM fallback, empty utterance prompt
- [ ] Add template rendering utility
- **Deliverable:** `backend/app/agents/prompts/templates.py` with prompt templates
- **Dependencies:** 3.2

---

## Phase 6: Wiring & Integration

### 6.1 — Wire all components in FastAPI lifespan
- [ ] Initialize all singletons in startup: `Settings`, `EventBus`, `SessionManager`, `SileroVAD`, `AudioCodec`, `WhisperClient`, `GPT4oClient`, `ElevenLabsStreamingClient`, `ConversationRecorder`
- [ ] Start TTL sweeper background task
- [ ] Initialize database tables
- [ ] Load agent configurations
- [ ] Implement graceful shutdown: cancel TTL sweeper, close all active sessions, persist partial transcripts, close DB connections
- **Deliverable:** Complete lifespan in `main.py` with all component initialization
- **Dependencies:** All previous phases

### 6.2 — API dependencies and injection
- [ ] Create `backend/app/api/dependencies.py` with FastAPI dependency functions
- [ ] `get_settings()` → yield Settings
- [ ] `get_session_manager()` → yield SessionManager
- [ ] `get_event_bus()` → yield EventBus
- [ ] `get_recorder()` → yield ConversationRecorder
- [ ] Wire dependencies into route handlers
- **Deliverable:** `backend/app/api/dependencies.py` + wired routes
- **Dependencies:** 5.1, 6.1

### 6.3 — Structured logging throughout
- [ ] Configure `structlog` with JSON output in `main.py`
- [ ] Add session context to all log entries (session_id, agent_id)
- [ ] Log all state transitions
- [ ] Log all API calls with latency
- [ ] Log all errors with full context
- **Deliverable:** Structured JSON logging across all components
- **Dependencies:** 6.1

---

## Task Dependency Graph

```
Phase 0: 0.1 → 0.3 → 0.4 → 0.5
         0.2 → 0.3

Phase 1: 0.1 → 1.1 → 1.2 → 3.5
                   → 1.3 → 3.5
                   → 1.5 → 3.5
         1.4 → 3.5

Phase 2: 2.1 → 2.2 → 2.3 → 2.4
                   → 2.5
         1.1 → 2.2

Phase 3: 0.5 → 3.1
         3.2 → 3.1
         3.2 → 3.3
         0.5 → 3.4
         1.2, 1.3, 1.4, 1.5, 2.2, 3.3, 3.4, 4.1 → 3.5
         3.5 → 3.6 → 3.7

Phase 4: 0.5, 3.2 → 4.1
         3.4, 3.5, 4.1 → 4.2
         3.2 → 4.3
         2.2 → 4.4

Phase 5: 2.3, 2.5, 3.1, 4.1 → 5.1
         All phases → 5.2 → 5.3
         All phases → 5.4
         3.2 → 5.5

Phase 6: All phases → 6.1 → 6.2
         6.1 → 6.3
```

---

## Recommended Execution Order

| Session | Tasks | Focus Area |
|---------|-------|------------|
| 1 | 0.1, 0.2, 0.3, 0.4, 0.5 | Project skeleton: deps, config, app, DB |
| 2 | 1.1, 1.3, 1.4 | Audio codec + STT + LLM clients |
| 3 | 1.2, 1.5 | VAD + TTS streaming client |
| 4 | 2.1, 2.2, 2.4, 2.5 | Channel abstraction + Twilio adapter + WS endpoint |
| 5 | 3.1, 3.2, 3.3, 3.4 | Session manager + models + state machine + event bus |
| 6 | 3.5, 3.6, 3.7 | Orchestrator core loop + interruption + streaming |
| 7 | 4.1, 4.2, 4.3, 4.4 | Recording + events + agent configs + fallback audio |
| 8 | 5.1, 5.5 | Complete API surface + prompt templates |
| 9 | 6.1, 6.2, 6.3 | Full wiring + dependencies + structured logging |
| 10 | 5.2 | Mock-based integration tests |
| 11 | 5.3 | End-to-end test script |
| 12 | 5.4 | README + documentation |

---

## Risks and Mitigations

| Risk | Affected Tasks | Mitigation |
|------|---------------|------------|
| **ElevenLabs WebSocket API changes** | 1.5, 3.7 | Test with actual API early; wrap in abstraction for easy updates |
| **Silero VAD ONNX model loading issues** | 1.2 | Have fallback VAD (energy-based) as backup; test model loading in isolation |
| **Twilio Media Streams WebSocket quirks** | 2.2, 2.5 | Test with actual Twilio sandbox early; handle edge cases in message parsing |
| **Audio quality in mu-law ↔ PCM cycles** | 1.1, 3.7 | Validate with actual audio samples; use pydub for complex conversions |
| **Race conditions in interruption handling** | 3.6, 3.7 | Use `asyncio.Lock` per session; atomic state transitions; thorough testing |
| **ffmpeg dependency for pydub** | 1.1, 1.5, 3.7 | Document clearly in README; provide Docker alternative; test without ffmpeg for codec-only path |
| **OpenAI API rate limits during testing** | 1.3, 1.4 | Use mocks for all tests; reserve real API calls for E2E only |
