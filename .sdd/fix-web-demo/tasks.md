# Tasks: Fix Web Demo Endpoint

**Change ID**: `fix-web-demo`  
**File Modified**: `backend/app/api/routes/web_demo.py`  
**Tests Created**: `backend/tests/test_web_demo.py`

---

## Phase 1: Foundation — Helper Functions

- [ ] 1.1 Create `_build_system_prompt(custom: str | None) -> str` helper in `web_demo.py` that uses default Spanish prompt when no custom prompt provided, and appends `SPANISH_CLAUSE = "Respondé SIEMPRE en español rioplatense. NUNCA respondas en inglés."` to any custom prompt if not already present
- [ ] 1.2 Create `_synthesize_mp3(text: str, settings: Settings) -> bytes` async helper in `web_demo.py` that uses `httpx.AsyncClient` to POST to `https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream`, collects chunks via `aiter_bytes()`, returns `b"".join(chunks)`
- [ ] 1.3 Remove all imports and usage of `ElevenLabsStreamingClient` from `web_demo.py` — no WebSocket TTS code should remain

## Phase 2: Core Implementation — Rewrite `demo_speak` Endpoint

- [ ] 2.1 Add `import time` and `import httpx` to `web_demo.py`; remove `from app.voice.tts import ElevenLabsStreamingClient`
- [ ] 2.2 Add timing instrumentation: `stt_start`, `llm_start`, `tts_start` using `time.monotonic()` around each pipeline stage in `demo_speak`
- [ ] 2.3 Replace Spanish system prompt logic: use `_build_system_prompt()` helper instead of inline `default_prompt` string; ensure `llm.clear_history()` is called before `llm.generate()`
- [ ] 2.4 Replace TTS section: call `_synthesize_mp3(assistant_text, settings)` instead of `ElevenLabsStreamingClient.stream()`; remove all PCM conversion, pydub `AudioSegment` wrapping, and byte-trimming logic
- [ ] 2.5 Add empty response guard: check `if not assistant_text or not assistant_text.strip()` before TTS, return HTTP 400 with `"Empty response from agent."`
- [ ] 2.6 Add MP3 validation: check `if len(mp3_data) < 100` after synthesis, return HTTP 400 with `"No audio data received."`
- [ ] 2.7 Add structured timing log at end of successful request: `logger.info("demo_pipeline_timings", stt_ms=..., llm_ms=..., tts_ms=..., total_ms=...)`
- [ ] 2.8 Add structured response log: `logger.info("demo_llm_response", text=assistant_text, session_id="web_demo")` after LLM returns
- [ ] 2.9 Update endpoint docstring to reflect HTTP streaming TTS (no longer mentions WebSocket or PCM conversion)

## Phase 3: Error Handling

- [ ] 3.1 Wrap `_synthesize_mp3` call in try/except that catches `httpx.HTTPStatusError` and returns HTTP 500 with `"TTS failed: {error}"` and logs `demo_tts_failed`
- [ ] 3.2 Verify existing error handling remains intact: STT empty text → 400, audio conversion failure → 400, raw audio < 100 bytes → 400, STT/LLM API errors → 500
- [ ] 3.3 Ensure response headers are always set on success: `Content-Type: audio/mpeg`, `X-Demo-Transcription`, `X-Demo-Response`

## Phase 4: Testing

- [ ] 4.1 Create `backend/tests/test_web_demo.py` with FastAPI test client setup (reuse `conftest.py` fixtures: `mock_settings`, `test_app`, `test_client`)
- [ ] 4.2 Test `_build_system_prompt()` unit: default prompt contains Spanish clause, custom prompt gets clause appended, custom prompt already containing clause is not duplicated
- [ ] 4.3 Test `_synthesize_mp3()` unit: mock `httpx.AsyncClient.stream()` to return fake MP3 chunks; verify `b"".join()` concatenation and correct URL/headers/payload
- [ ] 4.4 Test Spanish language enforcement: mock LLM to verify `_build_system_prompt()` output always contains `SPANISH_CLAUSE` regardless of custom prompt input
- [ ] 4.5 Test happy path integration: mock STT → text, LLM → Spanish text, httpx → MP3 bytes; verify 200 response, `audio/mpeg` content type, correct headers, timing log present
- [ ] 4.6 Test error scenarios: empty LLM response → 400, TTS HTTP error → 500, audio < 100 bytes → 400, invalid audio format → 400, STT empty → 400
- [ ] 4.7 Test no WebSocket import: grep `web_demo.py` for `ElevenLabsStreamingClient` — zero matches; grep for `AudioSegment` — only in `_convert_browser_audio_to_wav`
- [ ] 4.8 Run full test suite: `cd backend && python -m pytest tests/ -v --tb=short` — verify 489+ tests pass, no regressions

## Phase 5: Cleanup & Verification

- [ ] 5.1 Verify no pydub `AudioSegment` usage in TTS path — only in `_convert_browser_audio_to_wav` for STT preprocessing
- [ ] 5.2 Verify no `websockets` import or `ElevenLabsStreamingClient` reference anywhere in `web_demo.py`
- [ ] 5.3 Manual smoke test: send a valid WebM/Opus audio file to `POST /demo/speak` with mocked services; confirm end-to-end flow returns MP3
- [ ] 5.4 Confirm all spec acceptance criteria (AC-1 through AC-8) are met
