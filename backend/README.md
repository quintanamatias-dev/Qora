# QORA — AI Call Center

QORA is an AI-powered outbound call center platform built on ElevenLabs Conversational AI and GPT-4o. It orchestrates real-time voice conversations between an AI insurance agent ("Jaumpablo") and leads — no Twilio, no Whisper, no VAD pipeline.

## What QORA Is

QORA connects ElevenLabs' voice agent directly to a Custom LLM webhook backed by GPT-4o. ElevenLabs handles speech-to-text, text-to-speech, and WebSocket transport. QORA provides:

- **Multi-tenant routing** — each client (`client_id`) has its own config in the database
- **Lead context injection** — lead data (name, car, current insurance) is injected into the system prompt at runtime
- **Tool execution** — GPT-4o can call CRM tools mid-conversation (register interest, mark not interested, schedule follow-up)
- **Dynamic filler system** — context-aware filler phrases emitted as first tokens to reduce perceived latency
- **Demo UI** — browser-based WebSocket demo at `/demo/`

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
                 │  POST /api/v1/voice/custom-llm
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
│  5. Stream GPT-4o via SSE       │
│  6. Handle tool calls           │
│  7. Persist transcript          │
└────────────┬────────────────────┘
             │
      ┌──────┴──────┐
      ▼             ▼
  GPT-4o         CRM Tools
  (OpenAI)       (DB ops)
```

## Prerequisites

- **Python 3.11+**
- **API Keys**: OpenAI, ElevenLabs
- **ngrok** (for exposing the local webhook to ElevenLabs)

## Setup

1. **Clone and navigate to backend**

   ```bash
   cd V1-CallCenter/backend
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
   cp .env.example .env
   # Edit .env and fill in your API keys
   ```

   | Variable | Description |
   |----------|-------------|
   | `OPENAI_API_KEY` | OpenAI API key — used for GPT-4o |
   | `ELEVENLABS_API_KEY` | ElevenLabs API key |
   | `ELEVENLABS_AGENT_ID` | Your ElevenLabs agent ID |
   | `DATABASE_URL` | SQLite path (default: `sqlite+aiosqlite:///./qora.db`) |

5. **Run the server**

   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

6. **Expose via ngrok** (required for ElevenLabs to reach your webhook)

   ```bash
   ngrok http 8000
   ```

   Configure your ElevenLabs agent's Custom LLM URL:

   **Recommended (path-based, multi-tenant):**
   `https://<your-ngrok-id>.ngrok-free.app/api/v1/voice/{client_id}/custom-llm`

   **Legacy (deprecated — use path-based route):**
   `https://<your-ngrok-id>.ngrok-free.app/api/v1/voice/custom-llm`

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/voice/signed-url` | Generate ElevenLabs signed WebSocket URL |
| POST | `/api/v1/voice/{client_id}/custom-llm/chat/completions` | **Path-based** multi-tenant Custom LLM webhook (recommended) |
| POST | `/api/v1/voice/custom-llm` | Legacy Custom LLM webhook (deprecated — use path-based route) |
| POST | `/api/v1/voice/custom-llm/chat/completions` | Legacy (ElevenLabs appends path — deprecated) |
| GET | `/api/v1/leads/{lead_id}` | Get lead details |
| GET | `/demo/` | Browser demo UI |
| GET | `/docs` | Swagger UI |

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
│   ├── main.py                  # FastAPI app, lifespan, DB init
│   ├── core/
│   │   ├── config.py            # pydantic-settings (env vars)
│   │   └── database.py          # SQLAlchemy async engine
│   ├── voice/
│   │   ├── webhook.py           # Custom LLM webhook (core of QORA)
│   │   ├── initiation.py        # Lead injection endpoint
│   │   └── filler.py            # Dynamic filler system
│   ├── prompts/
│   │   └── insurance_agent.py   # Jaumpablo system prompt renderer
│   ├── tenants/                 # Multi-tenant config (Client model + service)
│   ├── leads/                   # Lead CRM (Lead model + service + state machine)
│   ├── calls/                   # Call session tracking (transcript persistence)
│   ├── tools/                   # CRM tool implementations (GPT-4o function calls)
│   ├── ai/
│   │   └── llm_streaming.py     # OpenAI streaming client
│   └── static/
│       └── index.html           # Browser demo UI
├── tests/
│   ├── unit/                    # Unit tests per module
│   ├── integration/             # Integration tests (webhook, app wiring)
│   └── test_spec_coverage.py    # Spec scenario coverage matrix
├── .env.example
└── pyproject.toml
```

## License

MIT
