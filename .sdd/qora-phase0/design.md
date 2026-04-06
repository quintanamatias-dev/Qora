# Design: QORA Phase 0 — Local PoC

> **Change**: qora-phase0
> **Date**: 2026-04-05
> **Covers**: CAP-1 through CAP-8 from spec

---

## Technical Approach

Restructure `backend/app/` into a domain-driven layout. Reuse the existing SQLAlchemy async engine, structlog setup, and `OpenAIStreamingClient` — but rewrite models, routes, and prompts to match QORA's multi-tenant CRM-centric design. ElevenLabs sends full message context per turn; our webhook injects tenant config + lead context, streams GPT-4o via SSE, and handles tool calls mid-stream.

---

## Architecture Decisions

### AD-1: Filler Strategy — System Prompt Only (Option A)

| Option | Tradeoff | Decision |
|--------|----------|----------|
| A: Single GPT-4o call, prompt instructs fillers | Simpler, ~50ms slower first token, one model call | **CHOSEN** |
| B: GPT-4o-mini parallel filler + GPT-4o real | Complex stream merging, two API calls, race conditions | Rejected |

**Rationale**: GPT-4o first-token latency is ~200-300ms. The system prompt forces filler tokens first, so they stream almost immediately. The 500ms fallback timer (CAP-5) covers the edge case. Option B adds complexity for marginal gain — we can always upgrade later. ElevenLabs VAD keeps the audio flowing; we don't need sub-100ms tokens.

### AD-2: Project Structure — Domain Modules, Not Layers

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Domain modules (`tenants/`, `leads/`, `calls/`) | Feature cohesion, easy to find code | **CHOSEN** |
| Layer modules (`models/`, `services/`, `routes/`) | Familiar, but cross-cutting features split across dirs | Rejected |

**Rationale**: QORA has clear bounded contexts (tenants, leads, calls, voice). Domain modules keep model + service + router together per feature. Scales better for Phase 1+ multi-tenant additions.

### AD-3: In-Memory Session Store for Filler Tracking

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `dict[str, ConversationState]` in-memory | Fast, lost on crash, sufficient for PoC | **CHOSEN** |
| Redis | Over-engineered for Phase 0, adds infra | Rejected |
| SQLite per-turn | Too slow for filler dedup mid-stream | Rejected |

**Rationale**: Filler repetition tracking and per-turn state need <1ms access. In-memory dict keyed by `elevenlabs_conversation_id`. Call session data persists to SQLite on turn completion and call end. Crash = lost filler tracking only (acceptable for Phase 0).

### AD-4: Tool Calls — Intercept in SSE Stream

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Intercept `tool_calls` in stream, execute, re-call GPT-4o | Full control, matches OpenAI function calling | **CHOSEN** |
| Pre-execute tools before GPT-4o call | Requires predicting tool need — impossible | Rejected |

**Rationale**: GPT-4o returns `tool_calls` delta chunks in the stream. We accumulate them, execute the tool, append the tool result as a message, and make a second GPT-4o streaming call for the final response — all within the same SSE connection. The `OpenAIStreamingClient` must be extended to yield tool call deltas alongside content.

### AD-5: Reuse vs Rewrite Assessment

| Component | Action | Rationale |
|-----------|--------|-----------|
| `db/engine.py` | **REUSE** as-is | Async SQLAlchemy engine + session factory is exactly what we need |
| `ai/llm_streaming.py` | **EXTEND** | Add tool_calls delta handling; base streaming logic is solid |
| `config.py` (Settings) | **REWRITE** | Remove Twilio/VAD/STT fields; add QORA-specific fields |
| `db/models.py` | **REWRITE** | Current models are Twilio-centric; QORA needs leads, clients, call_sessions |
| `agents/prompts/insurance_agent.py` | **REWRITE** | Good starting point but needs template vars and filler instructions |
| `api/routes/elevenlabs_conversational.py` | **REWRITE** | Missing tenant routing, tool calls, lead injection, filler dedup |
| `main.py` | **REWRITE** | Lifespan needs new components; remove Twilio/VAD/STT init |
| Everything in `voice/`, `channels/`, `recording/` | **DELETE** | Twilio pipeline — not used in QORA Phase 0 |

---

## Directory Structure

```
backend/
├── app/
│   ├── main.py                     # FastAPI app, lifespan, router registration
│   ├── core/
│   │   ├── config.py               # Settings (pydantic-settings)
│   │   ├── db.py                   # Engine + session factory (reuse engine.py)
│   │   └── logging.py              # Structlog setup (extract from main.py)
│   ├── tenants/
│   │   ├── models.py               # Client SQLAlchemy model
│   │   ├── service.py              # Load tenant config, seed Quintana
│   │   └── router.py               # GET /api/v1/tenants/{id} (admin)
│   ├── leads/
│   │   ├── models.py               # Lead model + LeadStatus enum
│   │   ├── service.py              # CRUD, state machine, seed data
│   │   └── router.py               # GET/PATCH leads (admin/debug)
│   ├── calls/
│   │   ├── models.py               # CallSession + TranscriptTurn models
│   │   ├── service.py              # Create/update session, calc billable mins
│   │   └── router.py               # GET /api/v1/calls (admin)
│   ├── voice/
│   │   ├── webhook.py              # POST /api/v1/voice/custom-llm (main SSE endpoint)
│   │   ├── initiation.py           # POST /api/v1/voice/initiation (pre-call hook)
│   │   └── filler.py               # Filler dedup logic, fallback timer
│   ├── tools/
│   │   ├── registry.py             # Tool name → handler mapping
│   │   ├── get_lead_details.py     # Tool implementation
│   │   ├── register_interest.py    # Tool implementation
│   │   ├── mark_not_interested.py  # Tool implementation
│   │   └── schedule_followup.py    # Tool implementation
│   ├── prompts/
│   │   └── insurance_agent.py      # Jaumpablo template with filler instructions
│   └── ai/
│       └── llm_streaming.py        # Extended OpenAIStreamingClient (tool call support)
├── callcenter.db                   # SQLite (auto-created)
├── pyproject.toml
└── .env
```

---

## Database Schema

### clients

```sql
CREATE TABLE clients (
    id          TEXT PRIMARY KEY,            -- "quintana-seguros"
    name        TEXT NOT NULL,               -- "Quintana Seguros"
    broker_name TEXT NOT NULL,               -- "Quintana Seguros"
    agent_name  TEXT NOT NULL DEFAULT 'Jaumpablo',
    voice_id    TEXT NOT NULL,               -- ElevenLabs voice ID
    system_prompt_override TEXT,             -- NULL = use default template
    knowledge_base TEXT,                     -- FAQ/product info injected into prompt
    model       TEXT NOT NULL DEFAULT 'gpt-4o',
    temperature FLOAT NOT NULL DEFAULT 0.7,
    max_tokens  INTEGER NOT NULL DEFAULT 300,
    tools_enabled TEXT NOT NULL DEFAULT '["get_lead_details","register_interest","mark_not_interested","schedule_followup"]',  -- JSON array
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### leads

```sql
CREATE TABLE leads (
    id                TEXT PRIMARY KEY,      -- UUID
    client_id         TEXT NOT NULL REFERENCES clients(id),
    name              TEXT NOT NULL,
    phone             TEXT NOT NULL,
    car_make          TEXT,
    car_model         TEXT,
    car_year          INTEGER,
    current_insurance TEXT,
    status            TEXT NOT NULL DEFAULT 'new'
                      CHECK(status IN ('new','called','interested','not_interested','follow_up')),
    notes             TEXT,
    call_count        INTEGER NOT NULL DEFAULT 0,
    last_called_at    TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### call_sessions

```sql
CREATE TABLE call_sessions (
    id                          TEXT PRIMARY KEY,  -- UUID
    client_id                   TEXT NOT NULL REFERENCES clients(id),
    lead_id                     TEXT NOT NULL REFERENCES leads(id),
    elevenlabs_conversation_id  TEXT,
    status                      TEXT NOT NULL DEFAULT 'initiated'
                                CHECK(status IN ('initiated','in_progress','completed','abandoned','failed')),
    started_at                  TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at                    TEXT,
    duration_seconds            REAL,
    billable_minutes            INTEGER,
    outcome                     TEXT CHECK(outcome IN ('completed','abandoned','failed')),
    created_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### transcript_turns

```sql
CREATE TABLE transcript_turns (
    id              TEXT PRIMARY KEY,  -- UUID
    session_id      TEXT NOT NULL REFERENCES call_sessions(id),
    role            TEXT NOT NULL CHECK(role IN ('user','agent','tool')),
    content         TEXT NOT NULL,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    filler_detected INTEGER NOT NULL DEFAULT 0
);
```

---

## Data Flow — Custom LLM Webhook (CAP-1)

```
ElevenLabs POST /api/v1/voice/custom-llm
    │
    ▼
┌─────────────────────────────────────┐
│ 1. Parse request, extract           │
│    client_id + lead_id from         │
│    elevenlabs_extra_body            │
│    → 422 if missing client_id       │
│    → 404 if unknown client          │
├─────────────────────────────────────┤
│ 2. Load tenant config (clients DB)  │
│    → system_prompt, model, tools    │
├─────────────────────────────────────┤
│ 3. Load lead context (leads DB)     │
│    → Inject into system prompt vars │
├─────────────────────────────────────┤
│ 4. Load filler state (in-memory)    │
│    → last_filler for dedup          │
├─────────────────────────────────────┤
│ 5. Start SSE stream response        │
│    ┌──────────────────────────┐     │
│    │ 5a. Start 500ms timer    │     │
│    │ 5b. Call GPT-4o stream   │     │
│    │                          │     │
│    │ IF timer fires first:    │     │
│    │   → emit fallback filler │     │
│    │ ELSE first token arrives:│     │
│    │   → cancel timer         │     │
│    │   → stream tokens        │     │
│    │                          │     │
│    │ IF tool_call detected:   │     │
│    │   → accumulate tool call │     │
│    │   → execute tool         │     │
│    │   → 2nd GPT-4o call      │     │
│    │   → stream final reply   │     │
│    └──────────────────────────┘     │
├─────────────────────────────────────┤
│ 6. Persist: transcript turn to DB   │
│    Update filler state in memory    │
│ 7. Emit data: [DONE]               │
└─────────────────────────────────────┘
```

## Data Flow — Initiation Webhook (CAP-2)

```
ElevenLabs POST /api/v1/voice/initiation
    │
    ├── Extract lead_id
    ├── Fetch lead from SQLite
    ├── Create call_session record (status=initiated)
    ├── Set lead status → "called"
    └── Return { dynamic_variables: { lead_name, car_make, ... } }
```

## Data Flow — Tool Execution Mid-Stream (CAP-4)

```
GPT-4o stream → yields tool_calls delta chunks
    │
    ├── Accumulate: function name + arguments JSON
    ├── Stream ends with finish_reason="tool_calls"
    │
    ├── Execute tool via registry.py:
    │   tools_map = {
    │       "get_lead_details": get_lead_details_handler,
    │       "register_interest": register_interest_handler,
    │       ...
    │   }
    │
    ├── Build messages: original + assistant(tool_calls) + tool(result)
    ├── Second GPT-4o streaming call
    └── Stream final response tokens via SSE
```

---

## Interfaces / Contracts

### Tool Definitions (OpenAI function calling format)

```python
QORA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_lead_details",
            "description": "Get full lead info from CRM",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"}
                },
                "required": ["lead_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "register_interest",
            "description": "Register lead interest and mark for quoting",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "string"},
                    "car_make": {"type": "string"},
                    "car_model": {"type": "string"},
                    "car_year": {"type": "integer"},
                    "current_insurance": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["lead_id", "car_make", "car_model", "car_year"]
            }
        }
    },
    # mark_not_interested(lead_id, reason)
    # schedule_followup(lead_id, followup_date, note?)
]
```

### In-Memory Conversation State

```python
@dataclass
class ConversationState:
    conversation_id: str
    client_id: str
    lead_id: str
    session_id: str          # call_sessions.id
    last_filler: str | None  # for dedup
    turn_count: int
    started_at: float        # monotonic time

# Global store: dict[str, ConversationState]
# Key = elevenlabs_conversation_id
```

---

## Seed Data — 5 Test Leads (CAP-3)

| Name | Phone | Car | Status | Notes |
|------|-------|-----|--------|-------|
| Carlos Méndez | +5411155501 | Toyota Corolla 2021 | `new` | Pidió cotización por web |
| María López | +5411155502 | VW Golf 2019 | `new` | Referida por cliente existente |
| Juan Pérez | +5411155503 | Ford Ranger 2022 | `called` | Llamado una vez, no atendió |
| Ana García | +5411155504 | Fiat Cronos 2023 | `interested` | Quiere todo riesgo |
| Roberto Silva | +5411155505 | Chevrolet Cruze 2020 | `not_interested` | Tiene seguro reciente |

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/core/config.py` | Create | QORA Settings: OpenAI key, ElevenLabs key, DB URL, defaults |
| `app/core/db.py` | Create | Reuse engine.py logic — async engine + session factory |
| `app/core/logging.py` | Create | Extract structlog setup from current main.py |
| `app/tenants/models.py` | Create | Client SQLAlchemy model |
| `app/tenants/service.py` | Create | Load config, seed Quintana |
| `app/leads/models.py` | Create | Lead model + LeadStatus enum + state machine |
| `app/leads/service.py` | Create | CRUD + state transitions + seed data |
| `app/calls/models.py` | Create | CallSession + TranscriptTurn models |
| `app/calls/service.py` | Create | Session lifecycle + billable minutes |
| `app/voice/webhook.py` | Create | SSE Custom LLM endpoint with tenant routing |
| `app/voice/initiation.py` | Create | Pre-call webhook with dynamic_variables |
| `app/voice/filler.py` | Create | Filler dedup + 500ms fallback timer |
| `app/tools/registry.py` | Create | Tool dispatcher mapping |
| `app/tools/get_lead_details.py` | Create | Tool handler |
| `app/tools/register_interest.py` | Create | Tool handler |
| `app/tools/mark_not_interested.py` | Create | Tool handler |
| `app/tools/schedule_followup.py` | Create | Tool handler |
| `app/prompts/insurance_agent.py` | Create | Jaumpablo template with filler + tool rules |
| `app/ai/llm_streaming.py` | Modify | Add tool_calls delta accumulation + yield |
| `app/main.py` | Rewrite | New lifespan: DB init, seed data, minimal startup |
| `app/voice/`, `app/channels/`, `app/recording/` (old) | Delete | Twilio pipeline not used |
| `app/agents/` (old) | Delete | Replaced by tenants/ + tools/ + prompts/ |

---

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Lead state machine transitions (valid + invalid) | pytest — no DB needed, pure logic |
| Unit | Filler dedup logic | pytest — in-memory state |
| Unit | Tool execution handlers | pytest + SQLite in-memory |
| Integration | Custom LLM webhook end-to-end | pytest + httpx AsyncClient, mock OpenAI |
| Integration | Initiation webhook → creates session + returns vars | pytest + httpx AsyncClient |
| Manual | Full conversation via ElevenLabs demo page | ngrok + browser + ElevenLabs agent |

---

## Migration / Rollout

No migration required. Phase 0 is greenfield — new SQLite DB created on startup. Old `callcenter.db` is not reused. Existing V1-CallCenter code stays untouched in git history; QORA builds in the same repo but replaces the active application.

---

## Open Questions

- [x] Filler strategy: **Resolved → Option A (system prompt only)**
- [ ] Should old V1 code be kept in a separate branch or deleted from `main`? (Does not block Phase 0)
- [ ] ElevenLabs Conversational AI agent_id — do we create a new one or reuse existing? (Config question, not code)
