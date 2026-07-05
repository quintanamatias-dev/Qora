---
name: qora-client-agent-setup
description: "Trigger: create client, configure agent, ElevenLabs setup, voice demo routing, outbound call setup, new tenant. Set up isolated Qora clients and agents end-to-end."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "2.0"
---

## Activation Contract

Use this skill when creating or debugging a Qora client + agent setup: ElevenLabs Conversational AI routing, outbound call configuration, demo readiness, tenant isolation, or a new client that must not bleed into another tenant.

## Hard Rules

- Treat `client_id` as the tenant boundary. Never reuse another client's Custom LLM URL.
- **Filesystem `system-prompt.md` is the source of truth for every agent prompt.** DB `agent.system_prompt` is legacy fallback only.
- Runtime agent files belong under `backend/clients/{client-id}/agents/{agent-slug}/`.
- Project developer skills belong under root `skills/`; product agent skills under `backend/clients/.../skills/` with suffix `.agent-skill.md`.
- ElevenLabs Custom LLM URL must be `https://{host}/api/v1/voice/{client_id}/custom-llm` — no `/chat/completions` suffix.
- ElevenLabs initiation webhook must include `?client_id={client_id}&lead_id={{lead_id}}`.
- Store the external ElevenLabs `agent_id` on the Qora Agent row (`elevenlabs_agent_id`), not on the Client.
- For outbound: set `elevenlabs_phone_number_id` on the Agent row AND `ENABLE_OUTBOUND_CALLS=true` in `.env`.
- `QORA_WEBHOOK_AUTH_ENABLED=true` requires `QORA_WEBHOOK_SECRET` — startup fails otherwise.
- Telnyx is invisible to Qora. Qora has zero Telnyx API calls. SIP infrastructure is owned by ElevenLabs.

## Filesystem Structure

```text
backend/clients/{client-id}/
├── agents/
│   └── {agent-slug}/
│       ├── system-prompt.md     ← SOURCE OF TRUTH (overrides DB)
│       └── skills/
│           ├── registry.yaml    ← skill index (may be empty: `skills: []`)
│           └── *.agent-skill.md ← runtime knowledge files
├── crm.yaml                     ← CRM field mappings (Airtable or similar)
├── prompt.md                    ← legacy client-level fallback only
└── knowledge.md                 ← optional knowledge base
```

### Prompt priority order (PromptLoader.render_for_agent)

1. `clients/{client_id}/agents/{agent_slug}/system-prompt.md` — **source of truth**
2. `agent.system_prompt` (DB) — legacy fallback
3. `clients/{client_id}/prompt.md` — legacy client-level fallback
4. Hardcoded `JAUMPABLO_PROMPT_TEMPLATE` — last resort

## Decision Gates

| Situation | Action |
|-----------|--------|
| New tenant/client | Create Client row, create filesystem dir, create demo lead |
| New voice agent | Create Agent row with slug + `elevenlabs_agent_id`, write `system-prompt.md` |
| Outbound call needed | Set `elevenlabs_phone_number_id` on Agent, set `ENABLE_OUTBOUND_CALLS=true` in `.env`, enable scheduler |
| Custom LLM fails | Verify ngrok URL externally, inspect ElevenLabs server URL, check `client_id` in path |
| Agent speaks as another tenant | Check Custom LLM URL path `client_id` and initiation webhook `client_id` |
| Need runtime skill | Add `.agent-skill.md` under `backend/clients/{id}/agents/{slug}/skills/`, register in `registry.yaml` |
| Prompt needs updating | Edit `system-prompt.md` — do NOT edit DB directly |
| Webhook auth needed | Generate secret, set `QORA_WEBHOOK_SECRET` in `.env`, set in ElevenLabs Security panel, then enable `QORA_WEBHOOK_AUTH_ENABLED=true` |

## Complete Setup: 5 Phases, 40 Steps

Full reference: `docs/agent-setup-checklist.md`

### Phase 1 — ElevenLabs Dashboard (9 steps, NOT automatable from Qora)

1. Create agent at https://elevenlabs.io/app/agents
2. Set voice (cloned or library voice matching brand)
3. Set Custom LLM URL: `https://{host}/api/v1/voice/{client_id}/custom-llm`
4. Set API Key placeholder: `dummy-key`
5. Set Model ID: `gpt-4o`
6. Set initiation webhook: `https://{host}/api/v1/voice/initiation?client_id={client_id}&lead_id={{lead_id}}`
7. Set first message (agent-specific greeting)
8. **Outbound only**: Add phone number resource (SIP trunk in Phone Numbers panel), copy the `phone_number_id`
9. Set post-call webhook: `https://{host}/api/v1/calls/elevenlabs-postcall` + copy webhook secret

### Phase 2 — Environment Variables (8 steps)

10. `OPENAI_API_KEY` — set if not already present
11. `ELEVENLABS_API_KEY` — set if not already present
12. `QORA_API_KEY` — set if not already present
13. `QORA_DEMO_CLIENT_ID` / `QORA_DEMO_AGENT_ID` — set to new client/agent if this is the demo
14. **Outbound only**: `ENABLE_OUTBOUND_CALLS=true`
15. **Outbound only**: `ELEVENLABS_PHONE_NUMBER_ID={pnum_...}` (from step 8)
16. **Webhook auth**: `QORA_WEBHOOK_SECRET={generated}` + `QORA_WEBHOOK_AUTH_ENABLED=true`
17. Per-client CRM key, e.g. `{CLIENT_NAME}_AIRTABLE_API_KEY`

### Phase 3 — Qora DB: Client + Agent Records (9 steps)

18. Create `Client` row: `id={client_id}`, `name`, `voice_id`, `is_active=True`
19. Set scheduler fields if outbound: `scheduler_enabled=True`, `scheduler_max_attempts`, `scheduler_allowed_hours_start/end`, `scheduler_timezone`
20. Set `next_action_*` fields if using next-action pipeline
21. Set `analysis_language` (default: `"Spanish"`)
22. Create `Agent` row: `client_id`, `slug`, `name`, `voice_id`, `is_default=True`, `is_active=True`
23. Set `elevenlabs_agent_id` on Agent (from step 1)
24. Set `model`, `temperature`, `max_tokens`
25. Set `tools_enabled` (JSON array of tool names)
26. **Outbound only**: Set `elevenlabs_phone_number_id` on Agent (from step 8)
27. Set TTS fields: `tts_speed`, `tts_stability`, `tts_similarity_boost`, `tts_model`

### Phase 4 — Filesystem Content (8 steps)

28. Create `backend/clients/{client_id}/` directory
29. Create `backend/clients/{client_id}/agents/{agent_slug}/` directory
30. Write `system-prompt.md` with full agent prompt and `{{variable}}` placeholders
31. Create `backend/clients/{client_id}/agents/{agent_slug}/skills/` directory
32. Write `skills/registry.yaml` (at minimum: `skills: []`)
33. Write any runtime knowledge files as `*.agent-skill.md`
34. Write `crm.yaml` if CRM integration is needed (see `backend/clients/quintana-seguros/crm.yaml` as template)
35. Seed at least one lead for demo/testing

### Phase 5 — Verification (6 steps)

36. Verify ngrok/public host is reachable: `curl https://{host}/api/v1/health` → 200
37. Test initiation webhook: `curl "https://{host}/api/v1/voice/initiation?client_id={client_id}"` → returns dynamic variables
38. Test Custom LLM route: `curl -X POST https://{host}/api/v1/voice/{client_id}/custom-llm/chat/completions -d '{}'` → 422 (missing `messages`)
39. Run browser demo and confirm backend logs hit `/{client_id}/custom-llm/chat/completions`
40. **Outbound only**: Send one test call via scheduler or API, confirm `scheduled_calls` row transitions to `completed`

## Outbound Call Setup (Detailed)

Outbound calls require four things in sync:

| What | Where |
|------|-------|
| `ENABLE_OUTBOUND_CALLS=true` | `.env` |
| `ELEVENLABS_PHONE_NUMBER_ID=pnum_...` | `.env` |
| `agent.elevenlabs_phone_number_id=pnum_...` | Qora DB Agent row |
| `scheduler_enabled=True` on Client | Qora DB Client row |

Phone number resource setup in ElevenLabs:
1. Go to **Conversational AI → Phone Numbers → Add Phone Number → SIP Trunk**
2. Enter Telnyx SIP credentials (Qora never touches Telnyx directly)
3. Copy the resulting `phone_number_id` (format: `pnum_...`)
4. Set it in both `.env` and on the Agent row

The scheduler tick runs every minute. `ScheduledCall` entries are created by the `next_action` pipeline after post-call analysis, or can be created manually via the admin API.

## Automatable vs Requires Dashboard

| Step | Automatable from Qora? | Notes |
|------|----------------------|-------|
| Create ElevenLabs agent | No | Dashboard only |
| Set voice | No | Dashboard only |
| Set Custom LLM URL | No | Dashboard only (ElevenLabs API exists but Qora doesn't use it) |
| Set initiation webhook | No | Dashboard only |
| Set first message | No | Dashboard only |
| Add phone number resource | No | Dashboard only |
| Copy webhook secret | No | Dashboard copy-paste |
| Set env vars | Script | `python backend/scripts/check-secrets.py` validates |
| Create Client + Agent DB rows | Script / API | `POST /api/v1/clients`, `POST /api/v1/agents` |
| Sync soft timeout config | Qora API | `ElevenLabsService.sync_soft_timeout(agent)` |
| Create filesystem dirs | Script | Could be a `qora setup-client` CLI command |
| Seed leads | API | `POST /api/v1/leads` or CRM import |
| Webhook reachability test | Script | `curl` chain |

**Current automation gap**: ~9 ElevenLabs dashboard steps cannot be scripted without building a wrapper around the ElevenLabs agent provisioning API. This is feasible but not yet implemented.

## Output Contract

Return: client_id, agent_slug, elevenlabs_agent_id, Custom LLM URL, initiation webhook URL, verification evidence, filesystem files created, outbound config status (enabled/disabled), and any remaining risk.

## References

- `docs/agent-setup-checklist.md` — full 40-step checklist with provider dependency table.
- `docs/elevenlabs-setup.md` — ElevenLabs dashboard configuration detail (webhook auth, soft timeout, background audio, tools, KB).
- `docs/telephony/operator-checklist.md` — Telnyx + ElevenLabs SIP trunk setup for outbound.
- `docs/architecture.md` — Qora system architecture, auth layers, data flow.
- `backend/clients/quintana-seguros/` — canonical client reference (crm.yaml, system-prompt.md, skills/).
- `backend/app/prompts/loader.py` — `PromptLoader.render_for_agent()` and `load_agent_system_prompt()`.
- `backend/app/tenants/models.py` — Client and Agent DB schema.
- `.env.example` — all environment variables with documentation.
