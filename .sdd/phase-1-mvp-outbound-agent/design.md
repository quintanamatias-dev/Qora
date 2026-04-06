# Technical Design: Phase 1 — MVP Outbound Call Agent with ElevenLabs Pipeline

**Status:** Draft  
**Version:** 1.0.0  
**Date:** 2026-03-30  
**Author:** SDD Design Agent  
**Change ID:** `phase-1-mvp-outbound-agent`  
**Spec Reference:** [spec.md](./spec.md)

---

## 1. Executive Summary

This document defines the technical architecture and implementation approach for the V1-CallCenter MVP: a real-time AI outbound call agent. The system orchestrates four external services — Twilio (telephony), Silero VAD (voice detection), OpenAI Whisper (speech-to-text), OpenAI GPT-4o (conversation brain), and ElevenLabs (streaming text-to-speech) — into a single async Python service built on FastAPI.

**Key architectural decisions:**
- **Channel abstraction pattern** from day one: the `ChannelAdapter` interface isolates Twilio-specific logic so inbound, WhatsApp, and other channels can be added without touching the core conversation loop.
- **Event-driven internal communication**: an async pub/sub event bus decouples components, enabling future external consumers (webhooks, analytics, external orchestrators).
- **Session-isolated state**: each call runs in its own `CallSession` with no shared mutable state, enabling horizontal scaling in Phase 2.
- **Streaming-first audio pipeline**: TTS audio is forwarded to Twilio as it arrives from ElevenLabs, minimizing perceived latency.

**Target latency budget (per conversation turn):**

| Stage | Target | Notes |
|-------|--------|-------|
| VAD (speech end detection) | < 20ms/frame | Silero ONNX inference |
| STT (Whisper API) | < 2s | Batch endpoint, 1-3s typical |
| LLM (GPT-4o) | < 1.5s | 10-message history, 300 max tokens |
| TTS (ElevenLabs TTFB) | < 200ms | eleven_flash_v2_5 model |
| **Total cycle** | **< 1.5s** (excluding STT) | STT is the dominant variable |

---

## 2. Architecture Overview

### 2.1 System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            V1-CallCenter Service                             │
│                                                                             │
│  ┌─────────────┐    ┌──────────────────────────────────────────────────┐    │
│  │  FastAPI     │    │              SessionManager                       │    │
│  │  Router      │    │  ┌────────────────────────────────────────────┐  │    │
│  │             │    │  │  sessions: Dict[str, CallSession]          │  │    │
│  │ POST/calls  │───►│  │  ttl_sweeper: asyncio.Task                 │  │    │
│  │ WS /media   │    │  └────────────────────────────────────────────┘  │    │
│  │ GET /conv   │    │                                                  │    │
│  │ GET /health │    │  ┌────────────────────────────────────────────┐  │    │
│  └─────────────┘    │  │              CallSession                     │  │    │
│                     │  │  ┌──────────────────────────────────────┐  │  │    │
│                     │  │  │  ChannelAdapter (TwilioAdapter)      │  │  │    │
│                     │  │  │  - WS recv/send (mu-law 8kHz)        │  │  │    │
│                     │  │  │  - audio format conversion           │  │  │    │
│                     │  │  └──────────────┬───────────────────────┘  │  │    │
│                     │  │                 │                          │  │    │
│                     │  │  ┌──────────────▼───────────────────────┐  │  │    │
│                     │  │  │  AudioPipeline                        │  │  │    │
│                     │  │  │  - mu-law ↔ PCM transcoding           │  │  │    │
│                     │  │  │  - chunk buffering & streaming        │  │  │    │
│                     │  │  └──────────────┬───────────────────────┘  │  │    │
│                     │  │                 │                          │  │    │
│                     │  │  ┌──────────────▼───────────────────────┐  │  │    │
│                     │  │  │  VAD (Silero ONNX)                    │  │  │    │
│                     │  │  │  - speech start/end detection         │  │  │    │
│                     │  │  └──────────────┬───────────────────────┘  │  │    │
│                     │  │                 │                          │  │    │
│                     │  │  ┌──────────────▼───────────────────────┐  │  │    │
│                     │  │  │  STT (Whisper API)                    │  │  │    │
│                     │  │  │  - audio → text transcription         │  │  │    │
│                     │  │  └──────────────┬───────────────────────┘  │  │    │
│                     │  │                 │                          │  │    │
│                     │  │  ┌──────────────▼───────────────────────┐  │  │    │
│                     │  │  │  LLM (GPT-4o)                         │  │  │    │
│                     │  │  │  - conversation brain                 │  │  │    │
│                     │  │  └──────────────┬───────────────────────┘  │  │    │
│                     │  │                 │                          │  │    │
│                     │  │  ┌──────────────▼───────────────────────┐  │  │    │
│                     │  │  │  TTS (ElevenLabs WS Streaming)        │  │  │    │
│                     │  │  │  - text → streaming audio             │  │  │    │
│                     │  │  └──────────────┬───────────────────────┘  │  │    │
│                     │  │                 │                          │  │    │
│                     │  │  ┌──────────────▼───────────────────────┐  │  │    │
│                     │  │  │  AgentOrchestrator                    │  │  │    │
│                     │  │  │  - state machine                      │  │  │    │
│                     │  │  │  - interruption handling              │  │  │    │
│                     │  │  │  - conversation loop                  │  │  │    │
│                     │  │  └──────────────────────────────────────┘  │  │    │
│                     │  └────────────────────────────────────────────┘  │    │
│                     │                                                  │    │
│                     │  ┌────────────────────────────────────────────┐  │    │
│                     │  │              EventBus                       │  │    │
│                     │  │  - async pub/sub, structured logging       │  │    │
│                     │  │  - event persistence (SQLite)              │  │    │
│                     │  └────────────────────────────────────────────┘  │    │
│                     │                                                  │    │
│                     │  ┌────────────────────────────────────────────┐  │    │
│                     │  │              SQLite (MVP)                   │  │    │
│                     │  │  - clients, agents, conversations          │  │    │
│                     │  │  - transcript_segments, events             │  │    │
│                     │  └────────────────────────────────────────────┘  │    │
│                     └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
         ▲
         │ WebSocket (mu-law 8kHz, ~20ms chunks)
         │
┌────────┴────────┐          ┌──────────────┐     ┌──────────────┐
│    Twilio       │          │  OpenAI      │     │  ElevenLabs  │
│  Media Streams  │          │  Whisper API │     │  WS TTS      │
│  REST API       │          │  GPT-4o API  │     │  Streaming   │
└─────────────────┘          └──────────────┘     └──────────────┘
```

### 2.2 Component Interaction Sequence (Happy Path)

```
Twilio          TwilioAdapter    AudioPipeline    VAD       STT        LLM        TTS        EventBus
  │                 │               │              │         │          │          │           │
  │──start────────►│                │              │         │          │          │           │
  │                 │──session.start─────────────────────────────────────────────────────────►│
  │                 │               │              │         │          │          │           │
  │──media(chunk)─►│               │              │         │          │          │           │
  │                 │──decode─────►│              │         │          │          │           │
  │                 │               │──pcm_frame──►│         │          │          │           │
  │                 │               │              │──vad───►│          │          │           │
  │                 │               │              │ speech  │          │          │           │
  │                 │               │              │ start   │          │          │           │
  │                 │               │              │──vad.speech_started────────────────────►│
  │                 │               │              │         │          │          │           │
  │──media(chunk)─►│──...accumulate utterance...──►│         │          │          │           │
  │                 │               │              │──vad───►│          │          │           │
  │                 │               │              │ speech  │          │          │           │
  │                 │               │              │ end     │          │          │           │
  │                 │               │              │──vad.speech_ended(audio)──────────────►│
  │                 │               │              │         │          │          │           │
  │                 │               │              │         │──transcribe                │
  │                 │               │              │         │◄──text                     │
  │                 │               │              │         │──stt.completed─────────────►│
  │                 │               │              │         │          │          │           │
  │                 │               │              │         │          │──generate│           │
  │                 │               │              │         │          │◄──response        │
  │                 │               │              │         │          │──llm.completed────►│
  │                 │               │              │         │          │          │           │
  │                 │               │              │         │          │          │──stream  │
  │                 │               │              │         │          │          │◄──chunk  │
  │                 │               │              │         │          │          │──tts.chunk►
  │                 │               │◄──encode────│         │          │          │           │
  │◄──media(chunk)─│               │              │         │          │          │           │
  │                 │               │              │         │          │          │◄──done   │
  │                 │               │              │         │          │          │──tts.done►
  │                 │               │              │         │          │          │           │
  │──stop─────────►│                │              │         │          │          │           │
  │                 │──conv.completed───────────────────────────────────────────────────────►│
```

---

## 3. Component Design

### 3.1 Channel Abstraction

#### `channels/base.py` — `ChannelAdapter` (Abstract Base)

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class ChannelAdapter(ABC):
    """Abstract interface for telephony/messaging channels.
    
    Implementations handle channel-specific protocols (Twilio Media Streams,
    WhatsApp Cloud API, etc.) and normalize them into a common audio/text
    event stream for the AgentOrchestrator.
    """
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish the channel connection."""
    
    @abstractmethod
    async def send_audio(self, chunk: bytes) -> None:
        """Send a mu-law 8kHz audio chunk to the channel."""
    
    @abstractmethod
    async def clear_audio_buffer(self) -> None:
        """Clear any queued/buffered audio on the channel side."""
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the channel connection."""
    
    @abstractmethod
    async def receive(self) -> AsyncIterator[bytes]:
        """Yield incoming audio chunks as raw mu-law 8kHz bytes."""
```

**Design rationale:** The channel adapter isolates all protocol-specific logic. The orchestrator only knows about `send_audio()`, `clear_audio_buffer()`, and `receive()`. Adding WhatsApp or inbound calls means implementing a new adapter — zero changes to the core pipeline.

#### `channels/twilio.py` — `TwilioAdapter`

**Responsibilities:**
- Accept WebSocket connections from Twilio Media Streams at `/api/v1/media-stream/{session_id}`
- Parse Twilio JSON messages: `start`, `media`, `stop`, `close`
- Decode base64 mu-law payloads to raw bytes for the pipeline
- Encode outgoing PCM audio back to base64 mu-law for Twilio
- Send `clear` messages to flush Twilio's audio buffer during interruptions

**WebSocket message format (incoming):**
```json
{
  "event": "media",
  "streamSid": "MStreamSid...",
  "media": {
    "payload": "<base64-encoded-mulaw>",
    "track": "inbound",
    "chunk": 1
  }
}
```

**WebSocket message format (outgoing):**
```json
{
  "event": "media",
  "streamSid": "MStreamSid...",
  "media": {
    "payload": "<base64-encoded-mulaw>"
  }
}
```

**Clear message (for interruptions):**
```json
{
  "event": "clear",
  "streamSid": "MStreamSid..."
}
```

**Key implementation details:**
- Uses `fastapi.WebSocket` for the connection
- Stores `streamSid` from the `start` event — required for all outgoing messages
- Incoming chunks are ~20ms of mu-law audio (160 bytes per chunk at 8kHz)
- Outgoing chunks should match Twilio's expected size for smooth playback

---

### 3.2 Audio Pipeline

#### `voice/audio_codec.py` — Format Conversion

**Responsibilities:**
- Decode mu-law (PCMU) 8kHz → PCM 16-bit signed 8kHz (for VAD/STT)
- Encode PCM 16-bit signed 8kHz → mu-law (PCMU) 8kHz (for Twilio)
- Handle ElevenLabs output (MP3 or PCM) → PCM 16-bit 8kHz → mu-law

**Conversion chain:**
```
Twilio (mu-law 8kHz, base64)
    │
    ▼ [base64 decode]
mu-law bytes
    │
    ▼ [audioop.ulaw2lin() or pydub]
PCM 16-bit signed 8kHz
    │
    ▼ [VAD processing]
    ▼ [STT: send to Whisper as WAV bytes]
    │
    ▼ [TTS output: ElevenLabs MP3/PCM]
MP3 or PCM (variable sample rate)
    │
    ▼ [pydub: resample to 8kHz, convert to PCM 16-bit]
PCM 16-bit signed 8kHz
    │
    ▼ [audioop.lin2ulaw() or pydub]
mu-law bytes
    │
    ▼ [base64 encode]
Twilio media payload
```

**Library choice:** `audioop` (stdlib) for mu-law ↔ PCM conversion (fast, no dependencies). `pydub` + `ffmpeg` for MP3 decoding and resampling from ElevenLabs output.

**Performance note:** `audioop.ulaw2lin()` and `audioop.lin2ulaw()` operate in C and handle 160-byte chunks in < 1ms. This is the preferred path for the hot loop.

---

### 3.3 Voice Activity Detection

#### `voice/vad.py` — `SileroVAD`

**Responsibilities:**
- Load Silero VAD ONNX model at startup (singleton)
- Process incoming PCM frames (256 samples = 32ms at 8kHz)
- Track speech state: `IDLE` → `SPEAKING` → `SILENT` (post-speech)
- Emit `vad.speech_started` on transition to SPEAKING
- Emit `vad.speech_ended` with accumulated audio buffer on silence threshold expiry

**Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `sample_rate` | 8000 | Audio sample rate (must match Twilio) |
| `frame_samples` | 256 | Samples per frame (32ms at 8kHz) |
| `speech_threshold` | 0.5 | Probability threshold for speech detection |
| `silence_threshold_ms` | 500 | Silence duration to mark speech end |
| `max_utterance_s` | 30 | Maximum utterance duration before truncation |

**State machine:**
```
IDLE ──[prob > threshold]──► SPEAKING ──[prob < threshold for N ms]──► SILENT
  ▲                                                                    │
  └──────────────────────[reset after speech_ended]────────────────────┘
```

**Accumulation buffer:** While in SPEAKING state, all PCM frames are appended to a `bytearray`. On speech end, the complete buffer is yielded for STT processing.

**Debouncing:** A 300ms debounce window prevents false speech-start triggers from brief noise spikes.

---

### 3.4 Speech-to-Text

#### `voice/stt.py` — `WhisperClient`

**Responsibilities:**
- Send accumulated PCM audio to OpenAI Whisper API (`/v1/audio/transcriptions`)
- Convert PCM bytes to WAV format in-memory (required by Whisper API)
- Use `whisper-1` model with `response_format: "text"`
- Apply 10-second timeout for API calls
- Return transcribed text or raise `STTError`

**Audio preparation:**
```python
import io
import wave

def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 8000) -> bytes:
    """Convert raw PCM 16-bit bytes to WAV format for Whisper API."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
```

**Error handling:**
- `openai.APIConnectionError` → retry with exponential backoff (max 3)
- `openai.RateLimitError` → retry with longer backoff
- `openai.APITimeoutError` → return fallback message
- Empty/unintelligible result → return `None` (orchestrator handles with prompt)

---

### 3.5 Conversational Brain

#### `ai/llm.py` — `GPT4oClient`

**Responsibilities:**
- Maintain conversation history as `list[dict[str, str]]` (role/content pairs)
- Prepend system prompt from agent config on every request
- Limit history to most recent N message pairs (default: 10)
- Set `max_tokens: 300`, `temperature: 0.7`
- Apply 10-second timeout
- Return generated text or raise `LLMError`

**Message structure:**
```python
messages = [
    {"role": "system", "content": agent_config.system_prompt},
    {"role": "user", "content": "Hola, bien, ¿quién habla?"},
    {"role": "assistant", "content": "Soy Ana, la asistente virtual de TechCorp..."},
    {"role": "user", "content": "Ah, genial. ¿Me puedes ayudar con...?"},
    # ... up to max_history_messages pairs
]
```

**History management:**
- On each new turn, append `{"role": "user", "content": transcription}` then `{"role": "assistant", "content": response}`
- If history exceeds `max_history_messages * 2` entries, truncate oldest pairs (keeping system prompt)
- On interruption: only append the *delivered portion* of the agent response, not the full generated text

**Error handling:**
- API errors → return fallback message: *"Lo siento, estoy teniendo problemas técnicos..."*
- Timeout → same fallback, log warning
- Response too long → truncate at 2,500 chars before sending to TTS

---

### 3.6 Text-to-Speech

#### `voice/tts.py` — `ElevenLabsStreamingClient`

**Responsibilities:**
- Establish WebSocket connection to `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`
- Send text input message with `generation_config`
- Send `flush` message to trigger audio generation
- Receive streaming audio chunks (MP3 or PCM)
- Handle interruption by closing WebSocket and cancelling tasks
- Respect 2,500 character limit per generation (split if needed)

**WebSocket protocol:**
```
Client → ElevenLabs:
{
  "text": "Hola, ¿cómo estás?",
  "generation_config": {
    "chunk_length_schedule": [120],
    "model_id": "eleven_flash_v2_5"
  }
}
Client → ElevenLabs:
{ "text": "" }  // flush signal

ElevenLabs → Client:
{ "audio": "<base64-encoded-audio-chunk>" }
...
{ "isFinal": true }  // end of stream
```

**Streaming delivery strategy:**
1. Open WebSocket to ElevenLabs
2. Send text + flush
3. As audio chunks arrive:
   a. Decode (MP3 → PCM via pydub) if needed
   b. Resample to 8kHz if needed
   c. Convert to mu-law
   d. Send to Twilio immediately (streaming, not batched)
4. On `isFinal`: close WebSocket, emit `tts.completed`

**Interruption handling:**
- Set an `asyncio.Event` flag `cancelled`
- When interruption detected, set flag and close WebSocket
- The chunk delivery task checks the flag before each send
- Any chunks already in the Twilio send queue are discarded

**Character limit handling:**
- If LLM response > 2,500 chars, split at sentence boundaries
- Send each segment as a separate TTS generation
- Queue segments for sequential delivery

---

### 3.7 Agent Orchestrator

#### `agents/orchestrator.py` — `AgentOrchestrator`

**Responsibilities:**
- Main conversation loop: coordinates VAD → STT → LLM → TTS pipeline
- Manages call state machine
- Handles interruption detection and recovery
- Coordinates audio delivery to Twilio
- Emits events for each pipeline stage

**State machine:**
```
                    ┌─────────────────────────────────────────────┐
                    │                                             │
                    ▼                                             │
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
│INITIATED  │─►│CONNECTED  │─►│LISTENING  │─►│PROCESSING │─►│ SPEAKING  │
└───────────┘  └───────────┘  └───────────┘  └───────────┘  └───────────┘
                                                    │              │
                                                    ▼              │
                                             ┌───────────┐       │
                                             │  FAILED   │       │
                                             └───────────┘       │
                                                    ▲              │
                                                    │              │
                                             ┌───────────┐       │
                                             │ COMPLETED │◄──────┘
                                             └───────────┘
```

**State transitions:**
| From | To | Trigger |
|------|-----|---------|
| INITIATED | CONNECTED | Twilio `start` event received |
| CONNECTED | LISTENING | After sending initial greeting |
| LISTENING | PROCESSING | VAD detects speech end |
| PROCESSING | SPEAKING | LLM response received, TTS started |
| SPEAKING | LISTENING | TTS completed |
| SPEAKING | PROCESSING | Interruption detected (VAD speech start while speaking) |
| ANY | COMPLETED | Twilio `stop` event |
| ANY | FAILED | Unrecoverable error |

**Conversation loop pseudocode:**
```python
async def run_conversation(self):
    self.state = CallState.CONNECTED
    await self.event_bus.emit(EventType.SESSION_STARTED, {...})
    
    # Send greeting
    greeting = await self.llm.generate([system_prompt, {"role": "user", "content": "Start the conversation with a greeting"}])
    await self._speak(greeting)
    
    self.state = CallState.LISTENING
    
    while self.state not in (CallState.COMPLETED, CallState.FAILED):
        # Wait for VAD to detect speech end
        audio_buffer = await self.vad.wait_for_utterance()
        
        self.state = CallState.PROCESSING
        
        # STT
        try:
            text = await self.stt.transcribe(audio_buffer)
        except STTError:
            await self._speak(self.agent.fallback_stt_message)
            self.state = CallState.LISTENING
            continue
        
        if not text or not text.strip():
            await self._speak("No pude escucharte bien, ¿podrías repetir?")
            self.state = CallState.LISTENING
            continue
        
        # LLM
        try:
            response = await self.llm.generate(self.history + [{"role": "user", "content": text}])
        except LLMError:
            await self._speak(self.agent.fallback_llm_message)
            self.state = CallState.FAILED
            break
        
        # TTS + speak
        self.state = CallState.SPEAKING
        delivered = await self._speak(response)
        
        # Record in history (only delivered portion if interrupted)
        self.history.append({"role": "user", "content": text})
        self.history.append({"role": "assistant", "content": delivered})
        self.history = self.history[-(self.agent.max_history_messages * 2):]
        
        self.state = CallState.LISTENING
```

**Interruption handling detail:**
```python
async def _speak(self, text: str) -> str:
    """Speak text via TTS, return the portion actually delivered."""
    self._speaking = True
    self._interrupted = False
    self._delivered_chars = 0
    
    try:
        async for audio_chunk, text_position in self.tts.stream(text):
            if self._interrupted:
                break
            mu_law_chunk = self.audio_codec.encode(audio_chunk)
            await self.channel.send_audio(mu_law_chunk)
            self._delivered_chars = text_position
    finally:
        self._speaking = False
    
    if self._interrupted:
        await self.channel.clear_audio_buffer()
        await self.event_bus.emit(EventType.INTERRUPTION_DETECTED, {
            "delivered_chars": self._delivered_chars,
            "total_chars": len(text),
        })
    
    return text[:self._delivered_chars] if self._interrupted else text

def on_vad_speech_start(self):
    """Called when VAD detects speech while agent is speaking."""
    if self._speaking:
        self._interrupted = True
```

---

### 3.8 Session Management

#### `agents/session_manager.py` — `SessionManager`

**Responsibilities:**
- Maintain registry of active sessions: `Dict[str, CallSession]`
- Create sessions on outbound call initiation
- Clean up zombie sessions via TTL sweeper
- Provide session lookup by `session_id` and `streamSid`

**TTL sweeper:**
```python
async def ttl_sweeper(self):
    """Periodic task that checks for expired sessions."""
    while True:
        await asyncio.sleep(60)  # Check every minute
        now = datetime.utcnow()
        expired = [
            sid for sid, session in self.sessions.items()
            if (now - session.last_activity).total_seconds() > self.ttl_seconds
        ]
        for sid in expired:
            await self._cleanup_session(sid)
```

**Session lifecycle:**
1. `POST /api/v1/calls/outbound` → creates `CallSession`, initiates Twilio call
2. Twilio connects to WebSocket → session marked `CONNECTED`
3. Conversation runs → `last_activity` updated on each media message
4. Twilio sends `stop` → session marked `COMPLETED`, resources released
5. TTL expires → session marked `TIMED_OUT`, resources released

---

### 3.9 Recording & Persistence

#### `recording/recorder.py` — `ConversationRecorder`

**Responsibilities:**
- Persist transcript segments to SQLite during conversation
- Persist conversation metadata on completion
- Use SQLAlchemy with `aiosqlite` for async operations
- Batch writes where possible to minimize I/O

**Write strategy:**
- Transcript segments: written immediately after each turn (user + agent pair)
- Conversation metadata: updated on state changes, finalized on completion
- Events: written asynchronously via event bus

#### `recording/events.py` — `EventBus`

**Responsibilities:**
- Async pub/sub event dispatch
- Structured JSON logging of all events
- SQLite persistence for event audit trail
- Support for future external consumers (webhook dispatchers)

**Event structure:**
```python
@dataclass
class Event:
    type: EventType
    session_id: str
    timestamp: datetime
    payload: dict[str, Any]
    version: int = 1
```

**Subscriber pattern:**
```python
class EventBus:
    def __init__(self):
        self._subscribers: dict[EventType, list[Callable]] = defaultdict(list)
    
    def subscribe(self, event_type: EventType, handler: Callable):
        self._subscribers[event_type].append(handler)
    
    async def emit(self, event: Event):
        # Log
        logger.info("event", extra={"event": event.model_dump()})
        # Persist
        await self._persist(event)
        # Dispatch
        for handler in self._subscribers.get(event.type, []):
            try:
                await handler(event)
            except Exception:
                logger.exception("event_handler_failed", extra={"event_type": event.type})
```

---

### 3.10 Configuration

#### `config.py` — `Settings`

```python
from pydantic_settings import BaseSettings
from pydantic import SecretStr

class Settings(BaseSettings):
    # OpenAI
    openai_api_key: SecretStr
    openai_stt_model: str = "whisper-1"
    openai_llm_model: str = "gpt-4o"
    
    # ElevenLabs
    elevenlabs_api_key: SecretStr
    elevenlabs_model: str = "eleven_flash_v2_5"
    
    # Twilio
    twilio_account_sid: str
    twilio_auth_token: SecretStr
    twilio_phone_number: str
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./callcenter.db"
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    
    # Session
    session_ttl_seconds: int = 300
    
    # VAD
    vad_silence_threshold_ms: int = 500
    vad_speech_threshold: float = 0.5
    
    # STT
    max_utterance_duration_s: int = 30
    
    # LLM
    max_history_messages: int = 10
    max_response_tokens: int = 300
    
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

---

## 4. Data Flow

### 4.1 Happy Path: Complete Conversation Turn

```
1. Twilio sends mu-law audio chunk → TwilioAdapter receives via WebSocket
2. TwilioAdapter decodes base64, emits raw mu-law bytes
3. AudioCodec converts mu-law → PCM 16-bit 8kHz
4. VAD processes PCM frame:
   a. If speech detected → emit vad.speech_started, start accumulating
   b. If silence after speech → continue accumulating
   c. If silence threshold reached → emit vad.speech_ended with full buffer
5. STT receives PCM buffer:
   a. Converts PCM → WAV in-memory
   b. Sends to Whisper API
   c. Returns transcribed text
   d. Emits stt.completed
6. LLM receives transcribed text:
   a. Appends to conversation history
   b. Sends to GPT-4o with system prompt + history
   c. Returns generated response
   d. Emits llm.completed
7. TTS receives response text:
   a. Opens WebSocket to ElevenLabs
   b. Sends text + flush
   c. Receives streaming audio chunks
   d. For each chunk: decode → resample → mu-law → send to Twilio
   e. Emits tts.audio_chunk per chunk, tts.completed at end
8. Recorder persists transcript segment
```

### 4.2 Interruption Flow

```
1. Agent is SPEAKING: TTS streaming audio to Twilio
2. VAD detects speech in incoming audio (user talking over agent)
3. VAD emits vad.speech_started
4. Orchestrator checks: self._speaking == True → interruption!
5. Orchestrator sets self._interrupted = True
6. TTS delivery loop checks flag → breaks out of loop
7. Orchestrator sends "clear" to Twilio (flushes Twilio's audio buffer)
8. Orchestrator closes ElevenLabs WebSocket
9. Orchestrator emits interruption.detected with delivered portion
10. VAD continues accumulating the user's interrupting utterance
11. When user finishes: normal STT → LLM → TTS cycle resumes
12. Only the delivered portion of the interrupted response is added to history
```

### 4.3 Error Recovery Flow

```
STT Error:
1. Whisper API returns 5xx/timeout
2. STT client retries with exponential backoff (max 3)
3. If all retries fail → raises STTError
4. Orchestrator catches STTError
5. Orchestrator speaks fallback: "Disculpa, no pude entender..."
6. State returns to LISTENING (conversation continues)

LLM Error:
1. GPT-4o API returns 5xx/timeout
2. LLM client retries with exponential backoff (max 3)
3. If all retries fail → raises LLMError
4. Orchestrator catches LLMError
5. Orchestrator speaks fallback: "Lo siento, estoy teniendo problemas técnicos..."
6. State transitions to FAILED (conversation ends gracefully)

TTS Error:
1. ElevenLabs WebSocket fails to connect or errors mid-stream
2. TTS client raises TTSError
3. Orchestrator catches TTSError
4. Orchestrator plays pre-recorded apology audio (fallback WAV file)
5. Text response is recorded in transcript as text-only
6. State returns to LISTENING (conversation continues)
```

---

## 5. Audio Pipeline Details

### 5.1 Buffer Sizes and Thresholds

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Twilio chunk size | ~160 bytes (20ms mu-law) | Twilio default |
| VAD frame size | 256 samples (32ms at 8kHz) | Silero VAD optimal frame |
| VAD speech threshold | 0.5 | Balanced false positive/negative |
| Speech-end silence | 500ms | Natural conversation pause |
| Interruption debounce | 300ms | Prevents false triggers from noise |
| Max utterance duration | 30s | Prevents runaway audio buffers |
| TTS chunk delivery | immediate (no batching) | Minimizes perceived latency |
| Audio delivery queue | 5 chunks max | Prevents audio backlog during interruption |

### 5.2 Format Conversion Chain

```
Incoming (Twilio → Internal):
  base64(mu-law 8kHz) → base64 decode → mu-law bytes → audioop.ulaw2lin() → PCM 16-bit 8kHz

Outgoing (Internal → Twilio):
  PCM 16-bit 8kHz → audioop.lin2ulaw() → mu-law bytes → base64 encode → JSON payload

ElevenLabs → Twilio:
  MP3/PCM (variable rate) → pydub.AudioSegment → resample(8000) → PCM 16-bit 8kHz
  → audioop.lin2ulaw() → mu-law bytes → base64 encode → JSON payload
```

### 5.3 Streaming Strategy

The TTS-to-Twilio streaming pipeline uses `asyncio.Queue` for decoupled production and consumption:

```
ElevenLabs WS ──► [audio chunks] ──► asyncio.Queue ──► [transcode] ──► Twilio WS
     (producer)                                                (consumer)
```

- **Producer task**: receives chunks from ElevenLabs WebSocket, pushes to queue
- **Consumer task**: pops from queue, transcodes, sends to Twilio
- **Interruption**: both tasks check `cancelled` flag; queue is cleared on interrupt
- **Backpressure**: queue maxsize=5 prevents memory buildup if Twilio is slow

---

## 6. State Machine

### 6.1 States and Transitions

```python
from enum import Enum

class CallState(str, Enum):
    INITIATED = "initiated"       # Call placed via Twilio REST API
    CONNECTED = "connected"       # Twilio WebSocket established
    LISTENING = "listening"       # Waiting for user speech
    PROCESSING = "processing"     # STT + LLM running
    SPEAKING = "speaking"         # TTS streaming audio to Twilio
    COMPLETED = "completed"       # Call ended normally
    FAILED = "failed"             # Call ended due to error
    TIMED_OUT = "timed_out"       # Session TTL expired
```

### 6.2 Transition Matrix

| Current State | Event | Next State | Action |
|---------------|-------|------------|--------|
| INITIATED | Twilio `start` | CONNECTED | Initialize session, send greeting |
| CONNECTED | Greeting sent | LISTENING | Start VAD processing |
| LISTENING | VAD speech end | PROCESSING | Begin STT pipeline |
| PROCESSING | STT success + LLM success | SPEAKING | Begin TTS streaming |
| PROCESSING | STT error | LISTENING | Speak fallback, continue |
| PROCESSING | LLM error | FAILED | Speak fallback, end call |
| SPEAKING | TTS complete | LISTENING | Resume VAD processing |
| SPEAKING | VAD speech start | PROCESSING | Interrupt, process user utterance |
| SPEAKING | TTS error | LISTENING | Play fallback audio, continue |
| ANY | Twilio `stop` | COMPLETED | Persist transcript, cleanup |
| ANY | Unrecoverable error | FAILED | Log error, cleanup |
| ANY | TTL expiry | TIMED_OUT | Persist partial transcript, cleanup |

---

## 7. Error Handling Strategy

### 7.1 Per-Component Fallbacks

| Component | Error | Fallback | Recovery |
|-----------|-------|----------|----------|
| **STT (Whisper)** | API error, timeout | "Disculpa, no pude entender..." | Continue conversation |
| **LLM (GPT-4o)** | API error, timeout | "Lo siento, estoy teniendo problemas técnicos..." | End call gracefully |
| **TTS (ElevenLabs)** | Connection failure, API error | Pre-recorded apology WAV | Continue conversation (text-only in transcript) |
| **Twilio WS** | Connection drop | Log error, emit conversation.failed | Session cleanup |
| **VAD** | Model load failure | Disable VAD, use fixed-duration chunks | Log critical error |

### 7.2 Retry Policy

```python
async def with_retry(func, max_retries=3, base_delay=1.0, max_delay=10.0):
    """Execute async function with exponential backoff and jitter."""
    import random
    for attempt in range(max_retries):
        try:
            return await func()
        except (APIConnectionError, APITimeoutError) as e:
            if attempt == max_retries - 1:
                raise
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            await asyncio.sleep(delay)
```

### 7.3 Graceful Degradation Hierarchy

```
Full functionality (all APIs healthy)
    ↓
STT degraded (Whisper unavailable → fallback message, conversation continues)
    ↓
TTS degraded (ElevenLabs unavailable → pre-recorded audio, text transcript preserved)
    ↓
LLM degraded (GPT-4o unavailable → apology, call ends gracefully)
    ↓
Complete failure (Twilio disconnected → session cleanup, partial transcript saved)
```

### 7.4 Structured Logging

All errors logged with context:
```python
logger.error(
    "stt_api_error",
    extra={
        "session_id": session_id,
        "error_type": type(e).__name__,
        "error_message": str(e),
        "attempt": attempt,
        "max_retries": 3,
    },
    exc_info=True,
)
```

---

## 8. Configuration

### 8.1 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `OPENAI_API_KEY` | OpenAI API key (Whisper + GPT-4o) | Yes | — |
| `ELEVENLABS_API_KEY` | ElevenLabs API key | Yes | — |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | Yes | — |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | Yes | — |
| `TWILIO_PHONE_NUMBER` | Default Twilio phone number | Yes | — |
| `DATABASE_URL` | SQLite database URL | No | `sqlite+aiosqlite:///./callcenter.db` |
| `SESSION_TTL_SECONDS` | Session inactivity timeout | No | `300` |
| `HOST` | Server bind address | No | `0.0.0.0` |
| `PORT` | Server port | No | `8000` |
| `LOG_LEVEL` | Logging level | No | `INFO` |
| `VAD_SILENCE_THRESHOLD_MS` | VAD speech-end silence | No | `500` |
| `MAX_UTTERANCE_DURATION_S` | Max audio for STT | No | `30` |
| `MAX_HISTORY_MESSAGES` | Max conversation history pairs | No | `10` |

### 8.2 Agent Configuration JSON

```json
{
    "agent_id": "sales-agent-01",
    "name": "Ana",
    "system_prompt": "Eres Ana, una asistente virtual de ventas de TechCorp...",
    "voice_id": "EXAVITQu4vr4xnSDxMaL",
    "language": "es",
    "max_history_messages": 10,
    "max_response_tokens": 300,
    "speech_end_silence_ms": 500,
    "max_utterance_duration_s": 30,
    "fallback_language": "es"
}
```

### 8.3 Agent Config Storage (MVP)

For the MVP, agent configurations are loaded from a JSON file at startup:
```
backend/agents/configs/
├── sales-agent-01.json
├── support-agent-01.json
└── ...
```

Phase 2 will migrate to database-backed agent configuration.

---

## 9. Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app, lifespan, router mounting
│   ├── config.py                  # Pydantic Settings
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py        # AgentOrchestrator: main conversation loop
│   │   ├── session_manager.py     # SessionManager: registry + TTL cleanup
│   │   ├── models.py              # Pydantic models (AgentConfig, CallRequest, etc.)
│   │   └── prompts/
│   │       ├── __init__.py
│   │       └── templates.py       # System prompt templates
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── base.py                # ChannelAdapter abstract base class
│   │   └── twilio.py              # TwilioAdapter: WS handler, audio I/O
│   ├── voice/
│   │   ├── __init__.py
│   │   ├── audio_codec.py         # Mu-law ↔ PCM transcoding
│   │   ├── vad.py                 # SileroVAD: speech detection
│   │   ├── stt.py                 # WhisperClient: speech-to-text
│   │   └── tts.py                 # ElevenLabsStreamingClient: text-to-speech
│   ├── ai/
│   │   ├── __init__.py
│   │   └── llm.py                 # GPT4oClient: conversation brain
│   ├── recording/
│   │   ├── __init__.py
│   │   ├── recorder.py            # ConversationRecorder: SQLite persistence
│   │   └── events.py              # EventBus: async pub/sub
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy ORM models
│   │   └── engine.py              # Async engine + session factory
│   └── api/
│       ├── __init__.py
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── calls.py           # POST /calls/outbound
│       │   ├── conversations.py   # GET /conversations/{id}
│       │   ├── media_stream.py    # WS /media-stream/{session_id}
│       │   └── health.py          # GET /health
│       └── dependencies.py        # FastAPI dependencies
├── agents/
│   └── configs/                   # Agent JSON configs
│       └── sales-agent-01.json
├── fallback_audio/
│   └── apology_es.wav             # Pre-recorded TTS fallback
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # Pytest fixtures
│   ├── test_orchestrator.py
│   ├── test_vad.py
│   ├── test_stt.py
│   ├── test_llm.py
│   ├── test_tts.py
│   ├── test_twilio_adapter.py
│   ├── test_audio_codec.py
│   ├── test_event_bus.py
│   └── test_recorder.py
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 10. Database Schema (SQLite)

### 10.1 Tables

```sql
-- Clients
CREATE TABLE clients (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    phone_number        TEXT NOT NULL,
    twilio_account_sid  TEXT NOT NULL,
    twilio_auth_token   TEXT NOT NULL,
    twilio_phone_number TEXT NOT NULL,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    is_active           INTEGER NOT NULL DEFAULT 1
);

-- Agents
CREATE TABLE agents (
    id                       TEXT PRIMARY KEY,
    client_id                TEXT NOT NULL REFERENCES clients(id),
    name                     TEXT NOT NULL,
    system_prompt            TEXT NOT NULL,
    voice_id                 TEXT NOT NULL,
    language                 TEXT NOT NULL DEFAULT 'es',
    max_history_messages     INTEGER NOT NULL DEFAULT 10,
    max_response_tokens      INTEGER NOT NULL DEFAULT 300,
    speech_end_silence_ms    INTEGER NOT NULL DEFAULT 500,
    max_utterance_duration_s INTEGER NOT NULL DEFAULT 30,
    fallback_language        TEXT NOT NULL DEFAULT 'es',
    created_at               TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at               TEXT NOT NULL DEFAULT (datetime('now')),
    is_active                INTEGER NOT NULL DEFAULT 1
);

-- Conversations
CREATE TABLE conversations (
    id               TEXT PRIMARY KEY,
    client_id        TEXT NOT NULL REFERENCES clients(id),
    agent_id         TEXT NOT NULL,
    phone_number     TEXT NOT NULL,
    direction        TEXT NOT NULL DEFAULT 'outbound',
    status           TEXT NOT NULL DEFAULT 'active',
    started_at       TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at         TEXT,
    duration_seconds REAL,
    error_message    TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_conv_client ON conversations(client_id);
CREATE INDEX idx_conv_status ON conversations(status);
CREATE INDEX idx_conv_started ON conversations(started_at);

-- Transcript Segments
CREATE TABLE transcript_segments (
    id                  TEXT PRIMARY KEY,
    conversation_id     TEXT NOT NULL REFERENCES conversations(id),
    role                TEXT NOT NULL CHECK(role IN ('user', 'agent')),
    text                TEXT NOT NULL,
    timestamp           TEXT NOT NULL DEFAULT (datetime('now')),
    audio_duration_ms   INTEGER,
    was_interrupted     INTEGER NOT NULL DEFAULT 0,
    delivered_portion   TEXT,
    metadata            TEXT  -- JSON blob
);
CREATE INDEX idx_ts_conv ON transcript_segments(conversation_id);
CREATE INDEX idx_ts_ts ON transcript_segments(timestamp);

-- Events
CREATE TABLE conversation_events (
    id          TEXT PRIMARY KEY,
    event_type  TEXT NOT NULL,
    session_id  TEXT NOT NULL REFERENCES conversations(id),
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    payload     TEXT NOT NULL,  -- JSON blob
    version     INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_evt_session ON conversation_events(session_id);
CREATE INDEX idx_evt_type ON conversation_events(event_type);
```

### 10.2 SQLAlchemy Models

```python
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, DateTime, func
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Client(Base):
    __tablename__ = "clients"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    twilio_account_sid = Column(String, nullable=False)
    twilio_auth_token = Column(String, nullable=False)
    twilio_phone_number = Column(String, nullable=False)
    created_at = Column(String, server_default=func.datetime('now'))
    updated_at = Column(String, server_default=func.datetime('now'), onupdate=func.datetime('now'))
    is_active = Column(Integer, nullable=False, default=1)

class Agent(Base):
    __tablename__ = "agents"
    id = Column(String, primary_key=True)
    client_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    system_prompt = Column(Text, nullable=False)
    voice_id = Column(String, nullable=False)
    language = Column(String, nullable=False, default="es")
    max_history_messages = Column(Integer, nullable=False, default=10)
    max_response_tokens = Column(Integer, nullable=False, default=300)
    speech_end_silence_ms = Column(Integer, nullable=False, default=500)
    max_utterance_duration_s = Column(Integer, nullable=False, default=30)
    fallback_language = Column(String, nullable=False, default="es")
    created_at = Column(String, server_default=func.datetime('now'))
    updated_at = Column(String, server_default=func.datetime('now'), onupdate=func.datetime('now'))
    is_active = Column(Integer, nullable=False, default=1)

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String, primary_key=True)
    client_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    direction = Column(String, nullable=False, default="outbound")
    status = Column(String, nullable=False, default="active")
    started_at = Column(String, server_default=func.datetime('now'))
    ended_at = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(String, server_default=func.datetime('now'))

class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"
    id = Column(String, primary_key=True)
    conversation_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'user' or 'agent'
    text = Column(Text, nullable=False)
    timestamp = Column(String, server_default=func.datetime('now'))
    audio_duration_ms = Column(Integer, nullable=True)
    was_interrupted = Column(Integer, nullable=False, default=0)
    delivered_portion = Column(String, nullable=True)
    metadata = Column(String, nullable=True)  # JSON

class ConversationEvent(Base):
    __tablename__ = "conversation_events"
    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    timestamp = Column(String, server_default=func.datetime('now'))
    payload = Column(String, nullable=False)  # JSON
    version = Column(Integer, nullable=False, default=1)
```

---

## 11. API Endpoints

### 11.1 Initiate Outbound Call

```
POST /api/v1/calls/outbound
Content-Type: application/json

{
    "phone_number": "+5491112345678",
    "agent_id": "sales-agent-01",
    "client_id": "uuid-here"
}

Response 201 Created:
{
    "session_id": "uuid-here",
    "status": "initiated",
    "twilio_call_sid": "CA..."
}
```

**Implementation flow:**
1. Validate phone number (E.164 regex: `^\+[1-9]\d{1,14}$`)
2. Load agent config by `agent_id`
3. Create `CallSession`, persist to DB
4. Generate TwiML with `<Stream url="wss://your-domain/api/v1/media-stream/{session_id}"/>`
5. Call Twilio REST API to initiate outbound call
6. Return session ID and Twilio Call SID

### 11.2 Media Stream WebSocket

```
WebSocket /api/v1/media-stream/{session_id}
```

**Implementation flow:**
1. Accept WebSocket connection
2. Wait for `start` event → extract `streamSid`, validate `session_id`
3. Look up `CallSession` from `SessionManager`
4. Create `TwilioAdapter` with the WebSocket
5. Start `AgentOrchestrator` in a background task
6. Route incoming media to orchestrator's audio pipeline
7. On `stop` event: signal orchestrator to complete

### 11.3 Get Conversation

```
GET /api/v1/conversations/{conversation_id}

Response 200:
{
    "id": "uuid",
    "client_id": "uuid",
    "agent_id": "sales-agent-01",
    "phone_number": "+5491112345678",
    "direction": "outbound",
    "status": "completed",
    "started_at": "2026-03-30T10:00:00Z",
    "ended_at": "2026-03-30T10:05:30Z",
    "duration_seconds": 330.0,
    "transcript": [...]
}
```

### 11.4 Health Check

```
GET /api/v1/health

Response 200:
{
    "status": "healthy",
    "active_sessions": 1,
    "uptime_seconds": 3600
}
```

---

## 12. Dependencies

### 12.1 Python Packages

```toml
[project]
dependencies = [
    # Web framework
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.29.0",
    "websockets>=12.0",
    
    # HTTP clients
    "httpx>=0.27.0",
    "openai>=1.30.0",
    "elevenlabs>=1.3.0",
    "twilio>=9.0.0",
    
    # Audio processing
    "pydub>=0.25.1",
    # ffmpeg (system dependency, not pip)
    
    # VAD
    "onnxruntime>=1.17.0",
    
    # Database
    "sqlalchemy[asyncio]>=2.0.0",
    "aiosqlite>=0.20.0",
    
    # Configuration
    "pydantic>=2.7.0",
    "pydantic-settings>=2.2.0",
    
    # Utilities
    "python-multipart>=0.0.9",
    "structlog>=24.1.0",
]
```

### 12.2 System Dependencies

| Dependency | Purpose | Installation |
|------------|---------|-------------|
| `ffmpeg` | Audio transcoding (MP3 → PCM) | `brew install ffmpeg` / `apt install ffmpeg` |
| `silero_vad.onnx` | VAD model | Downloaded at runtime or bundled |

### 12.3 Silero VAD Model

The Silero VAD ONNX model is downloaded at first startup:
```python
import urllib.request

VAD_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/master/files/silero_vad.onnx"
VAD_MODEL_PATH = "models/silero_vad.onnx"

def ensure_vad_model():
    if not os.path.exists(VAD_MODEL_PATH):
        os.makedirs("models", exist_ok=True)
        urllib.request.urlretrieve(VAD_MODEL_URL, VAD_MODEL_PATH)
```

---

## 13. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Whisper API latency** (1-3s batch) | High | High | Accept for MVP; document as primary latency bottleneck; plan for streaming STT (Deepgram/local Whisper.cpp) in Phase 2 |
| **ElevenLabs free-tier limits** (10k chars/month, 2500 chars/gen) | Medium | Medium | Implement character counting per session; alert at 80% threshold; truncate LLM responses at 2,500 chars |
| **Interruption race conditions** | High | Medium | Use `asyncio.Lock` per session for state transitions; atomic `_interrupted` flag; clear Twilio buffer before processing new utterance |
| **Audio quality degradation** (mu-law ↔ PCM cycles) | Medium | Low | Use `audioop` (C implementation) for hot path; validate with audio testing; pydub for non-hot-path conversions |
| **Zombie sessions consuming resources** | Medium | Medium | TTL sweeper runs every 60s; WebSocket ping/pong keepalive; explicit cleanup on all exit paths |
| **Single point of failure** (no HA for MVP) | High | Low | Acceptable for MVP; document scaling path (Redis sessions, multiple workers) for Phase 2 |
| **GPT-4o response too long** (exceeds TTS char limit) | Medium | Medium | `max_tokens: 300` limits response length; hard truncate at 2,500 chars; split at sentence boundaries if needed |
| **ElevenLabs WebSocket instability** | Medium | Medium | Reconnect logic with backoff; fallback to pre-recorded audio on persistent failure |
| **pydub + ffmpeg overhead** | Low | Medium | Benchmark transcoding latency; if > 50ms per chunk, consider `audioop`-only path or native library |

---

## 14. Testing Strategy

### 14.1 Unit Tests
- `test_audio_codec.py`: mu-law ↔ PCM roundtrip fidelity
- `test_vad.py`: Silero VAD with synthetic audio (speech + silence patterns)
- `test_stt.py`: Whisper API client with mocked responses
- `test_llm.py`: GPT-4o client with mocked responses, history truncation
- `test_tts.py`: ElevenLabs WebSocket client with mocked stream
- `test_event_bus.py`: Event emission, subscriber dispatch, error isolation

### 14.2 Integration Tests
- `test_twilio_adapter.py`: WebSocket message parsing, audio encoding/decoding
- `test_orchestrator.py`: Full conversation loop with mocked dependencies
- `test_recorder.py`: SQLite persistence, query correctness

### 14.3 End-to-End Tests
- Manual testing with real Twilio phone calls
- Latency measurement: instrument each pipeline stage with timing metrics
- Interruption testing: speak over agent at various points in the response

### 14.4 Performance Targets
| Metric | Target | Measurement |
|--------|--------|-------------|
| VAD inference | < 20ms/frame | `time.perf_counter()` around model call |
| STT response | < 2s (10s utterance) | Timer around API call |
| LLM response | < 1.5s | Timer around API call |
| TTS TTFB | < 200ms | Timer from text sent to first audio chunk |
| Total cycle | < 1.5s (excluding STT) | End-to-end: speech end → first audio out |

---

## 15. Observability

### 15.1 Structured Logging

All logs use `structlog` with JSON output:
```json
{
    "event": "tts.audio_chunk",
    "session_id": "abc-123",
    "chunk_index": 5,
    "latency_ms": 142,
    "timestamp": "2026-03-30T10:05:30.123Z"
}
```

### 15.2 Metrics (Future)

Phase 2 should add:
- Prometheus metrics for pipeline stage latencies
- Active session count gauge
- Error rate counters per API
- ElevenLabs character usage counter

### 15.3 Tracing

Each conversation turn gets a correlation ID:
```python
correlation_id = str(uuid4())
# Propagate through all pipeline stages
# Include in all log entries and events
```

---

## 16. Migration Path (Phase 2+)

| Component | MVP (Phase 1) | Phase 2 | Phase 3 |
|-----------|---------------|---------|---------|
| **Database** | SQLite | PostgreSQL | PostgreSQL + read replicas |
| **STT** | Whisper API (batch) | Streaming STT (Deepgram/Whisper.cpp) | Same |
| **Concurrency** | 1 call | Multiple calls per instance | Horizontal scaling (Redis sessions) |
| **Channels** | Twilio outbound only | Twilio inbound | WhatsApp, WebRTC |
| **Events** | In-process pub/sub | Redis Streams / RabbitMQ | Event sourcing |
| **Config** | JSON files | Database-backed | Admin dashboard |
| **Observability** | Structured logging | Prometheus + Grafana | Full APM (Datadog) |

---

## 17. Open Questions

1. **ElevenLabs WebSocket library**: The `elevenlabs` Python SDK may not support the raw WebSocket streaming API directly. May need to use `websockets` library for direct WS connection to `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`. **Decision needed after SDK investigation.**

2. **Silero VAD model loading**: ONNX model is ~600KB. Should it be bundled in the repo or downloaded at startup? **Recommendation: bundle in `models/` directory to avoid startup failures in air-gapped environments.**

3. **TwiML generation**: Should TwiML be generated dynamically per call or served from a static endpoint? **Recommendation: dynamic generation via a dedicated `/twiml/{session_id}` endpoint that returns the `<Stream>` directive with the correct WebSocket URL.**

4. **Audio chunk sizing for Twilio**: Twilio expects ~20ms chunks (160 bytes mu-law). Should we match this exactly or can we send larger chunks? **Recommendation: match Twilio's expected size for smooth playback. ElevenLabs chunk sizes may vary — buffer and split as needed.**
