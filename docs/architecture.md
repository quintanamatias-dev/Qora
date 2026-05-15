# QORA — System Architecture

> **Canonical project truth:** this file is the source of truth for Qora's runtime architecture, configuration ownership, and major implementation decisions. If another README or test comment disagrees with this document, update that file or update this document deliberately in the same change.

## Table of Contents

1. [Overview](#overview)
2. [Component Diagram](#component-diagram)
3. [Components](#components)
4. [Data Flow — Single Conversation Turn](#data-flow--single-conversation-turn)
5. [Data Flow — Post-Call Analysis](#data-flow--post-call-analysis)
6. [Data Lifecycle](#data-lifecycle)
7. [Phase Roadmap](#phase-roadmap)

---

## Overview

QORA is a Custom LLM webhook server that powers ElevenLabs Conversational AI agents with GPT-4o, multi-tenant routing, lead context injection, CRM tool execution, post-call analysis, cross-call memory, and dynamic skill loading.

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
                           POST /api/v1/voice/webhook
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
                           │  │  2. Load Client + Agent from DB          │ │
                           │  │  3. Load Lead from DB (if lead_id given) │ │
                           │  │  4. render_system_prompt(agent, lead)    │ │
                           │  │     + skills index injection             │ │
                           │  │     + memory context injection           │ │
                           │  │  5. Stream GPT-4o (SSE)                  │ │
                           │  │  6. Handle tool calls (mid-stream)       │ │
                           │  │  7. Persist transcript turn to DB        │ │
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
                           │    ┌─────────▼──────────────────────────┐     │
                           │    │         SQLite (qora.db)            │     │
                           │    │  clients │ agents │ leads           │     │
                           │    │  call_sessions │ transcript_turns   │     │
                           │    │  call_analyses │ scheduled_calls    │     │
                           │    │  lead_profile_facts │               │     │
                           │    │  lead_interest_history              │     │
                           │    └─────────────────────────────────── ┘     │
                           └────────────────────────────────────────────────┘
                                              │
                               (after call ends)
                                              │
                           ┌───────────────────▼───────────────────────────┐
                           │         Post-Call Summarizer                   │
                           │   asyncio.gather → 13 analysis dimensions      │
                           │   → CallAnalysis row + Lead facts merge        │
                           │   → next_action pipeline → ScheduledCall       │
                           └────────────────────────────────────────────────┘
```

## Components

### Demo UI (`app/static/index.html`)

A single-page browser application. It connects to ElevenLabs via WebSocket using a signed URL (fetched from `/api/v1/voice/signed-url`). It sends microphone audio as PCM chunks, receives TTS audio and transcript events, and displays the conversation in real time.

The demo page does **not** own prompt, model, or voice-tuning defaults. It reads the selected agent configuration from Qora and sends only safe ElevenLabs runtime overrides generated from that agent state.

**WebSocket close handling:**
- Code `1000` → "Conversación finalizada" (clean end)
- Code `1006` or other → "Se perdió la conexión" + reconnect button

### Admin UI (`frontend/src/features/admin`)

The **only** admin UI is the React/Vite frontend at:

```text
http://localhost:5173/admin
```

The backend does not serve a second editable admin. Requests to backend `/admin` redirect to the canonical frontend admin. Do not recreate or edit `backend/app/static/admin/index.html`; that static admin was removed to avoid two competing sources of truth.

Admin responsibilities:
- Client CRUD.
- Agent CRUD.
- Per-agent runtime configuration, including Voice Tuning (`tts_speed`, `tts_stability`, `tts_similarity_boost`).

### ElevenLabs Agent

The ElevenLabs agent is configured in the ElevenLabs dashboard with:
- **Custom LLM URL**: points to the QORA webhook (`/api/v1/voice/{client_id}/custom-llm/chat/completions`)
- **customLlmExtraBody**: `{ "client_id": "quintana-seguros" }` (injected into every request)
- **Voice**: bound to a Qora Agent (`Agent.voice_id` / `Agent.elevenlabs_agent_id`)

Qora may send ElevenLabs conversation overrides, but Qora is the owner of the values. Do not manually tune runtime values in multiple places and then rely on dashboard state.

### Custom LLM Webhook (`app/voice/webhook.py`)

The core of QORA. Receives OpenAI-compatible POST requests from ElevenLabs and:
1. Validates `client_id` from `elevenlabs_extra_body` (required — 422 if missing)
2. Looks up the `Client` (tenant) and `Agent` in the database
3. Optionally loads a `Lead` record for context
4. Renders the system prompt using `PromptLoader().render_for_agent(agent, lead, db, client)` from `app/prompts/loader.py`
5. Injects the skills index from `registry.yaml` and memory context from `build_memory_context()`
6. Streams GPT-4o responses as SSE, intercepting tool calls
7. Persists each agent turn to the `transcript_turns` table

### System Prompt Renderer (`app/prompts/loader.py`)

`PromptLoader().render_for_agent(agent, lead, db, client)` renders the system prompt with:
- Filesystem-first resolution: `backend/clients/{client_id}/agents/{agent_slug}/system-prompt.md` → DB `agent.system_prompt` → legacy client prompt → hardcoded template
- Template variable substitution: `broker_name`, `agent_name`, `lead_name`, `car_make`, `car_model`, `car_year`, `current_insurance`, `call_history`, `confirmed_facts`
- Returning-caller context injected via `build_memory_context(db, lead)` (see `docs/memory-system.md`)
- Skills index injected via `build_skills_index()` (see `docs/skills-system.md`)

### Tool Dispatcher (`app/tools/dispatcher.py`)

Dispatches GPT-4o tool calls to implementations:

| Tool | Action |
|------|--------|
| `get_lead_details` | Fetch lead data, increment `call_count` |
| `register_interest` | Transition lead → `interested`, persist car data |
| `mark_not_interested` | Transition lead → `not_interested`, persist reason |
| `schedule_followup` | Transition lead → `follow_up`, persist date + note |
| `load_skill` | Load a skill from `registry.yaml` at runtime (dynamic knowledge injection) |

### Post-Call Summarizer (`app/summarizer.py`)

Runs automatically after a call ends. See `docs/analysis-pipeline.md` for full documentation.

The summarizer fans out 13 analysis dimensions in parallel via `asyncio.gather`, then runs a post-analysis `next_action` pipeline to determine the recommended next step for the lead. Results are persisted atomically to `CallAnalysis`, `Lead`, `LeadProfileFact`, and `LeadInterestHistory`.

### Memory System (`app/memory.py`)

`build_memory_context(db, lead)` assembles cross-call memory for injection into the system prompt. See `docs/memory-system.md` for full documentation.

### Scheduler (`app/scheduler/`)

Background tick (`scheduler_tick()`) runs every minute and dispatches pending `ScheduledCall` entries to the ElevenLabs outbound call API. Schedule entries are created automatically by the `next_action` pipeline after each call.

### Database (`qora.db` — SQLite)

| Table | Purpose |
|-------|---------|
| `clients` | Tenant config (broker_name, voice_id, scheduler settings, analysis_language) |
| `agents` | Per-client AI agents (model, temperature, voice_id, tts tuning, elevenlabs_agent_id) |
| `leads` | Lead CRM (name, phone, car, insurance, status, call_count, interest_level, extracted_facts) |
| `call_sessions` | Call records (started_at, ended_at, duration, summary, extracted_facts) |
| `transcript_turns` | Per-turn transcript (role, content, timestamp) |
| `call_analyses` | Normalized analysis per call (1:1 with call_sessions, structured query target) |
| `scheduled_calls` | Outbound call queue (scheduled_at, status, trigger_reason, attempt_number) |
| `lead_profile_facts` | Append-and-supersede key-value profile facts per lead (namespaced by prefix) |
| `lead_interest_history` | Append-only time series of interest_level per lead |

## Data Flow — Single Conversation Turn

```
1. User speaks into microphone
2. ElevenLabs STT transcribes audio → text
3. ElevenLabs posts to QORA: POST /api/v1/voice/{client_id}/custom-llm/chat/completions
   Body: { messages: [...], elevenlabs_extra_body: { client_id, lead_id } }
4. QORA:
   a. Validates client_id → loads Client + default Agent from DB
   b. Loads Lead from DB (optional)
   c. Renders system prompt (PromptLoader.render_for_agent)
      — includes skills index + memory context
   d. Streams GPT-4o → SSE tokens
   e. If tool call detected: executes tool → second GPT-4o call → more SSE tokens
      — load_skill injects skill content mid-stream
   f. Emits SSE [DONE]
   g. Persists agent turn to DB
5. ElevenLabs TTS converts SSE text tokens → audio
6. Browser plays audio through speaker
7. Browser displays transcript (agent_response event)
```

## Data Flow — Post-Call Analysis

```
1. Call ends (ElevenLabs sends post-call webhook or frontend calls /calls/{id}/end)
2. QORA closes the CallSession (status → "completed")
3. Summarizer is triggered asynchronously (asyncio.create_task)
4. Summarizer loads transcript turns from DB
5. Runs 13 analysis dimensions in parallel + stateful pipelines
6. Persists:
   - CallSession.summary, .extracted_facts
   - CallAnalysis row (normalized per-column)
   - Lead.interest_level, .objections_heard, .extracted_facts
   - LeadProfileFact rows (upsert / supersede)
   - LeadInterestHistory row (append-only)
7. Runs next_action pipeline → creates ScheduledCall if needed
```

## Data Lifecycle

### Source of Truth

- `Client` table: tenant identity, broker metadata, scheduler config.
- `Agent` table: per-client AI agent runtime config.
- `Lead` table: lead contact data, status, extracted facts, call count.
- `CallSession` table: per-call records with summaries and outcome data.
- `CallAnalysis` table: normalized analysis per call (structured query target).

### Runtime Configuration Sources

| Concern | Source of truth | Fallback / notes |
|---------|-----------------|------------------|
| Admin UI | `frontend/src/features/admin` | Backend `/admin` redirects to frontend admin. No static backend admin. |
| Agent identity/routing | `Agent` DB row | `client_id`, `agent_id`, `slug`, `is_default`, `is_active`. |
| LLM model params | `Agent.model`, `Agent.temperature`, `Agent.max_tokens` | Legacy `Client` columns are fallback only where still present. |
| Voice binding | `Agent.voice_id`, `Agent.elevenlabs_agent_id` | ElevenLabs dashboard must point to Qora Custom LLM, but Qora owns agent binding. |
| Voice tuning / TTS overrides | `Agent.tts_speed`, `Agent.tts_stability`, `Agent.tts_similarity_boost` | `Settings`/`.env` are defaults/backfill only, not the live runtime source once an Agent exists. |
| System prompt behavior | `backend/clients/{client_id}/agents/{agent_slug}/system-prompt.md` | DB `agent.system_prompt` is legacy fallback only. |
| Runtime knowledge / product-agent skills | `backend/clients/{client_id}/agents/{agent_slug}/skills/*.agent-skill.md` | Skill files are client/agent-scoped; never leak another client into a demo agent. |
| Lead/customer context | `Lead` + call memory tables | Injected by `build_voice_context` / prompt renderer per call. |

**Do not add new runtime knobs to the browser.** Browser UI may display and forward resolved values, but the source belongs to the Agent row or filesystem prompt/skill files above.

### Qora Demo Agent (`qora-demo / qora-explainer`)

The Qora explainer demo is configured as:

```text
backend/clients/qora-demo/agents/qora-explainer/
├── system-prompt.md                         ← behavior / soul: Mariano
└── skills/
    ├── registry.yaml                        ← skill registry
    └── Qora-info.agent-skill.md             ← factual Qora knowledge
```

Important behavior decisions:
- The agent is **Mariano**, not Sofia.
- It presents itself when the call starts because the intended flow is outbound-style: Qora/ElevenLabs initiates contact.
- It must not know or mention client-specific agents from other tenants.
- It speaks in short, semi-formal Rioplatense Spanish by default.
- Qora-info is knowledge, not personality; `system-prompt.md` is the dominant behavior contract.

Voice tuning constraints:
- `tts_speed` must stay in the ElevenLabs-safe range `0.7–1.2`.
- `tts_stability` and `tts_similarity_boost` must stay in `0.0–1.0`.
- If ElevenLabs rejects a TTS override with WebSocket `1008`, the browser reconnects once without that override.

**Agent system prompts**: The filesystem file is the source of truth.

```
backend/clients/{client_id}/agents/{agent_slug}/system-prompt.md   ← SOURCE OF TRUTH
```

When this file exists, it overrides `agent.system_prompt` (DB). The DB field is a legacy fallback for agents not yet migrated to the filesystem layout. This makes prompts visible, reviewable in git, and independent of database state.

**Agent runtime skills / knowledge**: product-agent skill files are loaded from:

```text
backend/clients/{client_id}/agents/{agent_slug}/skills/*.agent-skill.md
```

Do not use `SKILL.md` for runtime product-agent skills. `SKILL.md` is reserved for project developer skills under root `skills/`.

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
| Phase 1 | ✅ Complete | Multi-tenant admin UI, Client CRUD, Agent CRUD, skill registry |
| Phase 2 | ✅ Complete | Post-call analysis pipeline (13 dimensions), memory system |
| Phase 3 | ✅ Complete | Analytics dashboard, interest scoring, profile facts |
| Phase 4 | ✅ Complete | Data corrections, misc notes, objections, service issues dimensions |
| Phase 5 | ✅ Complete | Next-action decision engine, scheduler, outbound call queue |
