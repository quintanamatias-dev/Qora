# Qora Agent Setup Checklist

> Complete reference for setting up a new Qora voice agent from scratch.
> Work through the phases in order — each phase depends on the previous one.
>
> **Do not store credential values in this file.** Use your local `.env`.

---

## Architecture Summary

**Qora is the brain. ElevenLabs is the voice body.**

```
Lead's Phone
     │
     ▼
ElevenLabs (Telnyx SIP) ──── STT ──── conversation orchestration ──── TTS ──── audio back
                                              │
                              POST /api/v1/voice/{client_id}/custom-llm/chat/completions
                                              │
                                              ▼
                                    Qora Backend (FastAPI)
                                    ├── Tenant routing
                                    ├── System prompt rendering
                                    ├── GPT-4o streaming
                                    ├── Tool dispatch (CRM, schedule)
                                    ├── Memory context injection
                                    └── Post-call analysis pipeline
```

Qora owns: system prompts, skills, lead data, CRM integrations, LLM calls, post-call analysis, scheduler, memory.
ElevenLabs owns: STT, TTS, real-time conversation orchestration, WebSocket state, phone/SIP infrastructure.
Telnyx is invisible to Qora — it is ElevenLabs' SIP layer. Qora has zero Telnyx API calls.

---

## Phase 1 — ElevenLabs Dashboard

> These 9 steps require the ElevenLabs dashboard. They cannot be scripted from Qora today.

- [ ] **1.1** Go to https://elevenlabs.io/app/agents → **Create Agent**
- [ ] **1.2** Set the voice — clone or pick a library voice that matches the brand
- [ ] **1.3** Set **Custom LLM URL** (LLM panel → Server URL):
  ```
  https://{your-host}/api/v1/voice/{client_id}/custom-llm
  ```
  - API Key field: `dummy-key` (Qora ignores this; backend uses its own `OPENAI_API_KEY`)
  - Model ID: `gpt-4o`
  - **Do NOT append `/chat/completions`** — ElevenLabs adds it automatically
- [ ] **1.4** Set **Initiation Webhook** (Security → Webhook de datos de inicio):
  ```
  https://{your-host}/api/v1/voice/initiation?client_id={client_id}&lead_id={{lead_id}}
  ```
- [ ] **1.5** Set the **first message** (agent-specific greeting, matches the system-prompt persona)
- [ ] **1.6** *(Outbound only)* Add phone number resource: Conversational AI → Phone Numbers → Add → SIP Trunk, enter Telnyx SIP credentials. **Copy the `phone_number_id`** (format: `pnum_...`)
- [ ] **1.7** Set **Post-Call Webhook**:
  ```
  https://{your-host}/api/v1/calls/elevenlabs-postcall
  ```
- [ ] **1.8** *(Webhook auth)* In Security panel, set the webhook secret field to the same value as `QORA_WEBHOOK_SECRET`
- [ ] **1.9** Note the ElevenLabs **agent_id** (format: `agent_...`) — you will need it for the DB record

---

## Phase 2 — Environment Variables

> Edit repo-root `.env`. **Never commit values.**

- [ ] **2.1** `OPENAI_API_KEY=sk-proj-...` — required at startup
- [ ] **2.2** `ELEVENLABS_API_KEY=sk_...` — required at startup
- [ ] **2.3** `QORA_API_KEY=...` — required for admin API access (generate with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`)
- [ ] **2.4** *(Demo client)* `QORA_DEMO_CLIENT_ID={client_id}` and `QORA_DEMO_AGENT_ID={agent_id}` if this is the public demo client
- [ ] **2.5** *(Outbound)* `ENABLE_OUTBOUND_CALLS=true`
- [ ] **2.6** *(Outbound)* `ELEVENLABS_PHONE_NUMBER_ID={pnum_...}` — from Phase 1 step 1.6
- [ ] **2.7** *(Webhook auth)* `QORA_WEBHOOK_SECRET={generated}` then `QORA_WEBHOOK_AUTH_ENABLED=true` — startup fails if auth is enabled but secret is missing
- [ ] **2.8** *(CRM)* Per-client API key, e.g. `QUINTANA_AIRTABLE_API_KEY=pat...`

Validate your `.env` before starting the backend:
```bash
python backend/scripts/check-secrets.py
```

---

## Phase 3 — Qora DB: Client + Agent Records

> Use the admin API (`POST /api/v1/clients`, `POST /api/v1/agents`) or the admin UI at `http://localhost:5173/admin`.

### Client record

- [ ] **3.1** Create `Client` row: `id={client_id}`, `name`, `voice_id`, `is_active=True`
- [ ] **3.2** Set `analysis_language` (default: `"Spanish"`)
- [ ] **3.3** *(Outbound)* Set scheduler config: `scheduler_enabled=True`, `scheduler_max_attempts`, `scheduler_allowed_hours_start`, `scheduler_allowed_hours_end`, `scheduler_timezone`
- [ ] **3.4** *(Optional)* Set `next_action_max_attempts`, `next_action_min_interest_for_followup`

### Agent record

- [ ] **3.5** Create `Agent` row: `client_id={client_id}`, `slug={agent_slug}`, `name`, `voice_id`, `is_default=True`, `is_active=True`
- [ ] **3.6** Set `elevenlabs_agent_id` — from Phase 1 step 1.9
- [ ] **3.7** Set LLM params: `model` (default: `gpt-4o`), `temperature` (default: `0.7`), `max_tokens` (default: `300`)
- [ ] **3.8** Set `tools_enabled` — JSON array, e.g. `["get_lead_details","mark_not_interested","schedule_followup"]`
- [ ] **3.9** *(Outbound)* Set `elevenlabs_phone_number_id` — from Phase 1 step 1.6
- [ ] **3.10** Set TTS params: `tts_speed` (0.7–1.2), `tts_stability` (0.0–1.0), `tts_similarity_boost` (0.0–1.0), `tts_model` (`eleven_flash_v2_5` or `eleven_v3_conversational`)

---

## Phase 4 — Filesystem Content

> Create the client directory structure under `backend/clients/`.

- [ ] **4.1** Create `backend/clients/{client_id}/` directory
- [ ] **4.2** Create `backend/clients/{client_id}/agents/{agent_slug}/` directory
- [ ] **4.3** Write `system-prompt.md` — full agent prompt with `{{variable}}` placeholders:
  - `{{lead_name}}`, `{{call_history}}`, `{{confirmed_facts}}`, `{{is_returning_caller}}`, `{{call_number}}`
  - Company-specific: `{{company_name}}`, `{{agent_name}}`, etc.
- [ ] **4.4** Create `backend/clients/{client_id}/agents/{agent_slug}/skills/` directory
- [ ] **4.5** Write `skills/registry.yaml` — at minimum: `skills: []`
- [ ] **4.6** *(Optional)* Write runtime knowledge files as `{capability}.agent-skill.md` inside `skills/`
- [ ] **4.7** *(CRM)* Write `crm.yaml` — use `backend/clients/quintana-seguros/crm.yaml` as a template; fields: `provider`, `api_key_env`, `base_id`, `table_id`, `field_mappings`, `status_mapping`, `import_status_mapping`
- [ ] **4.8** Seed at least one lead for demo/testing:
  ```bash
  # Via admin API
  POST /api/v1/leads  {"client_id": "{client_id}", "name": "...", "phone": "+549..."}
  ```

---

## Phase 5 — Verification

- [ ] **5.1** Backend reachability:
  ```bash
  curl https://{your-host}/api/v1/health
  # Expected: 200 {"status": "ok"}
  ```
- [ ] **5.2** Initiation webhook smoke test:
  ```bash
  curl "https://{your-host}/api/v1/voice/initiation?client_id={client_id}&lead_id={lead_id}"
  # Expected: 200 with dynamic variables JSON
  ```
- [ ] **5.3** Custom LLM route smoke test:
  ```bash
  curl -X POST https://{your-host}/api/v1/voice/{client_id}/custom-llm/chat/completions \
    -H "Content-Type: application/json" -d '{}'
  # Expected: 422 (missing `messages` field — route is alive and routing correctly)
  ```
- [ ] **5.4** Browser demo: open demo UI, start a call, confirm backend logs show:
  ```
  POST /api/v1/voice/{client_id}/custom-llm/chat/completions 200
  ```
- [ ] **5.5** *(Outbound)* Test scheduled call: create a `ScheduledCall` entry and wait for the scheduler tick (runs every 60s). Confirm it transitions to `completed` and the lead receives a call.
- [ ] **5.6** *(Webhook auth)* Verify 401 without secret, 200 with correct secret:
  ```bash
  curl -X POST https://{your-host}/api/v1/voice/initiation
  # Expected: 401

  curl -X POST https://{your-host}/api/v1/voice/initiation \
    -H "X-Webhook-Secret: {your-secret}" \
    -H "Content-Type: application/json" -d '{"client_id": "{client_id}"}'
  # Expected: 200
  ```

---

## Provider Dependency Table

| Configuration item | Configured where | Depends on | Automatable? |
|-------------------|-----------------|------------|-------------|
| Agent identity + voice | ElevenLabs dashboard | ElevenLabs account | No — dashboard only |
| Custom LLM URL | ElevenLabs dashboard | ngrok/public URL | No — dashboard only |
| Initiation webhook URL | ElevenLabs dashboard | ngrok/public URL | No — dashboard only |
| First message | ElevenLabs dashboard | — | No — dashboard only |
| Phone number resource (SIP) | ElevenLabs dashboard + Telnyx | Telnyx SIP connection | No — dashboard only |
| Post-call webhook | ElevenLabs dashboard | ngrok/public URL | No — dashboard only |
| Webhook secret | ElevenLabs dashboard + `.env` | — | Partial (secret generation is scriptable) |
| `OPENAI_API_KEY` | `.env` | OpenAI account | Script (check-secrets.py validates) |
| `ELEVENLABS_API_KEY` | `.env` | ElevenLabs account | Script |
| `ENABLE_OUTBOUND_CALLS` | `.env` | ElevenLabs SIP setup | Script |
| `ELEVENLABS_PHONE_NUMBER_ID` | `.env` | ElevenLabs phone resource | Script (value from dashboard) |
| CRM API key | `.env` | Airtable / CRM provider | Script |
| Client DB record | Qora DB via API/UI | Qora running | Yes — admin API |
| Agent DB record | Qora DB via API/UI | Client record | Yes — admin API |
| Outbound phone_number_id on Agent | Qora DB via API/UI | ElevenLabs phone resource | Yes — admin API |
| Scheduler config | Qora DB via API/UI | — | Yes — admin API |
| `system-prompt.md` | Filesystem | — | Yes — file creation |
| `skills/registry.yaml` | Filesystem | — | Yes — file creation |
| `crm.yaml` | Filesystem | CRM provider | Yes — file creation |
| Lead seed | Qora DB via API | Client + Agent | Yes — admin API |

---

## Provider Lock-in Analysis

### ElevenLabs — HIGH lock-in, STRUCTURAL

ElevenLabs is the voice body. Its lock-in is deep because it owns:

| Locked capability | Why it's hard to replace |
|------------------|--------------------------|
| STT (speech-to-text) | Real-time streaming, language detection, barge-in detection |
| TTS (text-to-speech) | Custom voice clones, emotional range, latency tuning |
| Real-time conversation orchestration | WebSocket state machine, turn management, barge-in, soft timeout |
| Outbound call API | SIP trunk routing, batch call scheduling |
| Phone number resources | Telnyx SIP pairings registered in ElevenLabs |
| Dashboard-only config | 9 setup steps have no API equivalent in Qora |

**Exit path**: Build an adapter layer. Qora's `POST /api/v1/voice/{client_id}/custom-llm` is already a standard OpenAI-compatible endpoint. Any provider that can call a custom LLM webhook (Vapi, Retell, LiveKit Agents) could replace ElevenLabs at the conversation-orchestration layer with an adapter.

### Telnyx — ZERO direct lock-in for Qora

Telnyx provides SIP infrastructure but Qora never calls Telnyx directly. All Telnyx interactions go through ElevenLabs. Replacing Telnyx requires reconfiguring ElevenLabs phone numbers only.

### OpenAI — LOW lock-in

Qora uses any OpenAI-compatible endpoint. `OPENAI_API_KEY` and model config are in `.env`. Swapping to Anthropic, Groq, or a local model requires only endpoint/key changes.

### Airtable / CRM — SCOPED lock-in

CRM integration is client-scoped via `crm.yaml`. Each client can use a different provider. Adding a new CRM provider requires a new adapter in the CRM sync layer, not a system-wide change.

### Qora-owned and portable

| Asset | Portability |
|-------|------------|
| System prompts (`system-prompt.md`) | Fully portable — plain markdown |
| Runtime skills (`*.agent-skill.md`) | Fully portable — plain markdown |
| `registry.yaml` | Fully portable |
| Lead data (SQLite) | Portable — standard relational schema |
| Post-call analysis pipeline | Portable — any LLM via OpenAI-compatible API |
| Memory system | Portable |
| Scheduler | Portable |
| CRM mappings (`crm.yaml`) | Portable |

---

## Automation Opportunities

### Can be scripted today

| Task | Mechanism |
|------|----------|
| Validate all required env vars | `python backend/scripts/check-secrets.py` |
| Create Client + Agent DB records | `POST /api/v1/clients`, `POST /api/v1/agents` |
| Scaffold filesystem structure | Shell script or `qora setup-client` CLI (not yet built) |
| Seed demo lead | `POST /api/v1/leads` |
| Sync soft timeout config to ElevenLabs | `ElevenLabsService.sync_soft_timeout(agent)` |
| Webhook reachability smoke test | `curl` chain against `/health`, `/initiation`, `/custom-llm` |

### Requires dashboard (not yet scriptable from Qora)

| Task | Blocker |
|------|---------|
| Create ElevenLabs agent | Qora doesn't use ElevenLabs agent provisioning API |
| Set voice | Dashboard only |
| Set Custom LLM URL + first message | Dashboard only |
| Set initiation + post-call webhooks | Dashboard only |
| Add phone number resource (SIP) | Dashboard + Telnyx pairing |
| Copy webhook secret | Manual copy-paste |

**Feasible shortcut**: ElevenLabs does expose a partial agent creation API. Implementing a `qora provision-elevenlabs-agent` command could reduce manual dashboard steps from 9 to ~3 (voice selection, phone provisioning, secret copy-paste). Not yet implemented.

### Future automation targets

- `qora setup-client {client_id}` CLI: scaffold dirs, create DB records, prompt for ElevenLabs agent_id
- ElevenLabs agent provisioning API wrapper: set Custom LLM URL and webhooks programmatically
- CRM lead import from `crm.yaml` on first setup

---

## Common Gotchas

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `custom_llm_error` on WebSocket close | Wrong or unreachable Custom LLM URL | Verify `curl https://{host}/api/v1/health` → 200; check URL in ElevenLabs |
| `404` on custom-llm route | `client_id` not in path or tenant not registered | Ensure URL path uses correct `{client_id}` |
| `403 "Tenant disabled"` | `Client.is_active=False` | Set `is_active=True` on the Client row |
| `422` on initiation webhook | Missing `client_id` query param | Ensure `?client_id={client_id}` is in the URL |
| Agent uses wrong prompt | DB `system_prompt` overriding filesystem | Check that `system-prompt.md` exists at correct path |
| Outbound calls not firing | `ENABLE_OUTBOUND_CALLS` is false or `phone_number_id` not set | Check `.env` and Agent row |
| Scheduler creates calls but they fail | `elevenlabs_phone_number_id` missing on Agent | PATCH Agent record with the phone number ID |
| Startup fails with webhook auth error | `QORA_WEBHOOK_AUTH_ENABLED=true` but no secret | Set `QORA_WEBHOOK_SECRET` in `.env` before enabling auth |
| Lead context missing in call | Lead not seeded or `lead_id` not in dynamic variables | Seed a lead and confirm `lead_id={{lead_id}}` in initiation URL |
| ngrok URL changes on restart | Free tier assigns new subdomain each session | Use `--domain=your-fixed.ngrok-free.dev` or update both ElevenLabs URLs |

---

## Related Docs

- `skills/qora-client-agent-setup/SKILL.md` — AI agent skill (concise, decision-gate format)
- `docs/elevenlabs-setup.md` — ElevenLabs dashboard config detail (soft timeout, background audio, tools, KB, memory flow)
- `docs/telephony/operator-checklist.md` — Telnyx + ElevenLabs SIP trunk setup
- `docs/architecture.md` — full system architecture, auth layers, data flow
- `.env.example` — all environment variables with documentation
- `backend/clients/quintana-seguros/` — canonical client reference
