# Specification: Phase 1 — MVP Outbound Call Agent with ElevenLabs Pipeline

**Status:** Draft  
**Version:** 1.0.0  
**Date:** 2026-03-30  
**Author:** SDD Spec Agent  
**Change ID:** `phase-1-mvp-outbound-agent`

---

## 1. Executive Summary

This specification defines the requirements for the **Minimum Viable Product (MVP)** of the V1-CallCenter platform: an AI-powered outbound call agent that can initiate phone calls, carry a natural conversation in real-time, handle interruptions, and record the full interaction.

The system integrates **Twilio** (telephony + media streams), **OpenAI Whisper** (speech-to-text), **OpenAI GPT-4o** (conversation brain), and **ElevenLabs** (streaming text-to-speech with `eleven_flash_v2_5` model) into a single async Python service built on **FastAPI**.

The MVP supports **1 concurrent call** and is designed as the foundation for the channel abstraction pattern that will later support inbound calls, WhatsApp, and other channels.

---

## 2. Conventions

### 2.1 RFC 2119 Keywords

The following keywords are used throughout this specification and carry the meanings defined in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119):

- **MUST** / **MUST NOT** — Absolute requirement or prohibition
- **SHALL** / **SHALL NOT** — Absolute requirement or prohibition (synonym of MUST)
- **SHOULD** / **SHOULD NOT** — Recommended; valid reasons may exist to ignore
- **MAY** — Optional; permitted but not required

### 2.2 Scenario Format

All behavioral scenarios use the **Given / When / Then** format:

```
Given [preconditions and system state]
When [action or event occurs]
Then [expected observable outcome]
```

---

## 3. Functional Requirements

### 3.1 Outbound Call Initiation

| ID | Requirement |
|----|-------------|
| **FR-001** | The system SHALL initiate outbound phone calls via the Twilio REST API (`/v2010/Accounts/{AccountSid}/Calls.json`). |
| **FR-002** | The TwiML response for the outbound call SHALL direct Twilio to open a `<Stream>` WebSocket connection to the FastAPI media stream endpoint. |
| **FR-003** | The system SHALL accept the phone number to call and the agent configuration as input parameters for call initiation. |
| **FR-004** | The system SHALL validate that the destination phone number is in E.164 format before initiating the call. |
| **FR-005** | The system SHALL return a call session identifier (UUID) upon successful call initiation. |

### 3.2 Real-Time Audio Streaming from Twilio

| ID | Requirement |
|----|-------------|
| **FR-010** | The system SHALL accept WebSocket connections from Twilio Media Streams at a dedicated endpoint (e.g., `/api/v1/media-stream/{session_id}`). |
| **FR-011** | The system SHALL parse incoming Twilio media messages as JSON containing base64-encoded audio chunks. |
| **FR-012** | Incoming audio from Twilio SHALL be in **mu-law (PCMU) codec at 8,000 Hz sample rate**, 20ms chunks, mono. |
| **FR-013** | The system SHALL decode mu-law 8kHz audio to raw PCM 16-bit for internal processing (VAD, STT). |
| **FR-014** | The system SHALL buffer incoming audio chunks and emit a `media.received` event for each chunk. |
| **FR-015** | The system SHALL handle Twilio `start`, `media`, `stop`, and `close` WebSocket message types. |

### 3.3 Voice Activity Detection (VAD)

| ID | Requirement |
|----|-------------|
| **FR-020** | The system SHALL implement Voice Activity Detection to determine when the user starts and stops speaking. |
| **FR-021** | The VAD implementation SHALL use **Silero VAD** (ONNX runtime) for real-time voice detection on PCM audio frames. |
| **FR-022** | The system SHALL accumulate audio frames into a "user utterance" from VAD speech-start to VAD speech-end. |
| **FR-023** | The system SHALL apply a configurable **speech-end silence threshold** (default: 500ms) to determine when the user has finished speaking. |
| **FR-024** | The system SHALL emit a `vad.speech_started` event when speech is detected. |
| **FR-025** | The system SHALL emit a `vad.speech_ended` event when speech ends, including the accumulated audio buffer. |
| **FR-026** | The system SHALL discard silence-only audio frames and NOT send them to the STT service. |

### 3.4 Speech-to-Text (STT)

| ID | Requirement |
|----|-------------|
| **FR-030** | The system SHALL transcribe user speech using the **OpenAI Whisper API** (`/v1/audio/transcriptions`). |
| **FR-031** | The system SHALL send the complete accumulated user utterance (PCM audio) to Whisper after VAD speech-end. |
| **FR-032** | The system SHALL use the `whisper-1` model for transcription. |
| **FR-033** | The system SHALL set the response format to `text` (plain text, not verbose JSON). |
| **FR-034** | The system SHALL emit a `stt.completed` event containing the transcribed text and the original audio duration. |
| **FR-035** | The system SHALL handle Whisper API errors (timeout, rate limit, service unavailable) and emit a `stt.error` event with the error details. |
| **FR-036** | The system SHALL apply a maximum utterance duration limit of **30 seconds**; audio exceeding this limit SHALL be truncated before sending to Whisper. |

### 3.5 Conversational Response (GPT-4o)

| ID | Requirement |
|----|-------------|
| **FR-040** | The system SHALL generate conversational responses using the **OpenAI Chat Completions API** with the `gpt-4o` model. |
| **FR-041** | The system SHALL maintain a conversation history (list of `role`/`content` message pairs) for context continuity. |
| **FR-042** | The system SHALL prepend a configurable **system prompt** to every GPT-4o request, defining the agent's personality, role, and behavioral rules. |
| **FR-043** | The system SHALL include the user's transcribed utterance as the latest `user` message in the conversation history. |
| **FR-044** | The system SHALL limit the conversation history to the **most recent 10 message pairs** to control token usage and latency. |
| **FR-045** | The system SHALL set `max_tokens` to **300** for agent responses to keep replies concise. |
| **FR-046** | The system SHALL emit a `llm.completed` event containing the generated response text. |
| **FR-047** | The system SHALL handle GPT-4o API errors and emit an `llm.error` event with the error details. |
| **FR-048** | The system SHALL apply a **10-second timeout** for GPT-4o API calls; on timeout, the system SHALL respond with a fallback message (see FR-060). |

### 3.6 Text-to-Speech (TTS) via ElevenLabs Streaming

| ID | Requirement |
|----|-------------|
| **FR-050** | The system SHALL generate speech audio using the **ElevenLabs WebSocket Streaming API** with the `eleven_flash_v2_5` model. |
| **FR-051** | The system SHALL establish a WebSocket connection to `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input` for each TTS request. |
| **FR-052** | The system SHALL send a text input message to ElevenLabs within **50ms** of receiving the LLM response. |
| **FR-053** | The system SHALL send a `flush` message after the complete text has been transmitted to trigger audio generation. |
| **FR-054** | The system SHALL receive streaming audio chunks from ElevenLabs as they become available (MP3 or PCM format). |
| **FR-055** | The system SHALL emit a `tts.audio_chunk` event for each audio chunk received from ElevenLabs. |
| **FR-056** | The system SHALL emit a `tts.completed` event when ElevenLabs signals the end of the audio stream. |
| **FR-057** | The system SHALL handle ElevenLabs API errors and emit a `tts.error` event with the error details. |
| **FR-058** | The system SHALL respect the ElevenLabs free-tier limit of **2,500 characters per generation**; text exceeding this limit SHALL be split into multiple generations. |

### 3.7 Audio Transcoding and Delivery to Twilio

| ID | Requirement |
|----|-------------|
| **FR-060** | The system SHALL transcode audio from ElevenLabs output format (MP3 or PCM) to **mu-law (PCMU) 8kHz, 16-bit mono** for Twilio compatibility. |
| **FR-061** | The system SHALL use the `pydub` library with `ffmpeg` backend for audio transcoding. |
| **FR-062** | The system SHALL send transcoded audio chunks to Twilio via the WebSocket connection as base64-encoded `media` messages. |
| **FR-063** | The system SHALL send audio chunks to Twilio as soon as they are transcoded (streaming delivery, not batched). |
| **FR-064** | The system SHALL include a `streamSid` in each media message sent to Twilio. |
| **FR-065** | The system SHALL maintain an ordered queue of audio chunks to ensure sequential delivery. |

### 3.8 Interruption Handling (Barge-In)

| ID | Requirement |
|----|-------------|
| **FR-070** | The system SHALL detect user speech (via VAD) while the agent is currently speaking. |
| **FR-071** | Upon detecting user speech during agent speech, the system SHALL **immediately stop** sending audio to Twilio. |
| **FR-072** | The system SHALL terminate the active ElevenLabs WebSocket connection when an interruption is detected. |
| **FR-073** | The system SHALL discard any remaining audio chunks in the delivery queue for the interrupted utterance. |
| **FR-074** | The system SHALL emit an `interruption.detected` event containing the timestamp and the portion of the agent's response that was delivered. |
| **FR-075** | The system SHALL process the user's interrupting utterance as a new conversational turn (VAD → STT → LLM → TTS). |
| **FR-076** | The system SHALL NOT send the interrupted agent response to the conversation history; only the delivered portion SHALL be recorded. |

### 3.9 Conversation Recording

| ID | Requirement |
|----|-------------|
| **FR-080** | The system SHALL record a complete transcript of every conversation, including timestamps, speaker role (`agent` or `user`), and text content. |
| **FR-081** | The system SHALL record metadata for each conversation: session ID, phone number, agent ID, start time, end time, duration, and status. |
| **FR-082** | The system SHALL store transcripts and metadata in **SQLite** for the MVP. |
| **FR-083** | The system SHALL assign a unique UUID to each transcript segment. |
| **FR-084** | The system SHALL persist the transcript to the database upon conversation completion. |

### 3.10 Event Emission

| ID | Requirement |
|----|-------------|
| **FR-090** | The system SHALL emit a `conversation.completed` event when a call ends normally (Twilio sends `stop`). |
| **FR-091** | The `conversation.completed` event SHALL include: session ID, full transcript, duration, status, and any error information. |
| **FR-092** | The system SHALL emit a `conversation.failed` event when a call ends due to an unrecoverable error. |
| **FR-093** | Events SHALL be dispatched via an internal event bus (async pub/sub pattern) to allow future external consumers (webhooks, analytics). |
| **FR-094** | The system SHALL log all events with structured logging (JSON format) for observability. |

---

## 4. Non-Functional Requirements

### 4.1 Latency Targets

| ID | Requirement |
|----|-------------|
| **NFR-001** | The TTS Time-To-First-Byte (TTFB) from ElevenLabs SHALL be **< 200ms** when using `eleven_flash_v2_5`. |
| **NFR-002** | The total conversation cycle time (user speech end → agent audio start) SHALL be **< 1.5 seconds** under normal conditions. |
| **NFR-003** | Audio chunks from ElevenLabs SHALL be forwarded to Twilio within **50ms** of transcoding completion. |
| **NFR-004** | VAD processing latency per frame SHALL be **< 20ms**. |
| **NFR-005** | STT API response time SHALL be **< 2 seconds** for utterances up to 10 seconds. |

### 4.2 Concurrency

| ID | Requirement |
|----|-------------|
| **NFR-010** | The MVP SHALL support a minimum of **1 concurrent call**. |
| **NFR-011** | The system architecture SHALL be designed to support horizontal scaling for future concurrent call capacity without fundamental redesign. |
| **NFR-012** | Each concurrent call SHALL operate in an isolated session context with no shared mutable state between sessions. |

### 4.3 Audio Format Handling

| ID | Requirement |
|----|-------------|
| **NFR-020** | The system SHALL correctly handle mu-law 8kHz audio from Twilio without quality degradation during decode/encode cycles. |
| **NFR-021** | The system SHALL handle variable audio chunk sizes from Twilio (typically ~20ms, but may vary). |
| **NFR-022** | The system SHALL gracefully handle audio format mismatches by logging a warning and attempting automatic conversion. |

### 4.4 Agent Configuration

| ID | Requirement |
|----|-------------|
| **NFR-030** | Agent configurations SHALL be defined in **JSON format**. |
| **NFR-031** | The agent configuration SHALL include at minimum: `agent_id`, `name`, `system_prompt`, `voice_id` (ElevenLabs), `language`, and `max_history_messages`. |
| **NFR-032** | The system SHALL validate agent configuration on load and reject invalid configurations. |
| **NFR-033** | Agent configurations SHALL be loaded at startup and MAY be reloaded without restarting the service. |

### 4.5 Session TTL Cleanup

| ID | Requirement |
|----|-------------|
| **NFR-040** | The system SHALL implement a **TTL-based cleanup** for zombie sessions (connections that are open but inactive). |
| **NFR-041** | The default session TTL SHALL be **5 minutes** of inactivity. |
| **NFR-042** | A session SHALL be considered inactive if no media messages have been received from Twilio within the TTL window. |
| **NFR-043** | Upon TTL expiration, the system SHALL: (a) close the WebSocket connection, (b) persist any partial transcript, (c) emit a `conversation.timed_out` event, and (d) release all associated resources. |
| **NFR-044** | The session TTL SHALL be configurable via environment variable. |

### 4.6 Error Handling and Graceful Degradation

| ID | Requirement |
|----|-------------|
| **NFR-050** | The system SHALL catch and log all exceptions at the session level without crashing the entire service. |
| **NFR-051** | When the Whisper API is unavailable, the system SHALL respond with a fallback message: *"Disculpa, no pude entender lo que dijiste. ¿Podrías repetirlo?"* and continue the conversation. |
| **NFR-052** | When the ElevenLabs API is unavailable, the system SHALL respond with a text-only fallback message sent as a synthetic audio file (pre-recorded apology) and log the error. |
| **NFR-053** | When the GPT-4o API is unavailable, the system SHALL respond with a fallback message: *"Lo siento, estoy teniendo problemas técnicos. ¿Podrías llamar más tarde?"* and end the call gracefully. |
| **NFR-054** | The system SHALL implement exponential backoff with jitter for API retries (max 3 retries). |
| **NFR-055** | All errors SHALL be logged with structured context: session ID, error type, timestamp, and stack trace. |

---

## 5. Behavioral Scenarios

### 5.1 Happy Path: Complete Conversation Flow

```
Given an agent is configured with a system prompt and ElevenLabs voice
  And the system is running and accepting WebSocket connections
When the system initiates an outbound call to a valid E.164 phone number
  And Twilio connects and opens a Media Stream WebSocket
  And the agent speaks a greeting (e.g., "Hola, ¿cómo estás?")
  And the user responds with "Hola, bien, ¿quién habla?"
  And VAD detects the user has finished speaking (500ms silence)
  And Whisper successfully transcribes the utterance
  And GPT-4o generates a response (e.g., "Soy Ana, la asistente virtual de...")
  And ElevenLabs generates streaming audio for the response
Then the system transcodes the audio to mu-law 8kHz
  And streams the audio chunks to Twilio in real-time
  And the transcript is recorded with timestamps and speaker roles
  And when the call ends, a conversation.completed event is emitted
  And the full transcript and metadata are persisted to SQLite
```

### 5.2 Interruption: User Cuts Agent Mid-Sentence

```
Given the agent is currently speaking a response
  And audio chunks are being streamed to Twilio
When VAD detects the user has started speaking (voice activity in incoming audio)
Then the system immediately stops sending audio chunks to Twilio
  And the active ElevenLabs WebSocket connection is terminated
  And any remaining audio chunks in the delivery queue are discarded
  And an interruption.detected event is emitted with the delivered portion
  And the system processes the user's interrupting utterance as a new turn
  And only the delivered portion of the agent's response is added to conversation history
  And the conversation continues normally with the new context
```

### 5.3 Error: Whisper API Fails

```
Given the user has spoken and VAD has ended the utterance
When the system sends the audio to the Whisper API for transcription
  And the Whisper API returns an error (5xx, timeout, or rate limit)
Then the system logs the error with session context
  And the system responds with the fallback message: "Disculpa, no pude entender lo que dijiste. ¿Podrías repetirlo?"
  And the fallback message is synthesized through ElevenLabs and streamed to Twilio
  And an stt.error event is emitted with the error details
  And the conversation continues without termination
```

### 5.4 Error: ElevenLabs API Fails

```
Given GPT-4o has generated a response text
When the system attempts to establish a WebSocket connection to ElevenLabs
  And the connection fails or the API returns an error
Then the system logs the error with session context
  And the system plays a pre-recorded synthetic apology audio
  And a tts.error event is emitted with the error details
  And the conversation continues (the agent response is recorded as text-only in the transcript)
```

### 5.5 Session Timeout: Zombie Connection Cleanup

```
Given an active call session with an open Twilio WebSocket
When no media messages are received from Twilio for 5 minutes (default TTL)
Then the system closes the WebSocket connection gracefully
  And any partial transcript is persisted to SQLite
  And a conversation.timed_out event is emitted
  And all associated resources (audio buffers, API connections, timers) are released
  And the session is removed from the active sessions registry
```

### 5.6 Edge Case: User Speaks Over Agent Greeting

```
Given the agent has just initiated the call and started speaking the greeting
When the user immediately starts speaking (before the agent finishes the greeting)
Then the system detects the interruption via VAD
  And stops the greeting audio mid-stream
  And processes the user's utterance
  And the agent responds contextually to the user's interruption
```

### 5.7 Edge Case: Empty or Unintelligible Utterance

```
Given VAD has detected speech activity
When the accumulated audio is sent to Whisper
  And Whisper returns an empty string or unintelligible transcription
Then the system responds with: "No pude escucharte bien, ¿podrías repetir?"
  And the empty transcription is NOT added to the conversation history
  And the conversation continues
```

---

## 6. Data Model

### 6.1 Client

Represents a business customer that owns one or more agents.

```python
class Client(BaseModel):
    id: UUID4                          # Unique identifier
    name: str                          # Business name
    phone_number: str                  # Primary contact number (E.164)
    twilio_account_sid: str            # Twilio Account SID
    twilio_auth_token: SecretStr       # Twilio Auth Token
    twilio_phone_number: str           # Twilio phone number for outbound calls
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
```

**SQLite Schema:**
```sql
CREATE TABLE clients (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    phone_number    TEXT NOT NULL,
    twilio_account_sid  TEXT NOT NULL,
    twilio_auth_token   TEXT NOT NULL,
    twilio_phone_number TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 1
);
```

### 6.2 Agent

Represents a configured AI agent with personality, voice, and behavioral settings.

```python
class AgentConfig(BaseModel):
    agent_id: str                      # Unique slug identifier (e.g., "sales-agent-01")
    name: str                          # Display name (e.g., "Ana")
    system_prompt: str                 # Full system prompt for GPT-4o
    voice_id: str                      # ElevenLabs voice ID
    language: str = "es"               # ISO 639-1 language code
    max_history_messages: int = 10     # Max conversation history pairs
    max_response_tokens: int = 300     # Max tokens for LLM response
    speech_end_silence_ms: int = 500   # VAD silence threshold
    max_utterance_duration_s: int = 30 # Max audio duration for STT
    fallback_language: str = "es"      # Language for fallback messages
```

**SQLite Schema:**
```sql
CREATE TABLE agents (
    id                      TEXT PRIMARY KEY,
    client_id               TEXT NOT NULL REFERENCES clients(id),
    name                    TEXT NOT NULL,
    system_prompt           TEXT NOT NULL,
    voice_id                TEXT NOT NULL,
    language                TEXT NOT NULL DEFAULT 'es',
    max_history_messages    INTEGER NOT NULL DEFAULT 10,
    max_response_tokens     INTEGER NOT NULL DEFAULT 300,
    speech_end_silence_ms   INTEGER NOT NULL DEFAULT 500,
    max_utterance_duration_s INTEGER NOT NULL DEFAULT 30,
    fallback_language       TEXT NOT NULL DEFAULT 'es',
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    is_active               INTEGER NOT NULL DEFAULT 1
);
```

### 6.3 Conversation

Represents a single phone call session.

```python
class Conversation(BaseModel):
    id: UUID4                          # Unique session identifier
    client_id: UUID4                   # Owning client
    agent_id: str                      # Agent used for this call
    phone_number: str                  # Destination number (E.164)
    direction: str = "outbound"        # Call direction
    status: str                        # "active", "completed", "failed", "timed_out"
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: float | None     # Total call duration
    error_message: str | None          # Error details if failed
    created_at: datetime
```

**SQLite Schema:**
```sql
CREATE TABLE conversations (
    id              TEXT PRIMARY KEY,
    client_id       TEXT NOT NULL REFERENCES clients(id),
    agent_id        TEXT NOT NULL REFERENCES agents(id),
    phone_number    TEXT NOT NULL,
    direction       TEXT NOT NULL DEFAULT 'outbound',
    status          TEXT NOT NULL DEFAULT 'active',
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    duration_seconds REAL,
    error_message   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_conversations_client ON conversations(client_id);
CREATE INDEX idx_conversations_status ON conversations(status);
CREATE INDEX idx_conversations_started ON conversations(started_at);
```

### 6.4 Transcript Segment

Represents a single turn in the conversation (one utterance + response).

```python
class TranscriptSegment(BaseModel):
    id: UUID4                          # Unique segment identifier
    conversation_id: UUID4             # Parent conversation
    role: str                          # "user" or "agent"
    text: str                          # Transcribed or generated text
    timestamp: datetime                # When this segment occurred
    audio_duration_ms: int | None      # Duration of the audio (if applicable)
    was_interrupted: bool = False      # Whether this agent response was interrupted
    delivered_portion: str | None      # Text that was actually delivered before interruption
    metadata: dict | None              # Additional context (e.g., STT confidence, latency)
```

**SQLite Schema:**
```sql
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

CREATE INDEX idx_transcript_conversation ON transcript_segments(conversation_id);
CREATE INDEX idx_transcript_timestamp ON transcript_segments(timestamp);
```

### 6.5 Event

Represents a domain event emitted during the conversation lifecycle.

```python
class ConversationEvent(BaseModel):
    id: UUID4                          # Unique event identifier
    event_type: str                    # e.g., "conversation.completed", "interruption.detected"
    session_id: UUID4                  # Associated conversation
    timestamp: datetime
    payload: dict                      # Event-specific data
    version: int = 1                   # Event schema version
```

**SQLite Schema (for MVP persistence; events are primarily dispatched via event bus):**
```sql
CREATE TABLE conversation_events (
    id              TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    session_id      TEXT NOT NULL REFERENCES conversations(id),
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    payload         TEXT NOT NULL,  -- JSON blob
    version         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_events_session ON conversation_events(session_id);
CREATE INDEX idx_events_type ON conversation_events(event_type);
```

### 6.6 Event Type Enum

```python
class EventType(str, Enum):
    # Session lifecycle
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"
    CONVERSATION_COMPLETED = "conversation.completed"
    CONVERSATION_FAILED = "conversation.failed"
    CONVERSATION_TIMED_OUT = "conversation.timed_out"

    # VAD
    VAD_SPEECH_STARTED = "vad.speech_started"
    VAD_SPEECH_ENDED = "vad.speech_ended"

    # STT
    STT_COMPLETED = "stt.completed"
    STT_ERROR = "stt.error"

    # LLM
    LLM_COMPLETED = "llm.completed"
    LLM_ERROR = "llm.error"

    # TTS
    TTS_AUDIO_CHUNK = "tts.audio_chunk"
    TTS_COMPLETED = "tts.completed"
    TTS_ERROR = "tts.error"

    # Interruption
    INTERRUPTION_DETECTED = "interruption.detected"

    # Media
    MEDIA_RECEIVED = "media.received"
    MEDIA_SENT = "media.sent"
```

---

## 7. System Architecture Overview

```
┌──────────────┐     WebSocket (mu-law 8kHz)     ┌──────────────────────────────────────┐
│   Twilio     │ ◄─────────────────────────────► │         V1-CallCenter Service         │
│   Media      │                                  │                                      │
│   Streams    │                                  │  ┌─────────────────────────────────┐  │
│              │                                  │  │       SessionManager            │  │
└──────────────┘                                  │  │  - Session lifecycle            │  │
                                                  │  │  - TTL cleanup (5 min)          │  │
                                                  │  │  - Resource isolation           │  │
                                                  │  └──────────────┬──────────────────┘  │
                                                  │                 │                     │
                                                  │  ┌──────────────▼──────────────────┐  │
                                                  │  │       AudioPipeline             │  │
                                                  │  │  - Mu-law ↔ PCM transcoding     │  │
                                                  │  │  - Chunk buffering              │  │
                                                  │  │  - Streaming delivery to Twilio │  │
                                                  │  └──────────────┬──────────────────┘  │
                                                  │                 │                     │
                                                  │  ┌──────────────▼──────────────────┐  │
                                                  │  │       VAD (Silero)              │  │
                                                  │  │  - Speech start/end detection   │  │
                                                  │  │  - Silence threshold (500ms)    │  │
                                                  │  └──────────────┬──────────────────┘  │
                                                  │                 │                     │
                                                  │  ┌──────────────▼──────────────────┐  │
                                                  │  │       STT (Whisper API)         │  │
                                                  │  │  - Transcription                │  │
                                                  │  │  - Error handling + fallback    │  │
                                                  │  └──────────────┬──────────────────┘  │
                                                  │                 │                     │
                                                  │  ┌──────────────▼──────────────────┐  │
                                                  │  │       LLM (GPT-4o)              │  │
                                                  │  │  - Conversation history         │  │
                                                  │  │  - System prompt injection      │  │
                                                  │  │  - Error handling + fallback    │  │
                                                  │  └──────────────┬──────────────────┘  │
                                                  │                 │                     │
                                                  │  ┌──────────────▼──────────────────┐  │
                                                  │  │       TTS (ElevenLabs WS)       │  │
                                                  │  │  - eleven_flash_v2_5 streaming  │  │
                                                  │  │  - Interruption cancellation    │  │
                                                  │  │  - Error handling + fallback    │  │
                                                  │  └──────────────┬──────────────────┘  │
                                                  │                 │                     │
                                                  │  ┌──────────────▼──────────────────┐  │
                                                  │  │       EventBus                  │  │
                                                  │  │  - Internal pub/sub             │  │
                                                  │  │  - Structured logging           │  │
                                                  │  │  - Event persistence (SQLite)   │  │
                                                  │  └─────────────────────────────────┘  │
                                                  │                                      │
                                                  │  ┌─────────────────────────────────┐  │
                                                  │  │       SQLite (MVP)              │  │
                                                  │  │  - Clients, Agents              │  │
                                                  │  │  - Conversations, Transcripts   │  │
                                                  │  │  - Events                       │  │
                                                  │  └─────────────────────────────────┘  │
                                                  └──────────────────────────────────────┘
```

---

## 8. API Endpoints

### 8.1 Initiate Outbound Call

```
POST /api/v1/calls/outbound
Content-Type: application/json

{
    "phone_number": "+5491112345678",
    "agent_id": "sales-agent-01",
    "client_id": "uuid-here"
}

Response 201:
{
    "session_id": "uuid-here",
    "status": "initiated",
    "twilio_call_sid": "CA..."
}
```

### 8.2 Media Stream WebSocket

```
WebSocket /api/v1/media-stream/{session_id}

Twilio sends:
{ "event": "start", "streamSid": "...", "custom": { "session_id": "..." } }
{ "event": "media", "streamSid": "...", "media": { "payload": "<base64>", "track": "inbound" } }
{ "event": "stop", "streamSid": "..." }

Service sends:
{ "event": "media", "streamSid": "...", "media": { "payload": "<base64-mulaw>" } }
{ "event": "clear", "streamSid": "..." }
```

### 8.3 Get Conversation

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
    "transcript": [
        {
            "role": "agent",
            "text": "Hola, ¿cómo estás?",
            "timestamp": "2026-03-30T10:00:05Z"
        },
        {
            "role": "user",
            "text": "Hola, bien, ¿quién habla?",
            "timestamp": "2026-03-30T10:00:10Z"
        }
    ]
}
```

### 8.4 Health Check

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

## 9. Configuration

### 9.1 Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `OPENAI_API_KEY` | OpenAI API key for Whisper + GPT-4o | Yes | — |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for TTS | Yes | — |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | Yes | — |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | Yes | — |
| `TWILIO_PHONE_NUMBER` | Default Twilio phone number | Yes | — |
| `DATABASE_URL` | SQLite database path | No | `sqlite:///./callcenter.db` |
| `SESSION_TTL_SECONDS` | Session inactivity timeout | No | `300` (5 min) |
| `HOST` | Server bind address | No | `0.0.0.0` |
| `PORT` | Server port | No | `8000` |
| `LOG_LEVEL` | Logging level | No | `INFO` |
| `VAD_SILENCE_THRESHOLD_MS` | VAD speech-end silence threshold | No | `500` |
| `MAX_UTTERANCE_DURATION_S` | Max audio duration for STT | No | `30` |
| `MAX_HISTORY_MESSAGES` | Max conversation history pairs | No | `10` |

### 9.2 Agent Configuration (JSON)

```json
{
    "agent_id": "sales-agent-01",
    "name": "Ana",
    "system_prompt": "Eres Ana, una asistente virtual de ventas de TechCorp. Tu objetivo es calificar leads y agendar demos. Sé amable, profesional y concisa. Habla en español rioplatense. No inventes información sobre productos. Si no sabes algo, ofrece agendar una llamada con un especialista.",
    "voice_id": "EXAVITQu4vr4xnSDxMaL",
    "language": "es",
    "max_history_messages": 10,
    "max_response_tokens": 300,
    "speech_end_silence_ms": 500,
    "max_utterance_duration_s": 30,
    "fallback_language": "es"
}
```

---

## 10. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| **Whisper API latency** (1-3s batch) | High | High | Accept for MVP; plan for local Whisper.cpp or alternative STT in Phase 2 |
| **ElevenLabs free-tier limits** (10k chars/month) | Medium | Medium | Monitor usage; implement character counting; alert at 80% threshold |
| **Interruption race conditions** | High | Medium | Use async locks per session; atomic state transitions for speaking/not-speaking |
| **Audio quality degradation** (mu-law ↔ PCM cycles) | Medium | Low | Use high-quality transcoding libraries; validate with audio testing |
| **Zombie sessions consuming resources** | Medium | Medium | TTL-based cleanup with periodic sweep; WebSocket keepalive pings |
| **Single point of failure (no HA for MVP)** | High | Low | Acceptable for MVP; document scaling path for Phase 2 |
| **GPT-4o response too long** (exceeds TTS char limit) | Medium | Medium | Truncate at 2,500 chars; split into multiple TTS generations |

---

## 11. Out of Scope (Future Phases)

The following are explicitly **NOT** included in Phase 1:

- Inbound call handling (Phase 2)
- WhatsApp channel integration (Phase 3)
- Real-time streaming STT (local Whisper.cpp or Deepgram) (Phase 2)
- Multi-language support beyond Spanish (Phase 2)
- Agent admin dashboard / UI (Phase 3)
- Analytics and reporting (Phase 3)
- PostgreSQL migration (Phase 2)
- Horizontal scaling / load balancing (Phase 2)
- Call transfer to human agents (Phase 3)
- Sentiment analysis (Phase 3)
- Custom voice cloning (Phase 3)

---

## 12. Acceptance Criteria

Phase 1 is considered **complete** when all of the following are verified:

1. ✅ The system can initiate an outbound call to a real phone number via Twilio
2. ✅ The agent can carry a multi-turn conversation (minimum 5 exchanges) with a human
3. ✅ The agent's voice is natural and intelligible (ElevenLabs `eleven_flash_v2_5`)
4. ✅ Interruptions are handled correctly — the agent stops speaking when the user interrupts
5. ✅ The total response latency (user speech end → agent audio start) is consistently < 1.5s
6. ✅ Full conversation transcripts are persisted to SQLite with timestamps
7. ✅ Zombie sessions are cleaned up after 5 minutes of inactivity
8. ✅ Graceful degradation works when Whisper, GPT-4o, or ElevenLabs APIs fail
9. ✅ All structured events are logged and emitted via the event bus
10. ✅ The system runs stably for a 30-minute continuous test session without crashes
