# QORA — AI Call Center

QORA is an AI-powered outbound call center platform built on ElevenLabs Conversational AI and GPT-4o. It orchestrates real-time voice conversations between an AI agent and leads, extracts structured intelligence from every call, and automatically schedules follow-ups.

## What QORA Is

QORA connects ElevenLabs' voice agent directly to a Custom LLM webhook backed by GPT-4o. ElevenLabs handles speech-to-text, text-to-speech, and WebSocket transport. QORA provides:

- **Multi-tenant routing** — each client (`client_id`) has its own agents, leads, and config in the database
- **Lead context injection** — lead data (name, car, current insurance) is injected into the system prompt at runtime
- **Tool execution** — GPT-4o can call CRM tools mid-conversation (register interest, mark not interested, schedule follow-up, load skill)
- **Dynamic skill loading** — agents can load detailed product knowledge on demand via `load_skill` tool + `registry.yaml`
- **Post-call analysis** — 13 GPT-4o-mini dimensions run in parallel after every call (summary, outcome, interests, objections, commitments, pain points, service issues, profile facts, misc notes, data corrections, next action, and more)
- **Cross-call memory** — `build_memory_context()` injects last 3 call summaries, profile facts, interest history, and operational notes into every new call
- **Automated scheduling** — `next_action` pipeline determines follow-up strategy and creates `ScheduledCall` entries automatically
- **Analytics dashboard** — overview, service issues, interests, and per-agent stats via `/api/v1/analytics`
- **Admin Bearer auth** — all admin routes protected by `Authorization: Bearer <QORA_API_KEY>` (Phase B5)
- **Session-scoped voice auth** — `AuthorizedSession` cached in session store; demo sessions never get admin scope (Phase B6)
- **Webhook shared-secret auth** — optional `X-Webhook-Secret` validation on ElevenLabs voice endpoints (Phase B7)
- **Configurable CORS** — `QORA_ALLOWED_ORIGINS` restricts browser origins in production (Phase B7)

## Architecture Overview

```
Browser (Demo UI)
      │
      │  WebSocket (wss://api.elevenlabs.io)
      ▼
┌─────────────────────────────────┐
│         ElevenLabs Agent        │
│  (STT → LLM → TTS pipeline)    │
└────────────────┬────────────────┘
                 │  POST /api/v1/voice/{client_id}/custom-llm/chat/completions
                 │  (OpenAI-compatible SSE request)
                 ▼
┌─────────────────────────────────┐
│       QORA Custom LLM Webhook   │
│  (FastAPI — webhook.py)         │
│                                 │
│  1. Validate client_id          │
│  2. Load tenant config (DB)     │
│  3. Load lead context (DB)      │
│  4. Build system prompt         │
│     + skills index              │
│     + memory context            │
│  5. Stream GPT-4o via SSE       │
│  6. Handle tool calls           │
│  7. Persist transcript          │
└────────────┬────────────────────┘
             │
      ┌──────┴──────┐
      ▼             ▼
  GPT-4o         CRM Tools
  (OpenAI)       (DB ops)
             ┌───┴───┐
             ▼       ▼
       load_skill  schedule_followup
```

## Prerequisites

- **Python 3.11+**
- **API Keys**: OpenAI, ElevenLabs
- **ngrok** (for exposing the local webhook to ElevenLabs)

## Setup

1. **Clone and navigate to backend**

   ```bash
   cd Qora/backend
   ```

2. **Create and activate a virtual environment**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -e ".[dev]"
   ```

4. **Configure environment**

   ```bash
   # Run from the repo root — .env.example lives there (B8 convention)
   cd ..
   cp .env.example .env
   # Edit .env and fill in your API keys
   ```

   > **Root `.env` is the single source of truth for the backend.** Do NOT create `backend/.env`; the application ignores it since B8.

   **Core**

   | Variable | Description |
   |----------|-------------|
   | `OPENAI_API_KEY` | OpenAI API key — used for GPT-4o |
   | `ELEVENLABS_API_KEY` | ElevenLabs API key |
   | `DATABASE_URL` | SQLite path (default: `sqlite+aiosqlite:///./qora.db`) |

   **Authentication (Phase B5)**

   | Variable | Default | Description |
   |----------|---------|-------------|
   | `QORA_API_KEY` | — | Admin Bearer token. All admin routes return 401 without this. Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
   | `QORA_DOCS_ENABLED` | `true` | Set `false` to disable `/docs` and `/redoc` in production. |
   | `QORA_WEBHOOK_SECRET` | — | Shared secret for `X-Webhook-Secret` header. Required when `QORA_WEBHOOK_AUTH_ENABLED=true`. |
   | `QORA_WEBHOOK_AUTH_ENABLED` | `false` | Enable webhook shared-secret validation. Startup fails if `true` without a secret. |
   | `QORA_ALLOWED_ORIGINS` | `*` | CORS allow-list. Comma-separated in production: `https://app.example.com,https://admin.example.com`. |

5. **Run database migrations (required before first start)**

   ```bash
   python scripts/migrate.py
   ```

   This runs `alembic upgrade head` to create or migrate the SQLite schema.
   The application no longer auto-creates tables on startup — migrations must
   run first. The `Qora` launcher does this automatically; only manual
   `uvicorn` starts require this step.

6. **Run the server**

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

7. **Expose via ngrok** (required for ElevenLabs to reach your webhook)

   ```bash
   ngrok http 8000
   ```

   Configure your ElevenLabs agent's Custom LLM URL:
   ```
   https://<your-ngrok-id>.ngrok-free.app/api/v1/voice/{client_id}/custom-llm
   ```
   ElevenLabs will append `/chat/completions` automatically.

## API Endpoints

### Voice

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/voice/{client_id}/custom-llm/chat/completions` | Multi-tenant Custom LLM webhook |
| POST | `/api/v1/voice/initiation` | ElevenLabs call initiation webhook (injects lead context) |
| POST | `/api/v1/voice/webhook` | Legacy webhook path (deprecated) |

### Calls

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/calls` | List all call sessions for a client |
| GET | `/api/v1/calls/metrics` | Aggregated call metrics (count, duration, outcomes) |
| GET | `/api/v1/calls/{session_id}` | Get a single call session |
| GET | `/api/v1/calls/{session_id}/transcript` | Get all transcript turns |
| POST | `/api/v1/calls/{conversation_id}/end` | Close a call session (idempotent) |
| POST | `/api/v1/calls/elevenlabs-postcall` | ElevenLabs post-call webhook (transcript merge) |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/analytics/{client_id}/overview` | Aggregated call metrics (period filter) |
| GET | `/api/v1/analytics/{client_id}/service-issues` | Ranked service issues |
| GET | `/api/v1/analytics/{client_id}/interests` | Top interests with trend direction |
| GET | `/api/v1/analytics/{client_id}/agent-stats` | Per-agent statistics |

### Clients

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/clients` | Create a new client (tenant) |
| GET | `/api/v1/clients` | List all active clients |
| GET | `/api/v1/clients/{client_id}` | Get a single client |
| PATCH | `/api/v1/clients/{client_id}` | Partial update (scheduler config, voice, etc.) |
| DELETE | `/api/v1/clients/{client_id}` | Soft delete (sets is_active=False) |

### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/clients/{client_id}/agents` | Create a new agent |
| GET | `/api/v1/clients/{client_id}/agents` | List all active agents for a client |
| GET | `/api/v1/clients/{client_id}/agents/{agent_id}` | Get a single agent |
| PATCH | `/api/v1/clients/{client_id}/agents/{agent_id}` | Partial update (model, voice, TTS params, etc.) |
| POST | `/api/v1/clients/{client_id}/agents/{agent_id}/deactivate` | Soft delete agent |
| POST | `/api/v1/clients/{client_id}/agents/{agent_id}/make-default` | Atomically swap default agent |

### Scheduler

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/scheduler/{client_id}/queue` | Create manual scheduled call |
| GET | `/api/v1/scheduler/{client_id}/queue` | List scheduled calls (filterable) |
| GET | `/api/v1/scheduler/{client_id}/queue/{id}` | Get a single scheduled call |
| POST | `/api/v1/scheduler/{client_id}/queue/{id}/cancel` | Cancel a pending call |
| PATCH | `/api/v1/scheduler/{client_id}/queue/{id}` | Reschedule a pending call |

### Leads

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/leads` | List leads for a client |
| GET | `/api/v1/leads/{lead_id}` | Get lead details + extracted facts |
| POST | `/api/v1/leads` | Create a new lead |
| PATCH | `/api/v1/leads/{lead_id}/status` | Transition lead status (state machine) |
| GET | `/api/v1/leads/{lead_id}/history` | Call session history for a lead |

### Meta

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check (status + uptime) |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc UI |

## Data MCP + Onboarding Harness

Two internal-only developer tools, additive to the HTTP API above, both running in-process against the same `DATABASE_URL`:

### `python -m app.mcp` — read-only data MCP server

Starts a stdio MCP server exposing `list_clients`, `get_client`, `list_agents`, `get_agent` (effective config + per-field provenance), `list_leads`, `get_lead`, `list_calls`, `get_call`. No write tools. Tenant-data tools (`list_leads`/`get_lead`/`list_calls`/`get_call`) require `client_id` — never default to a cross-tenant view. No tool ever returns a secret-shaped field.

```bash
DATABASE_URL=sqlite+aiosqlite:///./qora.db uv run python -m app.mcp
```

To register it in Claude Code or Codex as a stdio MCP server, point the launcher at `uv run python -m app.mcp` with `cwd` set to this `backend/` directory and `DATABASE_URL` set in its `env`. Both tools launch it as a local subprocess — no network transport is exposed.

### `python -m app.onboarding` / `POST /api/v1/admin/onboarding` — onboarding harness

Automates the DB-and-filesystem provisioning steps of `skills/qora-client-agent-setup/SKILL.md` (client row, agent row + revision 1, analysis profile, CRM integration row) from one declarative spec (`app/onboarding/spec.py`). The CLI and the admin endpoint call the same `app/onboarding/service.py:run_onboarding` function, so they can never diverge.

- **Never-secrets guarantee**: the spec schema (`extra="forbid"`) has no field that accepts a credential value. A CRM secret, if needed, is set afterward via the existing `PUT /clients/{client_id}/integrations/{provider}/secret` endpoint.
- **client_id required**: every spec names an explicit `client_id` and `agent_slug`.
- **Idempotent**: re-running an identical spec reports `already_exists` per entity instead of duplicating or erroring.

```bash
# Validate only — writes nothing
uv run python -m app.onboarding path/to/spec.yaml --dry-run

# Provision
uv run python -m app.onboarding path/to/spec.yaml
```

```bash
# Equivalent via the admin API (superadmin only)
curl -X POST https://{host}/api/v1/admin/onboarding \
  -H "Authorization: Bearer $QORA_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"spec": { ... }, "dry_run": true}'
```

The result is a checklist naming every automated step's outcome plus the manual ElevenLabs-dashboard steps (Phase 1/5 of the skill) the harness does not and cannot automate.

## ElevenLabs Agent Configuration

To connect a new ElevenLabs agent to QORA's multi-tenant backend, see the setup guide:

**[`docs/elevenlabs-setup.md`](../docs/elevenlabs-setup.md)**

The guide covers Custom LLM URL configuration, the Initiation Webhook, Post-Call Webhook, common gotchas (ngrok URL changes, HTTPS requirement, `/chat/completions` suffix), and a troubleshooting table.

## Running Tests

```bash
pytest tests/ -q
```

Run with coverage:

```bash
pytest tests/ --cov=app --cov-report=term-missing
```

## Project Structure

```
backend/
├── app/
│   ├── main.py                  # FastAPI app, lifespan, DB init, router registration
│   ├── memory.py                # Cross-call memory builder (build_memory_context)
│   ├── summarizer.py            # Post-call analysis orchestrator (13 dimensions)
│   ├── sweeper.py               # Background stale session cleanup
│   ├── core/
│   │   ├── config.py            # pydantic-settings (env vars)
│   │   └── database.py          # SQLAlchemy async engine
│   ├── voice/
│   │   ├── webhook.py           # Custom LLM webhook (core of QORA)
│   │   ├── initiation.py        # ElevenLabs call initiation webhook
│   │   ├── context.py           # build_voice_context() helper
│   │   └── session.py           # In-memory per-call ConversationState store
│   ├── prompts/
│   │   ├── loader.py            # PromptLoader — system prompt renderer
│   │   ├── skill_loader.py      # Skill registry parser + skills index builder
│   │   └── insurance_agent.py   # Legacy Jaumpablo prompt template
│   ├── analysis/
│   │   ├── schema.py            # PostCallAnalysis Pydantic model
│   │   ├── enums.py             # Shared enum types
│   │   └── universal/           # 13 analysis dimension modules
│   │       ├── summary.py
│   │       ├── outcome.py
│   │       ├── commitments.py
│   │       ├── objections.py
│   │       ├── problem.py
│   │       ├── service_issues.py
│   │       ├── profile_facts.py
│   │       ├── misc_notes.py
│   │       ├── data_corrections.py
│   │       ├── next_action.py
│   │       └── interest/
│   │           ├── interests.py
│   │           ├── interest_level.py
│   │           ├── catalog.py
│   │           └── pipeline.py
│   ├── tenants/                 # Multi-tenant config (Client + Agent models + service)
│   ├── clients/                 # Full CRUD router for clients
│   ├── agents/                  # Full CRUD router for agents
│   ├── leads/                   # Lead CRM (Lead model + service + state machine)
│   ├── calls/                   # Call session lifecycle + transcript persistence
│   ├── analytics/               # Analytics aggregation endpoints
│   ├── scheduler/               # Outbound call scheduler (tick + CRUD)
│   ├── tools/                   # CRM tool implementations (GPT-4o function calls)
│   ├── ai/
│   │   └── llm_streaming.py     # OpenAI streaming client
│   └── static/
│       └── index.html           # Browser demo UI
├── clients/
│   └── quintana-seguros/
│       └── agents/jaumpablo/
│           └── skills/
│               └── registry.yaml
├── tests/
│   ├── unit/                    # Unit tests per module
│   ├── integration/             # Integration tests (webhook, app wiring)
│   └── test_spec_coverage.py    # Spec scenario coverage matrix
└── pyproject.toml
```

> **Note:** The env template is at repo root — `../.env.example` (B8 convention). There is no `backend/.env.example`. Copy `../.env.example` to `../.env` (repo root) before starting the server.

## License

MIT
