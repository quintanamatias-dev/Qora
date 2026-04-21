# QORA — Quintana Operational Response Architecture

> AI-powered call center platform. Sell "agent employees" to businesses — agents that never get sick, never have bad days, and scale instantly.

## What is QORA?

QORA is a B2B SaaS platform that replaces traditional call center agents with AI voice agents. Companies pay per minute of conversation instead of per employee.

**The core value proposition**: An AI agent that sounds indistinguishable from a human, knows your product, calls your leads, and never burns out.

## Current State — Phase 2 (Memory Loop) ✅

The agent remembers previous conversations. Cross-call memory is working end-to-end in the browser demo — the agent references prior call summaries, extracted facts, and recognizes returning callers.

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
| Mock CRM with test leads | ✅ Working |
| Real-time lead status updates | ✅ Working |
| 342+ passing tests | ✅ |

### Architecture

```
BROWSER (Web Demo)
    │
    │  Native WebSocket
    ▼
ELEVENLABS (Voice Layer)
    • STT — speech to text (~200ms)
    • TTS — text to speech (Adam voice)
    • VAD — detects when user stops talking
    • Turn-taking — manages conversation flow
    │
    │  Custom LLM Webhook (SSE)
    │  POST /api/v1/clients/{client_id}/voice/custom-llm/chat/completions
    ▼
OUR BACKEND (Intelligence Layer — FastAPI)
    • GPT-4o — conversation brain
    • System prompt with memory injection
    • Dynamic fillers — never silent while thinking
    • Memory builder — prior call summaries + extracted facts
    • Session lifecycle — lead linkage + reconciliation
    • Summarizer — post-call summary + fact extraction
    • Multi-tenant routing — per-client isolation
    • Tool calls — register_interest, mark_not_interested, schedule_followup
    │
    ▼
SQLITE (Data Layer)
    • Leads with state machine (new → called → interested → not_interested)
    • Call sessions with lead_id + conversation_id linkage
    • Per-session summaries and extracted facts (JSON)
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
│   │   ├── calls/              # Call sessions, lifecycle, /end endpoint
│   │   ├── tools/              # Agent tools (register_interest, etc.)
│   │   ├── memory.py           # Shared memory context builder
│   │   ├── summarizer.py       # Post-call summary + fact extraction
│   │   ├── sweeper.py          # Stale session cleanup
│   │   └── static/             # Web demo frontend (index.html)
│   ├── clients/                # Per-client prompt templates
│   │   └── quintana-seguros/   # Pilot client
│   ├── tests/                  # 342+ tests (unit + integration)
│   ├── scripts/                # Migration and inspection scripts
│   ├── pyproject.toml
│   ├── .env.example
│   └── README.md               # Backend setup guide
├── docs/
│   ├── architecture.md         # Detailed system architecture
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

### 🔲 Phase 3 — Call Analytics + Client Dashboard
- Post-call analysis automation (conversation insights, duration metrics, abandonment reasons)
- Client-facing dashboard (agent metrics, call history, basic CRM)
- Internal admin panel for agent configuration
- Multi-agent concurrency (multiple agents running simultaneously per client)

### 🔲 Phase 4 — Real Phone Calls
- Deploy to server (Railway/Render)
- Twilio integration for outbound calls
- Public webhook URLs (no more ngrok)

### 🔲 Phase 5 — Sellable Product
- Per-minute billing tracking
- Client onboarding flow
- Real CRM integrations (replacing mock CRM)
- Hume AI sentiment analysis

---

## Quick Start

See [`docs/running-locally.md`](docs/running-locally.md) for full setup.

**TL;DR:**

```bash
# 1. Install dependencies
cd backend
pip install -e .

# 2. Configure environment
cp .env.example .env
# Fill in: OPENAI_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_AGENT_ID

# 3. Run
uvicorn app.main:app --reload

# 4. Open demo
open http://localhost:8000/demo/
```

For ElevenLabs to reach your local webhook, you also need ngrok:
```bash
ngrok http 8000
# Set the ngrok URL as Custom LLM URL in your ElevenLabs agent dashboard
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 + FastAPI |
| LLM | OpenAI GPT-4o |
| Voice | ElevenLabs Conversational AI |
| Database | SQLite (→ PostgreSQL in Phase 4) |
| Testing | pytest + pytest-asyncio (342+ tests) |
| Telephony | Twilio (Phase 4+) |
| Deploy | Railway/Render (Phase 4+) |

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
