# QORA — Quintana Operational Response Architecture

> AI-powered call center platform. Sell "agent employees" to businesses — agents that never get sick, never have bad days, and scale instantly.

## What is QORA?

QORA is a B2B SaaS platform that replaces traditional call center agents with AI voice agents. Companies pay per minute of conversation instead of per employee.

**The core value proposition**: An AI agent that sounds indistinguishable from a human, knows your product, calls your leads, and never burns out.

## Current State — Phase 0 (MVP Demo) ✅

The core pipeline is working end-to-end. You can have a real voice conversation with Jaumpablo, an AI insurance sales agent, through a web browser — no phone required.

### What works today

| Feature | Status |
|---------|--------|
| Voice conversation via browser | ✅ Working |
| ElevenLabs STT + TTS | ✅ Connected |
| GPT-4o as conversation brain | ✅ Working |
| Custom LLM webhook (our backend) | ✅ Working |
| Dynamic lead context injection | ✅ Working |
| Mock CRM with 5 test leads | ✅ Working |
| Real-time lead status updates | ✅ Working |
| Mute button + reconnect on disconnect | ✅ Working |
| 180 passing tests | ✅ |

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
    │  POST /api/v1/voice/custom-llm/chat/completions
    ▼
OUR BACKEND (Intelligence Layer — FastAPI)
    • GPT-4o — conversation brain
    • System prompt — Jaumpablo's personality & sales flow
    • Dynamic fillers — never silent while thinking
    • Mock CRM — lead data, status transitions
    • Tool calls — register_interest, mark_not_interested, schedule_followup
    │
    ▼
SQLITE (Mock CRM)
    • Leads with state machine (new → called → interested → not_interested)
    • Call sessions and transcripts
    • Per-client tenant config
```

**Key architectural decision**: ElevenLabs owns the audio (STT/TTS/VAD). We own the intelligence (LLM, business logic, CRM). Each layer is independently replaceable.

### The Agent — Jaumpablo

Jaumpablo is an insurance sales agent for Quintana Seguros (pilot client). He:
- Speaks Rioplatense Spanish with natural voseo
- Knows the lead's name and car before the call starts
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
│   │   ├── prompts/            # Jaumpablo system prompt
│   │   ├── leads/              # Mock CRM — lead model + state machine
│   │   ├── tenants/            # Multi-tenant config (clients)
│   │   ├── calls/              # Call sessions + transcripts
│   │   ├── tools/              # Agent tools (register_interest, etc.)
│   │   └── static/             # Web demo frontend (index.html)
│   ├── tests/                  # 180 tests (unit + integration)
│   ├── pyproject.toml
│   ├── .env.example
│   └── README.md               # Backend setup guide
├── docs/
│   ├── architecture.md         # Detailed system architecture
│   ├── running-locally.md      # Step-by-step local setup
│   └── elevenlabs-reference.md # ElevenLabs API reference for this project
└── .sdd/                       # Spec-Driven Development artifacts
    ├── qora-prd/               # Product Requirements Document
    ├── qora-phase0/            # Phase 0 spec, design, tasks
    └── qora-cleanup/           # Cleanup phase spec, design, tasks
```

---

## Roadmap

### ✅ Phase 0 — MVP Demo (complete)
Core pipeline working. Web demo with real voice conversation.

### 🔲 Phase 1 — Multi-client Foundation
- Per-client configuration system (not hardcoded to Quintana Seguros)
- Knowledge base per client (product docs, FAQs, pricing)
- Multiple agents with data isolation
- Admin panel to manage clients

### 🔲 Phase 2 — Complete Orchestration
- Memory between calls (second call knows about the first)
- Call recording and full transcript persistence
- Post-conversation metrics and analysis
- Proper call lifecycle management

### 🔲 Phase 3 — Real Phone Calls
- Deploy to server (Railway/Render)
- Twilio integration for outbound calls
- Public webhook URLs (no more ngrok)
- First real call to a real phone number

### 🔲 Phase 4 — Sellable Product
- Client dashboard (metrics, leads, call history)
- Per-minute billing tracking
- Client onboarding flow
- n8n + Hume AI for post-call sentiment analysis

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
| Database | SQLite (→ PostgreSQL in Phase 3) |
| Testing | pytest + pytest-asyncio (180 tests) |
| Telephony | Twilio (Phase 3+) |
| Deploy | Railway/Render (Phase 3+) |

---

## What Makes This Different

Everyone can set up an ElevenLabs agent. What we're building is the **call center operations layer** on top:

- **Lead management** — who to call, when, how many times
- **Agent training** — the agent knows your specific product and handles your specific objections  
- **Results tracking** — conversion rate, sentiment, objection patterns
- **Scale** — 1 agent or 100, same cost per minute
- **No vendor lock-in** — swap ElevenLabs for another voice provider in one afternoon

---

*Built with [QORA](https://github.com/quintanamatias-dev/Qora) — Phase 0*
