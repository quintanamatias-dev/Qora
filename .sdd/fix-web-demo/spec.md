# Spec: Fix Web Demo Endpoint

**Change ID**: `fix-web-demo`
**Status**: `draft`
**Date**: 2026-04-01
**Source**: [proposal.md](./proposal.md)

---

## 1. Overview

The `POST /demo/speak` endpoint in `backend/app/api/routes/web_demo.py` has three critical defects that make it unreliable for testing the voice agent:

1. **Agent may respond in English** despite a Spanish system prompt
2. **500 Internal Server Error** from PCM byte misalignment during TTS audio assembly
3. **Excessive response latency** from WebSocket TTS overhead and sequential pipeline

This specification defines the required behavior after all fixes are applied.

### 1.1 RFC 2119 Keywords

The keywords **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** in this document are to be interpreted as described in [RFC 2119](https://www.ietf.org/rfc/rfc2119.txt).

---

## 2. Functional Requirements

### 2.1 Spanish Language Enforcement

**Requirement**: The LLM MUST always respond in Spanish Rioplatense regardless of query parameters or user input language.

#### 2.1.1 System Prompt MUST Be Applied

- **Given** a request to `POST /demo/speak` with any combination of query parameters
- **When** the endpoint constructs the LLM call
- **Then** the system prompt MUST contain an explicit, reinforced Spanish Rioplatense language directive

#### 2.1.2 Default Prompt Reinforcement

- **Given** the caller does NOT provide a `system_prompt` query parameter
- **When** the endpoint uses the default prompt
- **Then** the default prompt MUST include the phrase:
  ```
  Respondé SIEMPRE en español rioplatense. NUNCA respondas en inglés.
  ```

#### 2.1.3 Custom Prompt Language Guard

- **Given** the caller provides a custom `system_prompt` query parameter
- **When** the endpoint merges the custom prompt
- **Then** the Spanish language enforcement clause MUST be appended to the custom prompt if it is not already present

#### 2.1.4 Clean History Per Request

- **Given** a new `GPT4oClient` instance is created per request
- **When** `generate()` is called
- **Then** `clear_history()` MUST be called on the client before `generate()` to guarantee no residual state from prior internal operations

#### 2.1.5 Response Logging

- **Given** the LLM produces a response
- **When** the response text is received
- **Then** the endpoint MUST log the response text with a structured `demo_llm_response` event for language verification

---

### 2.2 TTS Audio Assembly — No PCM Misalignment

**Requirement**: The TTS stage MUST produce valid MP3 audio without byte-alignment errors for any valid LLM response text.

#### 2.2.1 HTTP Streaming TTS (Primary Path)

- **Given** the endpoint needs to synthesize audio from LLM response text
- **When** the TTS stage executes
- **Then** it MUST use the ElevenLabs HTTP streaming endpoint (`POST /v1/text-to-speech/{voice_id}/stream`) instead of WebSocket streaming

#### 2.2.2 MP3 Output Directly

- **Given** the HTTP streaming endpoint returns MP3-encoded chunks
- **When** all chunks are collected
- **Then** the endpoint MUST concatenate them with `b"".join()` directly — no PCM conversion, no pydub transcoding, no alignment validation needed

#### 2.2.3 No Data Loss

- **Given** the previous implementation trimmed trailing bytes to force PCM alignment
- **When** the new HTTP streaming path is used
- **Then** zero bytes of audio data MUST be discarded during assembly

#### 2.2.4 Empty Response Handling

- **Given** the LLM returns an empty or whitespace-only response
- **When** the TTS stage is reached
- **Then** the endpoint MUST return a 400 error with a descriptive message — it MUST NOT attempt to call the TTS API with empty text

---

### 2.3 Pipeline Latency

**Requirement**: The end-to-end pipeline SHOULD complete within 5 seconds for typical utterances (1-3 sentence user input, 1-3 sentence LLM response).

#### 2.3.1 No WebSocket Overhead

- **Given** the previous WebSocket TTS path required connection handshake (~200-500ms)
- **When** the HTTP streaming path is used
- **Then** the WebSocket handshake overhead MUST be eliminated

#### 2.3.2 No Transcoding Step

- **Given** the previous path required pydub PCM→MP3 transcoding (~100-300ms)
- **When** the HTTP streaming path returns MP3 directly
- **Then** the transcoding step MUST be removed entirely

#### 2.3.3 Pipeline Timing Logging

- **Given** a request to `POST /demo/speak`
- **When** the request completes (success or failure)
- **Then** the endpoint MUST log structured timing data for each pipeline stage:
  - `stt_ms`: STT transcription duration in milliseconds
  - `llm_ms`: LLM generation duration in milliseconds
  - `tts_ms`: TTS synthesis duration in milliseconds
  - `total_ms`: Total pipeline duration in milliseconds

---

## 3. Technical Specifications

### 3.1 HTTP TTS Implementation

The TTS function MUST:

```
Input:  text (str), settings (Settings)
Output: bytes (complete MP3 data)

1. Construct URL: https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream
2. Set headers: {"xi-api-key": <api_key>, "Content-Type": "application/json"}
3. Build payload:
   {
     "text": <text>,
     "model_id": <model>,
     "voice_settings": {
       "stability": <stability>,
       "similarity_boost": <speed>
     }
   }
4. POST with httpx streaming response
5. Collect all chunks via aiter_bytes()
6. Return b"".join(all_chunks)
```

### 3.2 Error Handling

| Condition | HTTP Status | Detail |
|-----------|-------------|--------|
| No audio data (< 100 bytes) | 400 | "No audio data received." |
| Audio conversion fails | 400 | "Could not decode audio: {error}" |
| STT returns empty text | 400 | "Could not understand audio." |
| LLM returns empty text | 400 | "Empty response from agent." |
| STT API error | 500 | "STT failed: {error}" |
| LLM API error | 500 | "LLM failed: {error}" |
| TTS API error | 500 | "TTS failed: {error}" |

### 3.3 Response Headers

The successful response MUST include:
- `Content-Type: audio/mpeg`
- `X-Demo-Transcription: <transcribed user text>`
- `X-Demo-Response: <LLM response text>`

### 3.4 Dependencies

- `httpx` — already present (OpenAI SDK transitive dependency), no new dependency
- `pydub` — remains required for STT audio conversion (webm/opus → WAV), but NOT used for TTS
- `websockets` — remains required for Twilio pipeline (`ElevenLabsStreamingClient`), but NOT used by web demo
- `ElevenLabsStreamingClient` — MUST NOT be imported or instantiated in the web demo route after this change

---

## 4. Scenarios

### Scenario 1: Happy Path — Spanish Response

```
Given a user uploads a valid WebM/Opus audio file saying "Hola, ¿cómo estás?"
When POST /demo/speak is called
Then the response status is 200
And the response body is valid MP3 audio
And the X-Demo-Response header contains Spanish Rioplatense text
And the X-Demo-Transcription header contains the transcribed text
And the log contains demo_pipeline_timings with stt_ms, llm_ms, tts_ms, total_ms
```

### Scenario 2: PCM Misalignment Eliminated

```
Given the LLM returns a response of any length
When the TTS stage synthesizes the response
Then no DataLengthError or alignment exception is raised
And the resulting MP3 is playable and contains the full synthesized audio
And no bytes are trimmed or discarded during assembly
```

### Scenario 3: Custom System Prompt Still Enforces Spanish

```
Given a caller provides system_prompt="You are a helpful assistant"
When POST /demo/speak is called with valid audio
Then the LLM response is still in Spanish Rioplatense
And the Spanish enforcement clause is appended to the custom prompt
```

### Scenario 4: Empty LLM Response

```
Given the LLM returns an empty or whitespace-only string
When the TTS stage is reached
Then the endpoint returns HTTP 400
And the response body contains "Empty response from agent."
And no TTS API call is made
```

### Scenario 5: TTS API Failure

```
Given the ElevenLabs HTTP API returns a 5xx error
When the TTS stage attempts synthesis
Then the endpoint returns HTTP 500
And the response body contains "TTS failed: {error}"
And the log contains demo_tts_failed with the error details
```

### Scenario 6: Pipeline Timing Observability

```
Given a successful request to POST /demo/speak
When the response is returned
Then a structured log entry exists with keys:
  - stt_ms (integer, milliseconds)
  - llm_ms (integer, milliseconds)
  - tts_ms (integer, milliseconds)
  - total_ms (integer, milliseconds)
And total_ms ≈ stt_ms + llm_ms + tts_ms (within 50ms tolerance for overhead)
```

### Scenario 7: Invalid Audio Input

```
Given a user uploads a file with less than 100 bytes
When POST /demo/speak is called
Then the response status is 400
And the response body contains "No audio data received."
And no STT, LLM, or TTS calls are made
```

### Scenario 8: Audio Conversion Failure

```
Given a user uploads a file that is not valid audio
When POST /demo/speak is called
Then the response status is 400
And the response body contains "Could not decode audio: {error}"
And the log contains audio_conversion_failed with the error
And no STT, LLM, or TTS calls are made
```

---

## 5. Files Modified

| File | Change Description |
|------|-------------------|
| `backend/app/api/routes/web_demo.py` | Replace WebSocket TTS with HTTP streaming; reinforce Spanish system prompt; add `clear_history()` call; add per-stage timing; add response language logging |

### 5.1 Files NOT Modified

| File | Reason |
|------|--------|
| `backend/app/voice/tts.py` | `ElevenLabsStreamingClient` remains unchanged — still used by Twilio pipeline |
| `backend/app/ai/llm.py` | `GPT4oClient` remains unchanged — `clear_history()` already exists |
| `backend/app/config.py` | No new settings required |
| `pyproject.toml` / `requirements.txt` | No new dependencies |

---

## 6. Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | No 500 errors from PCM misalignment | Send 20 requests with varied LLM response lengths; all return 200 |
| AC-2 | Agent responds in Spanish Rioplatense | Send Spanish audio input; verify response text is Spanish |
| AC-3 | Custom system prompt does not break Spanish | Send custom English system prompt; verify response is still Spanish |
| AC-4 | End-to-end latency < 5s (typical) | Measure `total_ms` in logs for 10 typical requests; p95 < 5000ms |
| AC-5 | Pipeline timing logs present | Every successful request logs `demo_pipeline_timings` with all 4 keys |
| AC-6 | No pydub used in TTS path | Grep `web_demo.py` for `AudioSegment` — only appears in `_convert_browser_audio_to_wav` |
| AC-7 | No WebSocket import in web demo | Grep `web_demo.py` for `ElevenLabsStreamingClient` — zero matches |
| AC-8 | Empty LLM response returns 400 | Mock LLM to return ""; verify 400 response |

---

## 7. Out of Scope

The following are explicitly **NOT** part of this change:

- ElevenLabs Custom LLM integration (native VAD, bidirectional streaming)
- Streaming LLM responses (token-by-token SSE)
- Streaming TTS responses (play audio as chunks arrive)
- Frontend changes (browser audio recorder, UI updates)
- Twilio Media Stream pipeline changes
- Session management overhaul
- Database or model changes
- New environment variables or configuration
