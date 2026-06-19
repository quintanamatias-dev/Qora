# QORA — Quintana Operational Response Architecture

> AI-powered call center platform. Sell "agent employees" to businesses — agents that never get sick, never have bad days, and scale instantly.

## What is QORA?

QORA is a B2B SaaS platform that replaces traditional call center agents with AI voice agents. Companies pay per minute of conversation instead of per employee.

**The core value proposition**: An AI agent that sounds indistinguishable from a human, knows your product, calls your leads, and never burns out.

## Current State — Phase 7 Complete ✅

Full client dashboard, CRM, internal admin panel, call scheduler, post-call analysis, agent entity model, and unified design system — all implemented and tested.

> **Architecture source of truth:** `docs/architecture.md` owns Qora's runtime architecture, configuration precedence, and source-of-truth decisions. Keep README high-level; put detailed architecture decisions there.

### What works today

| Feature | Status |
|---------|--------|
| Voice conversation via browser | ✅ Working |
| ElevenLabs STT + TTS | ✅ Connected |
| GPT-4o as conversation brain | ✅ Working |
| Custom LLM webhook (our backend) | ✅ Working |
| Dynamic lead context injection | ✅ Working |
| Multi-tenant client routing | ✅ Working |
| Cross-call memory (summaries + facts) | ✅ Working |
| Session lifecycle with lead linkage | ✅ Working |
| Post-call summarization + fact extraction | ✅ Working |
| Structured transcript storage (turn-by-turn) | ✅ Working |
| Base call metrics (count + duration) | ✅ Working |
| Client dashboard with metrics + period selector | ✅ Working |
| CRM — lead list, call history, transcript viewer | ✅ Working |
| CRM — Next Action column (scheduled call visibility) | ✅ Working |
| Post-call analysis (abandonment, interests, problem detection) | ✅ Working |
| Call scheduler with configurable retry logic | ✅ Working |
| Agent entity model (1 client → N agents) | ✅ Working |
| Internal admin CRUD (clients + agents) | ✅ Working |
| Unified design system (admin + client dashboard) | ✅ Working |
| React frontend with TanStack Query | ✅ Working |
| 718 backend + 402 frontend tests | ✅ |

### Architecture

```
BROWSER (Web Demo + Client Dashboard + Admin Panel)
    │
    │  Native WebSocket (voice) / REST API (dashboard)
    ▼
ELEVENLABS (Voice Layer)
    • STT — speech to text (~200ms)
    • TTS — text to speech (Adam voice)
    • VAD — detects when user stops talking
    • Turn-taking — manages conversation flow
    │
    │  Custom LLM Webhook (SSE)
    │  POST /api/v1/clients/{client_id}/voice/{agent_id}/chat/completions
    ▼
OUR BACKEND (Intelligence Layer — FastAPI)
    • GPT-4o — conversation brain
    • System prompt with memory injection
    • Dynamic fillers — never silent while thinking
    • Memory builder — prior call summaries + extracted facts
    • Session lifecycle — lead linkage + reconciliation
    • Summarizer — post-call summary + fact extraction
    • Post-call analysis — abandonment, interests, problem detection
    • Multi-tenant routing — per-client isolation
    • Agent entity model — 1 client → N agents
    • Call scheduler — agenda with configurable retry logic
    • Tool calls — register_interest, mark_not_interested, schedule_followup
    │
    ▼
SQLITE (Data Layer)
    • Leads with state machine (new → called → interested → not_interested)
    • Call sessions with lead_id + conversation_id linkage
    • Per-session summaries and extracted facts (JSON)
    • Per-session call analysis (structured JSON)
    • Scheduled calls with retry configuration
    • Agents (per-client, with own config)
    • Per-client tenant config
```

### The Agent — Jaumpablo

Jaumpablo is an insurance sales agent for Quintana Seguros (pilot client). He:
- Speaks Rioplatense Spanish with natural voseo
- Knows the lead's name and car before the call starts
- **Remembers previous conversations** — references prior summaries and facts
- Conducts the conversation actively — doesn't wait for the user to lead
- Handles objections with specific counter-proposals
- Uses contextual dynamic fillers (never the same one twice)
- Registers interest, marks rejections, schedules follow-ups via tools

---

## Project Structure

```
Qora/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── core/               # Settings, DB, logging
│   │   ├── voice/              # ElevenLabs webhooks (initiation + custom LLM)
│   │   ├── prompts/            # System prompt + template renderer
│   │   ├── leads/              # Lead model + state machine
│   │   ├── tenants/            # Multi-tenant config (clients)
│   │   ├── clients/            # Client CRUD API
│   │   ├── agents/             # Agent entity model + CRUD API
│   │   ├── calls/              # Call sessions, lifecycle, /end endpoint
│   │   ├── scheduler/          # Call scheduler + retry logic
│   │   ├── tools/              # Agent tools (register_interest, etc.)
│   │   ├── ai/                 # LLM client + streaming
│   │   ├── memory.py           # Shared memory context builder
│   │   ├── summarizer.py       # Post-call summary + fact extraction
│   │   ├── analysis_schema.py  # Post-call analysis schema
│   │   ├── sweeper.py          # Stale session cleanup
│   │   └── static/             # Web demo frontend (index.html)
│   ├── clients/                # Per-client prompt templates
│   │   └── quintana-seguros/   # Pilot client
│   ├── tests/                  # 718 backend tests (unit + integration)
│   ├── scripts/                # Migration and inspection scripts
│   ├── pyproject.toml
│   ├── .env.example
│   └── README.md               # Backend setup guide
├── frontend/                   # React client dashboard + admin panel
│   ├── src/
│   │   ├── design/             # Design system (tokens, components)
│   │   ├── features/
│   │   │   ├── dashboard/      # Client metrics dashboard
│   │   │   ├── leads/          # CRM — lead list, detail, transcript viewer
│   │   │   ├── admin/          # Internal admin (clients + agents CRUD)
│   │   │   └── import/         # Lead import
│   │   ├── api/                # TanStack Query hooks + API layer
│   │   └── router.tsx          # App routing
│   └── tests/                  # 402 frontend tests
├── docs/
│   ├── architecture.md         # Detailed system architecture
│   ├── DESIGN.md               # Design system specification
│   ├── running-locally.md      # Step-by-step local setup
│   ├── elevenlabs-setup.md     # ElevenLabs config + session continuity
│   └── elevenlabs-reference.md # ElevenLabs API reference
└── .sdd/                       # Spec-Driven Development artifacts
    ├── qora-prd/               # Product Requirements Document
    ├── qora-phase0/            # Phase 0 spec, design, tasks
    ├── qora-phase2/            # Phase 2 spec, design, tasks
    └── archive/                # Archived completed changes
```

---

## Roadmap

### ✅ Phase 0 — MVP Demo (complete)
Core pipeline working. Web demo with real voice conversation.

### ✅ Phase 1 — Multi-client Foundation (complete)
Per-client configuration, tenant routing, data isolation.

### ✅ Phase 2 — Memory Loop (complete)
Cross-call memory: session continuity, tenant resolution, memory injection into prompt. Agent remembers previous conversations.

### ✅ Phase 3 — Transcripts + Base Metrics (complete)
Structured transcript storage (turn-by-turn). Base call metrics (count + duration).

### ✅ Phase 4 — Client Interface v1 + CRM (complete)
Client web app scaffold. Dashboard with call metrics view. Basic CRM — lead list, call history, transcript viewer.

### ✅ Phase 5 — Post-Call Analysis (complete)
Post-call analysis automation (abandonment detection, interest extraction, problem identification). Session reconciliation. Cross-call memory bugfixes.

### ✅ Phase 6 — Call Scheduler (complete)
Agenda system with configurable retry logic. Schedule follow-up calls from within conversations.

### ✅ Phase 7 — Internal Admin + Multi-Agent (complete)
Agent entity model (1 client → N agents). Internal admin CRUD for clients and agents. CRM Next Action column with scheduled call visibility. Admin panel unified with client dashboard design system.

### 🔲 Phase 8 — Real Telephony
- Deploy to Railway/Render + public webhooks ([#11](../../issues/11))
- Twilio outbound call integration ([#12](../../issues/12))

### 🔲 Phase 9 — Sellable Product
- Lead import via CSV ([#6](../../issues/6))
- Auth (JWT) + per-minute billing ([#13](../../issues/13))
- Real CRM integrations ([#14](../../issues/14))
- Hume AI sentiment analysis ([#15](../../issues/15))

### 🔄 In Progress — Post-Call Analysis v2
- Rethink analysis pipeline for maximum business value ([#33](../../issues/33))
- Per-dimension analysis: each axis owns its prompt + schema + GPT call,
  fanned out in parallel via `asyncio.gather` from the summarizer
- Multi-level analysis: per-call → per-lead → per-company

> **Note about n8n.** The analysis pipeline is now fully Python-native. The
> exported workflow under `docs/n8n-workflows/` and `docker-compose.n8n-local.yml`
> are kept as static modeling/diagramming references only — they are not part
> of the runtime path.

---

## Quick Start

See [`docs/running-locally.md`](docs/running-locally.md) for full setup.

Once dependencies and environment variables are configured, start the whole local stack with one command from the repository root:

```bash
./Qora
```

This starts:
- Backend: `http://localhost:8000`
- ngrok tunnel to the backend for ElevenLabs webhooks
- Frontend: `http://localhost:5173`
- Voice demo: `http://localhost:8000/demo/`

**TL;DR:**

```bash
# 1. Install dependencies
cd backend
pip install -e .

# 2. Configure environment
cp .env.example .env
# Fill in: OPENAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID

# 3. Run migrations first (required — init_db no longer auto-creates schema)
python scripts/migrate.py

# 4. Run
uvicorn app.main:app --reload

# 5. Open demo
open http://localhost:8000/demo/
```

For ElevenLabs to reach your local webhook, `Qora` starts ngrok automatically:
```bash
Qora
# Copy the ngrok HTTPS forwarding URL into your ElevenLabs agent dashboard
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 + FastAPI |
| Frontend | React + TypeScript + TanStack Query + Vite |
| LLM | OpenAI GPT-4o |
| Voice | ElevenLabs Conversational AI |
| Database | SQLite (→ PostgreSQL in Phase 8) |
| Design System | Custom tokens + component library |
| Testing | pytest (718 tests) + Vitest (402 tests) |
| Telephony | Twilio (Phase 8+) |
| Deploy | Railway/Render (Phase 8+) |

---

## What Makes This Different

Everyone can set up an ElevenLabs agent. What we're building is the **call center operations layer** on top:

- **Lead management** — who to call, when, how many times
- **Agent training** — the agent knows your specific product and handles your specific objections  
- **Cross-call memory** — the agent remembers every previous conversation
- **Results tracking** — conversion rate, sentiment, objection patterns
- **Scale** — 1 agent or 100, same cost per minute
- **No vendor lock-in** — swap ElevenLabs for another voice provider in one afternoon

---

*Built with [QORA](https://github.com/quintanamatias-dev/Qora)*
