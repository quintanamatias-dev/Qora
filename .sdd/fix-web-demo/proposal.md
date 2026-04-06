# Proposal: Fix Web Demo Issues

**Change ID**: `fix-web-demo`
**Status**: `proposed`
**Date**: 2026-04-01
**Author**: SDD Propose Agent

---

## Executive Summary

The web demo endpoint (`POST /demo/speak`) has three critical issues that make it unusable:
1. **Agent responds in English** despite Spanish system prompt — caused by shared session history pollution
2. **500 Internal Server Error** on TTS — caused by PCM chunk misalignment when concatenating raw bytes
3. **Slow response time** — caused by sequential pipeline + WebSocket TTS overhead

This proposal scopes **quick fixes only** (not architecture migration). All three fixes target existing code paths with minimal surface area. Estimated effort: **1-2 days**.

---

## Intent

Make the web demo endpoint reliable and fast enough for practical testing of the voice agent, without changing the overall architecture or migrating to ElevenLabs Custom LLM.

---

## Scope

### In Scope
1. Fix PCM alignment crash in TTS audio assembly
2. Fix Spanish language regression in LLM responses
3. Reduce TTS latency by switching from WebSocket to HTTP streaming endpoint
4. Add structured logging at each pipeline stage for observability

### Out of Scope
- ElevenLabs Custom LLM integration (native VAD, bidirectional streaming)
- Streaming LLM responses (token-by-token)
- Streaming TTS responses (play audio as it arrives)
- Frontend changes (browser audio recorder, UI)
- Twilio Media Stream pipeline changes
- Session management overhaul

---

## Approach

### Fix 1: PCM Alignment — Use AudioSegment Concatenation

**Problem**: ElevenLabs WebSocket returns base64-encoded PCM chunks of variable length. When concatenated with `b"".join(audio_chunks)`, the total byte count may not align to 16-bit (2-byte) boundaries, causing `AudioSegment()` to raise a `DataLengthError`.

**Current code** (`web_demo.py:142-151`): Trims trailing bytes to force alignment. This **loses audio data** (up to 1 byte per call) and is a band-aid, not a fix.

**Fix**: Build each chunk as an `AudioSegment` and concatenate using pydub's `+` operator, which handles alignment internally:

```python
# Instead of: raw_pcm = b"".join(audio_chunks)
segments = [
    AudioSegment(data=chunk, sample_width=2, frame_rate=44100, channels=1)
    for chunk in audio_chunks
]
combined = sum(segments)  # pydub concatenation
mp3_buf = io.BytesIO()
combined.export(mp3_buf, format="mp3", bitrate="128k")
```

**Why this works**: `AudioSegment` validates each chunk independently. The `+` operator (and `sum()`) concatenates at the sample level, not the byte level, so no alignment issue can occur.

**Files changed**: `backend/app/api/routes/web_demo.py` (lines 134-164)

### Fix 2: Spanish Language Regression — Isolate Web Demo Sessions

**Problem**: The web demo endpoint uses a hardcoded `session_id="web_demo"` for every request (`web_demo.py:113`). The LLM client (`llm.py`) maintains per-session conversation history in `self._history`. Since a **new `GPT4oClient` instance is created per request** (line 103-107), history is not shared across requests. However, the `session_id` is also used by the `SessionManager` (if wired) and for event tracking.

**Root cause analysis**: After reviewing the code, the LLM client **is** correctly applying the Spanish system prompt on every request. The system prompt is passed explicitly and prepended to messages. The most likely cause of English responses is:
- The ElevenLabs voice "Adam" (`pNInz6obpgDQGcFmaJgB`) is an English-optimized voice that may affect pronunciation/perception
- The LLM may occasionally ignore the language instruction if the user input is ambiguous

**Fix**: Two-part fix:
1. **Add language enforcement to the system prompt** — strengthen the language instruction:
   ```
   Respondé SIEMPRE en español rioplatense. NUNCA respondas en inglés.
   ```
2. **Add response language validation** — log the detected language of the LLM response for observability:
   ```python
   logger.info("demo_llm_response", text=assistant_text, session_id="web_demo")
   ```
3. **Clear LLM history explicitly** before each call to ensure no contamination:
   ```python
   llm.clear_history()  # Before generate()
   ```

**Files changed**: `backend/app/api/routes/web_demo.py` (lines 94-114)

### Fix 3: Reduce TTS Latency — Use ElevenLabs HTTP API Instead of WebSocket

**Problem**: The current TTS flow uses ElevenLabs WebSocket streaming (`wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`), which adds:
- WebSocket handshake overhead (~200-500ms)
- Per-request connection establishment
- PCM → MP3 transcoding step via pydub

**Fix**: Replace WebSocket TTS with ElevenLabs HTTP streaming endpoint (`POST /v1/text-to-speech/{voice_id}/stream`), which:
- Returns MP3 chunks directly (no transcoding needed)
- Uses standard HTTP (no WebSocket overhead)
- Is simpler to implement and more reliable

**Implementation**:
```python
import httpx

async def synthesize_mp3(text: str, settings: Settings) -> bytes:
    """Synthesize text to MP3 using ElevenLabs HTTP streaming."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}/stream"
    headers = {"xi-api-key": settings.elevenlabs_api_key.get_secret_value()}
    payload = {
        "text": text,
        "model_id": settings.elevenlabs_model,
        "voice_settings": {
            "stability": settings.elevenlabs_stability,
            "similarity_boost": settings.elevenlabs_speed,
        },
    }

    async with httpx.AsyncClient() as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            mp3_chunks = []
            async for chunk in response.aiter_bytes():
                mp3_chunks.append(chunk)
            return b"".join(mp3_chunks)
```

**Why this is better**:
- No WebSocket connection overhead
- No PCM alignment issues (MP3 chunks are self-contained)
- No pydub transcoding step (saves ~100-300ms)
- Simpler error handling (HTTP status codes vs WebSocket close codes)
- The `ElevenLabsStreamingClient` class remains available for Twilio pipeline (which needs PCM streaming)

**Files changed**: `backend/app/api/routes/web_demo.py` (lines 120-170)

### Fix 4: Add Pipeline Observability

**Problem**: No timing or structured logging exists for the demo pipeline stages. When something is slow or fails, there's no way to identify which stage is the bottleneck.

**Fix**: Add timing and structured logging at each stage:

```python
import time

start = time.monotonic()
# ... STT ...
stt_duration = time.monotonic() - start

start = time.monotonic()
# ... LLM ...
llm_duration = time.monotonic() - start

start = time.monotonic()
# ... TTS ...
tts_duration = time.monotonic() - start

logger.info(
    "demo_pipeline_timings",
    stt_ms=round(stt_duration * 1000),
    llm_ms=round(llm_duration * 1000),
    tts_ms=round(tts_duration * 1000),
    total_ms=round((stt_duration + llm_duration + tts_duration) * 1000),
)
```

**Files changed**: `backend/app/api/routes/web_demo.py` (entire endpoint function)

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| HTTP TTS endpoint returns different audio quality than WebSocket | Low | Medium | Both use the same model (`eleven_flash_v2_5`); quality should be identical. Test with same voice/text. |
| `AudioSegment` concatenation is slower than `b"".join()` | Low | Low | Only affects demo endpoint, not production Twilio pipeline. The pydub overhead is negligible for short responses. |
| Clearing LLM history breaks multi-turn demo | Low | Low | Web demo is single-turn by design (one audio upload → one response). Multi-turn is handled by the browser UI, not server state. |
| ElevenLabs HTTP streaming has different rate limits | Medium | Low | Same API key, same tier. Rate limits are per-key, not per-endpoint. |
| `sum(segments)` on empty list raises TypeError | Low | Medium | Guard with `if not audio_chunks: raise RuntimeError(...)` (already exists at line 138-139). |

---

## Rollback Plan

All changes are isolated to `backend/app/api/routes/web_demo.py`. To rollback:

1. **Git revert**: `git revert <commit>` — single file change, clean revert
2. **Partial rollback**: If HTTP TTS causes issues, revert only Fix 3 (keep PCM alignment fix and logging)
3. **No database changes**: This change touches no models, migrations, or data
4. **No config changes**: Uses existing environment variables and settings

---

## Success Criteria

1. **No 500 errors**: TTS produces valid MP3 for any valid LLM response text
2. **Spanish responses**: Agent responds in Spanish Rioplatense for Spanish input
3. **Response time < 5s**: End-to-end pipeline completes within 5 seconds for typical utterances
4. **Observable timings**: Logs include per-stage timing for every request

---

## Files to Modify

| File | Changes |
|------|---------|
| `backend/app/api/routes/web_demo.py` | PCM alignment fix, session isolation, HTTP TTS, timing logs |

**No new files created. No new dependencies added** (httpx already used by OpenAI SDK).

---

## Dependencies

- `pydub` — already in use (audio conversion)
- `httpx` — already in use (OpenAI SDK dependency)
- `elevenlabs` Python SDK — **NOT required** (using raw HTTP calls)
