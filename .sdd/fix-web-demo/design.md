# Design: Fix Web Demo Endpoint

## Technical Approach

Replace the WebSocket-based TTS pipeline with ElevenLabs HTTP streaming to eliminate PCM alignment errors and reduce latency. The web demo endpoint (`POST /demo/speak`) will use direct MP3 synthesis via HTTP, reinforced Spanish system prompts, and per-stage timing instrumentation.

## Architecture Decisions

### Decision: HTTP Streaming over WebSocket TTS

**Choice**: `POST /v1/text-to-speech/{voice_id}/stream` (HTTP streaming)
**Alternatives**: WebSocket (`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`)
**Rationale**: HTTP streaming returns MP3 directly—no PCM conversion, no alignment issues, ~200-500ms less overhead. Simpler error handling (HTTP status codes). The `ElevenLabsStreamingClient` remains available for Twilio pipeline which requires PCM streaming.

### Decision: Concatenate Audio Chunks with b"".join()

**Choice**: Direct byte concatenation (`b"".join(mp3_chunks)`)
**Alternatives**: `AudioSegment` concatenation + pydub export
**Rationale**: HTTP endpoint returns self-contained MP3 chunks—no alignment required. Eliminates pydub transcoding step entirely, saving ~100-300ms. MP3 frames are byte-aligned by spec.

### Decision: Clear LLM History Before Each Request

**Choice**: Call `llm.clear_history()` before `llm.generate()`
**Alternatives**: Rely on per-request client instantiation
**Rationale**: `GPT4oClient` is created per request (correct), but `clear_history()` guarantees no residual state from any internal operations. Safe belt-and-suspenders approach. Micro-overhead (~0.01ms) vs. risk of language contamination.

### Decision: Append Language Enforcement to Custom Prompts

**Choice**: Always append `Respondé SIEMPRE en español rioplatense. NUNCA respondas en inglés.` to custom system prompts
**Alternatives**: Reject custom prompts without Spanish, Ignore language
**Rationale**: Preserves user flexibility (custom prompts allowed) while guaranteeing Spanish output. Simple string check and concatenation—low complexity.

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  POST /demo/speak                                                       │
│  Content-Type: multipart/form-data (audio file)                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  1. Audio Validation                                                    │
│     - Check raw_audio >= 100 bytes                                      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ stt_start = time.monotonic()
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  2. STT Stage (pydub WAV conversion + Whisper API)                      │
│     - Convert webm/opus → WAV (mono, 16kHz, 16-bit)                     │
│     - Transcribe via WhisperClient                                       │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ llm_start = time.monotonic()
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  3. LLM Stage (GPT-4o)                                                  │
│     - Build system prompt with Spanish enforcement                       │
│     - llm.clear_history() → guarantee clean state                      │
│     - await llm.generate(messages, system_prompt)                       │
│     - Log: demo_llm_response {text, session_id}                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ tts_start = time.monotonic()
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  4. TTS Stage (ElevenLabs HTTP Streaming)                               │
│     - POST /v1/text-to-speech/{voice_id}/stream                         │
│     - Stream response via httpx.AsyncClient                              │
│     - Collect MP3 chunks: mp3_chunks.append(chunk)                     │
│     - Return: b"".join(mp3_chunks)                                       │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Response:                                                              │
│     200 OK                                                              │
│     Content-Type: audio/mpeg                                            │
│     X-Demo-Transcription: {user_text}                                    │
│     X-Demo-Response: {assistant_text}                                   │
│                                                                         │
│  Log: demo_pipeline_timings {stt_ms, llm_ms, tts_ms, total_ms}         │
└─────────────────────────────────────────────────────────────────────────┘
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/api/routes/web_demo.py` | Modify | Replace TTS WebSocket with HTTP streaming; reinforce Spanish prompt; add timing |

## Implementation Details

### TTS Function (New)

```python
async def _synthesize_mp3(text: str, settings: Settings) -> bytes:
    """Synthesize text to MP3 using ElevenLabs HTTP streaming."""
    import httpx

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}/stream"
    headers = {
        "xi-api-key": settings.elevenlabs_api_key.get_secret_value(),
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": settings.elevenlabs_model,
        "voice_settings": {
            "stability": settings.elevenlabs_stability,
            "similarity_boost": settings.elevenlabs_speed,
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            mp3_chunks = []
            async for chunk in response.aiter_bytes():
                mp3_chunks.append(chunk)
            return b"".join(mp3_chunks)
```

### System Prompt Builder (Modified)

```python
SPANISH_CLAUSE = "Respondé SIEMPRE en español rioplatense. NUNCA respondas en inglés."

def _build_system_prompt(custom: str | None) -> str:
    """Build system prompt with reinforced Spanish enforcement."""
    base = custom or (
        "Sos un agente de ventas de un call center. "
        "Tu nombre es María. Sos amable, profesional y concisa. "
        "Mantené las respuestas cortas (máximo 2-3 oraciones). "
        "Hablá de forma natural, como si estuvieras en una llamada telefónica. "
        "No uses formato markdown ni listas."
    )
    if SPANISH_CLAUSE not in base:
        base += f"\n\n{SPANISH_CLAUSE}"
    return base
```

### Timing Instrumentation

```python
import time

stt_start = time.monotonic()
# ... STT ...
stt_ms = round((time.monotonic() - stt_start) * 1000)

llm_start = time.monotonic()
# ... LLM ...
llm_ms = round((time.monotonic() - llm_start) * 1000)

tts_start = time.monotonic()
# ... TTS ...
tts_ms = round((time.monotonic() - tts_start) * 1000)

total_ms = stt_ms + llm_ms + tts_ms
logger.info(
    "demo_pipeline_timings",
    stt_ms=stt_ms,
    llm_ms=llm_ms,
    tts_ms=tts_ms,
    total_ms=total_ms,
)
```

## Error Handling

| Condition | HTTP | Detail |
|-----------|------|--------|
| raw_audio < 100 bytes | 400 | "No audio data received." |
| Audio conversion fails | 400 | "Could not decode audio: {e}" |
| STT returns empty | 400 | "Could not understand audio." |
| LLM returns empty | 400 | "Empty response from agent." |
| MP3 < 100 bytes | 400 | "No audio data received." |
| STT API error | 500 | "STT failed: {e}" |
| LLM API error | 500 | "LLM failed: {e}" |
| TTS API error | 500 | "TTS failed: {e}" |

## Response Headers

- `Content-Type: audio/mpeg`
- `X-Demo-Transcription: <transcribed text>`
- `X-Demo-Response: <LLM response text>`

## Performance Targets

| Stage | Target | Previous (WebSocket) |
|-------|--------|---------------------|
| STT | ~1-2s | ~1-2s |
| LLM | ~1-2s | ~1-2s |
| TTS | ~1-2s | ~2-4s (WebSocket + PCM) |
| **Total** | **< 5s p95** | **5-10s** |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | `_synthesize_mp3` | Mock httpx responses; verify MP3 concatenation |
| Unit | `_build_system_prompt` | Test Spanish clause append logic |
| Integration | Full pipeline | 20 requests with varied text lengths; verify no 500s, Spanish output |
| Load | Latency | Measure p95 < 5s across 50 requests |

## Rollback

Single file change (`web_demo.py`). Git revert is sufficient. No database or config changes.

## Open Questions

None — all decisions are resolved in the spec.
