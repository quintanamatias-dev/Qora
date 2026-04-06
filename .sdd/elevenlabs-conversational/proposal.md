# Proposal: Migrate to ElevenLabs Conversational AI with Custom LLM

## Intent

The current DIY voice pipeline (Twilio → VAD → STT → LLM → TTS → Twilio) has ~15s end-to-end latency, making conversations feel unnatural and broken. The primary bottleneck is the sequential chain of independent HTTP calls: Whisper STT (~8s) + GPT-4o LLM (~2s) + ElevenLabs TTS (~5s). Replacing this with ElevenLabs Conversational AI reduces latency to ~2.5s by handling VAD, STT, and TTS natively in a single WebRTC/WebSocket connection, while keeping our business logic in a Custom LLM webhook.

## Scope

### In Scope
- **Custom LLM Webhook** — FastAPI SSE endpoint that ElevenLabs Conversational AI calls with transcribed text; streams GPT-4o responses back via Server-Sent Events
- **Web Demo** — Browser-based demo using `@elevenlabs/client` SDK to connect directly to ElevenLabs via WebRTC (no Twilio, no backend media relay)
- **Mega System Prompt** — Insurance sales agent "Jaumpablo" for "Quintana Seguros" (broker name configurable), handling outbound calls to auto insurance leads
- **Configuration** — New env vars for ElevenLabs Conversational AI (agent ID, API key), Custom LLM webhook URL, broker name

### Out of Scope
- Twilio SIP integration with ElevenLabs Conversational AI (future phase)
- n8n/Hume AI sentiment analysis pipeline (future phase)
- Migration or removal of existing DIY pipeline components (VAD, STT, TTS modules remain for fallback)
- Call recording through ElevenLabs (handled separately)

## Approach

1. **Custom LLM Webhook** (`POST /api/v1/elevenlabs/custom-llm`): FastAPI endpoint that receives JSON payloads from ElevenLabs Conversational AI containing transcribed user input and conversation context. Internally calls GPT-4o via streaming SSE and returns the response in ElevenLabs' expected format.

2. **Web Demo**: Static HTML/JS page using `@elevenlabs/client` SDK. Browser establishes WebRTC connection directly to ElevenLabs Conversational AI. The agent is pre-configured with the Jaumpablo system prompt and points to our Custom LLM webhook URL.

3. **System Prompt**: Comprehensive insurance sales prompt for Jaumpablo — handles lead qualification, quote presentation, objection handling, and appointment scheduling for Quintana Seguros.

4. **Coexistence**: The existing DIY pipeline (VAD → STT → LLM → TTS) remains intact. The new ElevenLabs path is additive, accessed via separate routes.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/api/routes/elevenlabs_conversational.py` | New | Custom LLM webhook endpoint for ElevenLabs |
| `backend/app/ai/llm.py` | Modified | Reuse existing GPT4oClient for webhook streaming |
| `backend/app/static/elevenlabs-demo.html` | New | Browser WebRTC demo page |
| `backend/app/config.py` | Modified | Add ElevenLabs Conversational AI settings |
| `backend/app/main.py` | Modified | Register new router |
| `backend/.env.example` | Modified | Add new env vars |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ElevenLabs agent requires API or dashboard creation | High | Document manual agent setup steps; agent ID stored in env |
| Custom LLM webhook must be publicly accessible | High | Use ngrok/tunnel for local dev; document production requirements |
| ElevenLabs Conversational AI pricing unknown | Medium | Test with free tier first; monitor usage metrics |
| SSE streaming format mismatch with ElevenLabs spec | Medium | Follow ElevenLabs Custom LLM docs precisely; add validation |
| Browser WebRTC connectivity issues (firewalls, NAT) | Low | WebRTC handles NAT traversal; fallback to WebSocket if needed |

## Rollback Plan

1. The existing DIY pipeline remains fully functional — no components are removed
2. Remove the new `/api/v1/elevenlabs/custom-llm` route registration from `main.py`
3. Delete `elevenlabs_conversational.py` and `elevenlabs-demo.html`
4. Remove new env vars from `.env` and `config.py`
5. Web demo users simply revert to the existing `/demo` route

## Dependencies

- ElevenLabs API key with Conversational AI access
- ElevenLabs agent created (via API or dashboard) with Custom LLM integration pointing to our webhook
- OpenAI API key (already configured) for GPT-4o
- `@elevenlabs/client` npm package for web demo
- Public URL for webhook (ngrok for development, domain for production)

## Success Criteria

- [ ] Custom LLM webhook receives transcribed text from ElevenLabs and returns GPT-4o response via SSE
- [ ] Web demo connects to ElevenLabs Conversational AI via WebRTC and completes a full conversation loop
- [ ] End-to-end latency (user speaks → agent responds audibly) is under 3 seconds
- [ ] Jaumpablo system prompt correctly identifies as Quintana Seguros insurance agent
- [ ] Broker name is configurable via environment variable
- [ ] Existing DIY pipeline continues to function unchanged
