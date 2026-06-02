---
name: elevenlabs-config
description: "Trigger: ElevenLabs config, TTS change, voice model, speed, stability, first message, soft timeout, agent sync. Modify ElevenLabs voice agent configuration."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when modifying ANY ElevenLabs-related configuration for a Qora voice agent: TTS model, voice parameters, soft timeout, first message, dynamic variables, or agent sync. This covers both code-side and dashboard-side changes.

For agent CONTENT (system prompt, skills, registry), use `qora-agent-designer` instead.
For agent SETUP (client creation, ElevenLabs URL routing, tenant scaffold), use `qora-client-agent-setup` instead.

## Hard Rules

- **Never assume a config change is code-only or dashboard-only.** Always check the config map below.
- When switching TTS model to `eleven_v3_conversational`, speed/stability/similarity_boost MUST NOT be sent — the demo page already handles this via `isV3` check.
- When switching BACK from v3 to flash, ensure the Agent row has valid speed/stability/similarity_boost values (defaults: 0.95, 0.4, 0.75).
- Only `soft_timeout` is API-synced via `elevenlabs/service.py`. All other ElevenLabs settings are either dashboard-only or client-side WebSocket overrides.
- `first_message` is dashboard-only — Qora code does NOT control it today.
- Test TTS changes on the demo page (`localhost:8000/demo/`) before committing.

## Config Map — Where Everything Lives

| Config Area | Where Set | Where Read/Sent | How to Change |
|-------------|-----------|-----------------|---------------|
| **Agent ID** | `agents.elevenlabs_agent_id` (DB) | `index.html` → WebSocket URL | API PATCH or DB update |
| **Voice ID** | `agents.voice_id` (DB) + EL dashboard | EL dashboard binds voice to agent | DB update + dashboard |
| **TTS Model** | `agents.tts_model` (DB) | `index.html` → `isV3` check | API PATCH or DB update |
| **Speed** | `agents.tts_speed` (DB, default 0.95) | `index.html` → `conversation_config_override.tts.speed` | API PATCH (skipped for v3) |
| **Stability** | `agents.tts_stability` (DB, default 0.4) | `index.html` → `conversation_config_override.tts.stability` | API PATCH (skipped for v3) |
| **Similarity boost** | `agents.tts_similarity_boost` (DB, default 0.75) | `index.html` → `conversation_config_override.tts.similarity_boost` | API PATCH (skipped for v3) |
| **Soft timeout** | `agents.soft_timeout_*` (DB) | `elevenlabs/service.py` → EL PATCH API | API PATCH + sync endpoint |
| **First message** | ElevenLabs dashboard only | EL speaks it on WebSocket connect | Dashboard edit |
| **System prompt** | Filesystem `system-prompt.md` (source of truth) | `voice/webhook.py` via PromptLoader | File edit |
| **LLM model** | `agents.model` (DB, default gpt-4o) | `voice/webhook.py` → OpenAI call | API PATCH or DB update |
| **Dynamic variables** | `index.html` `buildInitPayload()` | Sent on WebSocket init | Code edit in `index.html` |
| **Background audio** | ElevenLabs dashboard only | N/A | Dashboard edit |
| **Custom LLM URL** | ElevenLabs dashboard | EL routes to Qora backend | Dashboard edit |

## TTS Model Decision Gate

| Model | Supports speed/stability/similarity? | Supports expressive tags? | Latency | Use when |
|-------|--------------------------------------|---------------------------|---------|----------|
| `eleven_flash_v2_5` | Yes | No | Low (~300ms) | Production, latency-critical |
| `eleven_v3_conversational` | **No** | Yes (`[laughs]`, `[slow]`, `[excited]`, `[whispers]`, `[sighs]`) | Higher (~500ms+) | Expressive agents, testing |

## Execution Steps

### Changing TTS Model

1. Update DB: `UPDATE agents SET tts_model='eleven_v3_conversational' WHERE slug='{slug}' AND client_id='{client}'`
   — or API PATCH: `PATCH /api/v1/clients/{client}/agents/{id}` with `{"tts_model": "eleven_v3_conversational"}`
2. Change model in **ElevenLabs dashboard** → Agent → Voice → Model selector
3. Restart Qora or reload demo page — the `isV3` check auto-skips TTS param overrides

### Changing TTS Parameters (flash model only)

1. API PATCH: `PATCH /api/v1/clients/{client}/agents/{id}` with `{"tts_speed": 0.9, "tts_stability": 0.3, "tts_similarity_boost": 0.8}`
2. Ranges: speed `[0.7, 1.2]`, stability `[0.0, 1.0]`, similarity_boost `[0.0, 1.0]`
3. If ElevenLabs rejects with WebSocket close 1008, demo auto-reconnects without TTS override

### Changing Soft Timeout

1. API PATCH the agent: `{"soft_timeout_seconds": 2.5, "soft_timeout_message": "Sigo acá...", "soft_timeout_use_llm": false}`
2. Trigger sync: `POST /api/v1/clients/{client}/agents/{id}/sync-elevenlabs`
3. Verify: response should show `sync_status: "synced"`

### Changing First Message

1. Go to ElevenLabs dashboard → Agent → First Message
2. Supports `{{variable}}` syntax — use dynamic variables from `buildInitPayload()`
3. Available variables: `{{_lead_name_}}`, `{{_car_make_}}`, `{{_car_model_}}`, `{{_car_year_}}`, `{{_current_insurance_}}`, `{{_company_name_}}`

### Adding Expressive Tags (v3 only)

Add in the system prompt (`system-prompt.md`): instruct the agent to use tags like `[slow]`, `[laughs]`, `[excited]` inline. These are interpreted by the v3 TTS model, not by the LLM.

## Key File Paths

| File | What it does |
|------|-------------|
| `backend/app/tenants/models.py` | Agent DB model — all TTS columns |
| `backend/app/agents/schemas.py` | API request/response schemas |
| `backend/app/agents/router.py` | Agent CRUD endpoints |
| `backend/app/voice/context.py` | `VoiceSessionContext` — TTS values resolved per-session |
| `backend/app/voice/webhook.py` | Custom LLM webhook — system prompt injection |
| `backend/app/elevenlabs/service.py` | Programmatic sync (soft timeout only) |
| `backend/app/static/index.html` | Demo page — WebSocket init, TTS override, v3 detection |
| `backend/app/core/config.py` | Global ElevenLabs defaults (env var overrides) |
| `backend/app/main.py` | Auto-migration for new columns |

## Output Contract

Return: what was changed, which layer (DB/dashboard/code), verification steps taken, and any dashboard changes that must be done manually.

## References

- `docs/elevenlabs-setup.md` — full ElevenLabs dashboard setup guide
- `docs/elevenlabs-reference.md` — WebSocket API, TTS models, expressive tags
- `docs/pipeline-configs/elevenlabs-convai.md` — pipeline configuration reference
- `skills/qora-client-agent-setup/SKILL.md` — infrastructure setup (complementary)
- `skills/qora-agent-designer/SKILL.md` — content design (complementary)
