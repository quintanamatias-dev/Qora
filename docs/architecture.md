# QORA — System Architecture

## Overview

QORA is a Custom LLM webhook server that powers ElevenLabs Conversational AI agents with GPT-4o, multi-tenant routing, lead context injection, and CRM tool execution.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        USER (Browser)                        │
│              Demo UI — /demo/ (index.html)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ WebSocket (wss://api.elevenlabs.io)
                           │ + conversation_initiation_client_data
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    ElevenLabs Platform                       │
│                                                             │
│   ┌──────────────┐    ┌──────────────┐    ┌─────────────┐  │
│   │  Microphone  │───▶│   STT        │───▶│  Agent LLM  │  │
│   │  (browser)   │    │  (ElevenLabs)│    │  orchestr.  │  │
│   └──────────────┘    └──────────────┘    └──────┬──────┘  │
│                                                  │          │
│   ┌──────────────┐                               │ Custom   │
│   │  Speaker     │◀──────────────────────────────┤ LLM POST │
│   │  (browser)   │  TTS (ElevenLabs)             │          │
│   └──────────────┘                               ▼          │
└───────────────────────────────────────────────────────────--┘
                                                   │
                           POST /api/v1/voice/custom-llm
                           (OpenAI-compatible SSE)
                                                   │
                           ┌───────────────────────▼───────────────────────┐
                           │            QORA Backend (FastAPI)              │
                           │                                                │
                           │  ┌──────────────────────────────────────────┐ │
                           │  │          webhook.py                      │ │
                           │  │                                          │ │
                           │  │  1. Parse ElevenLabsExtraBody            │ │
                           │  │     → client_id (required)              │ │
                           │  │     → lead_id (optional)                │ │
                           │  │  2. Load Client from DB                  │ │
                           │  │  3. Load Lead from DB (if lead_id given) │ │
                           │  │  4. render_system_prompt(client, lead)   │ │
                           │  │  5. Select context filler (first token)  │ │
                           │  │  6. Stream GPT-4o (SSE)                  │ │
                           │  │  7. Handle tool calls (mid-stream)       │ │
                           │  │  8. Persist transcript turn to DB        │ │
                           │  └───────────┬──────────────────────────────┘ │
                           │              │                                  │
                           │    ┌─────────▼──────────┐                     │
                           │    │  OpenAI GPT-4o      │                     │
                           │    │  (SSE stream)       │                     │
                           │    └─────────┬──────────┘                     │
                           │              │                                  │
                           │    ┌─────────▼──────────┐                     │
                           │    │  Tool Dispatcher    │                     │
                           │    │  (if tool call)     │                     │
                           │    └─────────┬──────────┘                     │
                           │              │                                  │
                           │    ┌─────────▼──────────┐                     │
                           │    │  SQLite (qora.db)   │                     │
                           │    │  clients │ leads    │                     │
                           │    │  calls   │ turns    │                     │
                           │    └──────────────────── ┘                     │
                           └────────────────────────────────────────────────┘
```

## Components

### Demo UI (`app/static/index.html`)

A single-page browser application. It connects to ElevenLabs via WebSocket using a signed URL (fetched from `/api/v1/voice/signed-url`). It sends microphone audio as PCM chunks, receives TTS audio and transcript events, and displays the conversation in real time.

**WebSocket close handling:**
- Code `1000` → "Conversación finalizada" (clean end)
- Code `1006` or other → "Se perdió la conexión" + reconnect button

### ElevenLabs Agent

The ElevenLabs agent is configured in the ElevenLabs dashboard with:
- **Custom LLM URL**: points to the QORA webhook
- **customLlmExtraBody**: `{ "client_id": "quintana-seguros" }` (injected into every request)
- **Voice**: configured per tenant in the DB (`voice_id` column)

### Custom LLM Webhook (`app/voice/webhook.py`)

The core of QORA. Receives OpenAI-compatible POST requests from ElevenLabs and:
1. Validates `client_id` from `elevenlabs_extra_body` (required — 422 if missing)
2. Looks up the `Client` (tenant) in the database
3. Optionally loads a `Lead` record for context
4. Renders the system prompt using `render_system_prompt(client, lead)` from `app/prompts/insurance_agent.py`
5. Emits a context-aware filler phrase as the first SSE token
6. Streams GPT-4o responses as SSE, intercepting tool calls
7. Persists each agent turn to the `call_turns` table

### System Prompt Renderer (`app/prompts/insurance_agent.py`)

`render_system_prompt(client, lead)` renders the full Jaumpablo prompt with:
- Client-specific variables: `broker_name`, `agent_name`
- Lead-specific variables: `lead_name`, `car_make`, `car_model`, `car_year`, `current_insurance`
- Returning-caller context (if `call_count > 1`)

### Tool Dispatcher (`app/tools/dispatcher.py`)

Dispatches GPT-4o tool calls to implementations:

| Tool | Action |
|------|--------|
| `get_lead_details` | Fetch lead data, increment `call_count` |
| `register_interest` | Transition lead → `interested`, persist car data |
| `mark_not_interested` | Transition lead → `not_interested`, persist reason |
| `schedule_followup` | Transition lead → `follow_up`, persist date + note |

### Database (`qora.db` — SQLite)

| Table | Purpose |
|-------|---------|
| `clients` | Tenant config (model, temperature, voice_id, agent_name, etc.) |
| `leads` | Lead CRM (name, car, insurance, status, call_count) |
| `call_sessions` | Call records (started_at, ended_at, outcome, billable_minutes) |
| `call_turns` | Transcript turns (role, content, timestamp) |

## Data Flow — Single Conversation Turn

```
1. User speaks into microphone
2. ElevenLabs STT transcribes audio → text
3. ElevenLabs posts to QORA: POST /api/v1/voice/custom-llm
   Body: { messages: [...], elevenlabs_extra_body: { client_id, lead_id } }
4. QORA:
   a. Validates client_id → loads Client from DB
   b. Loads Lead from DB (optional)
   c. Renders system prompt (render_system_prompt)
   d. Selects filler (select_filler)
   e. Emits filler as first SSE token → ElevenLabs starts TTS immediately
   f. Streams GPT-4o → more SSE tokens
   g. If tool call detected: executes tool → second GPT-4o call → more SSE tokens
   h. Emits SSE [DONE]
   i. Persists agent turn to DB
5. ElevenLabs TTS converts SSE text tokens → audio
6. Browser plays audio through speaker
7. Browser displays transcript (agent_response event)
```

## Data Lifecycle

### Source of Truth

- `Client` table: tenant identity, broker metadata, scheduler config.
- `Agent` table: per-client AI agent config (voice, model, temperature, tools, `system_prompt` as legacy fallback).
- `Lead` table: lead contact data, status, extracted facts, call count.
- `CallSession` table: per-call records with summaries and outcome data.

**Agent system prompts**: The filesystem file is the source of truth.

```
backend/clients/{client_id}/agents/{agent_slug}/system-prompt.md   ← SOURCE OF TRUTH
```

When this file exists, it overrides `agent.system_prompt` (DB). The DB field is a legacy fallback for agents not yet migrated to the filesystem layout. This makes prompts visible, reviewable in git, and independent of database state.

### Client and Agent Configuration at Startup

Active tenant configuration is seeded via `seed_*()` functions in `backend/app/tenants/service.py`:

- `seed_quintana()` — creates `quintana-seguros` client and default agent.
  Prompt and knowledge content is embedded as `_QUINTANA_SYSTEM_PROMPT` and `_QUINTANA_KNOWLEDGE_BASE` string constants.
  Uses a **non-overwrite guard**: fields are only set if currently missing or blank (`None` or empty string), protecting any admin UI edits.
- `seed_qora_demo()` — creates the Qora demo client + `qora-explainer` agent. The canonical prompt is at `backend/clients/qora-demo/agents/qora-explainer/system-prompt.md`; the DB field is a legacy fallback.

### Soft Delete

Deactivating or removing a client or agent is always a **soft delete**:

- `Client.is_active = False` — client is excluded from active queries (`list_clients()` filters by `is_active=True`).
- `Agent.is_active = False` — agent is excluded from default-agent resolution (`get_default_agent()` filters by `is_active=True`).
- **No hard deletes exist** in the current codebase. No DB rows or filesystem paths are physically deleted on deactivation.
- Inactive tenants receive a `403 Forbidden` from the webhook route (`tenant_not_active` error).
- Associated `Lead` and `CallSession` records remain in the DB and are NOT cascaded to deletion.

### Prompt Rendering

`PromptLoader.render_for_agent(agent, lead, db=db)` resolves the system prompt in this priority order:

1. **Filesystem** `clients/{client_id}/agents/{agent_slug}/system-prompt.md` → source of truth; overrides DB.
2. `agent.system_prompt` (DB) → legacy fallback for agents not yet migrated to filesystem.
3. Filesystem `clients/{client_id}/prompt.md` → legacy client-level fallback.
4. `JAUMPABLO_PROMPT_TEMPLATE` hardcoded constant → last resort.

All prompt paths support `{{variable}}` template substitution (lead_name, call_history, confirmed_facts, etc.).

`agent.knowledge_base` (DB) is appended under `## INFORMACIÓN DE LA EMPRESA` when non-empty. Filesystem `knowledge.md` is NOT used when `agent.knowledge_base` is set.

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 | ✅ Complete | Single tenant (Quintana Seguros), demo UI, tools, transcript |
| Phase 1 | 🔲 Planned | Multi-tenant admin UI, JSON config import CLI, Twilio outbound |
| Phase 2 | 🔲 Planned | Analytics dashboard, A/B prompt testing, call scheduling |
