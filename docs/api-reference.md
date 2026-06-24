# API Reference

All endpoints are prefixed with `/api/v1`. The base URL is `http://localhost:8000` in local development.

Interactive documentation is available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Authentication

Qora uses three distinct auth layers depending on the endpoint group.

### Admin Bearer auth

All admin API routes require an `Authorization: Bearer` header with the value of `QORA_API_KEY`.

```bash
curl -H "Authorization: Bearer <QORA_API_KEY>" http://localhost:8000/api/v1/clients
```

**401 behavior** — any missing, malformed, or wrong key returns:

```json
{ "error": "authentication_required", "message": "..." }
```

If `QORA_API_KEY` is not set in `.env`, all protected routes deny every request (fail-closed).

> **Note on `VITE_API_KEY`**: The React frontend sends this key from the browser as a convenience for the current Phase B static admin auth model. It is intentionally browser-visible and acceptable only at this development stage. It will be replaced by a proper JWT login flow in Phase C — do not build new features that rely on browser-side API key access.

### Voice / ElevenLabs webhook routes

Voice endpoints (`/api/v1/voice/*`) are called by ElevenLabs — not by browser users — so they use a separate shared-secret mechanism instead of Bearer auth.

By default, webhook auth is **disabled**. To enable it (optional, recommended for production):

1. Set `QORA_WEBHOOK_SECRET=<strong-random-value>` in `.env`.
2. Add the same value as `X-Webhook-Secret` in the ElevenLabs agent's security settings.
3. Set `QORA_WEBHOOK_AUTH_ENABLED=true` and restart.

When enabled, every voice webhook request must include:

```
X-Webhook-Secret: <QORA_WEBHOOK_SECRET>
```

Missing or wrong secrets return `401`.

> **Startup guard**: If `QORA_WEBHOOK_AUTH_ENABLED=true` but `QORA_WEBHOOK_SECRET` is absent or empty, the application **refuses to start** with a configuration error. This prevents silently open webhook surfaces.

### Demo / public routes

The `/api/v1/demo/*` routes are intentionally auth-exempt. They are scoped server-side to `QORA_DEMO_CLIENT_ID` and never expose admin keys or cross-tenant data. The demo flow is: browser calls `/demo/context` → `/demo/leads` → ElevenLabs WebSocket → `POST /demo/sessions/{id}/end`.

### Endpoint auth summary

| Group | Auth required | Mechanism |
|-------|--------------|-----------|
| Admin routes (clients, agents, leads, calls, scheduler, analytics) | ✅ | `Authorization: Bearer <QORA_API_KEY>` |
| Voice webhooks (initiation, custom-LLM, post-call) | Optional | `X-Webhook-Secret` (when `QORA_WEBHOOK_AUTH_ENABLED=true`) |
| Demo routes (`/api/v1/demo/*`) | None | Public — scoped to demo client server-side |
| Health check (`/api/v1/health`) | None | Public |
| Signed URL (`/api/v1/voice/signed-url`) | None | Public — generates ElevenLabs WebSocket URL |
| Docs (`/docs`, `/redoc`) | None | Public — disable with `QORA_DOCS_ENABLED=false` in production |

### CORS

The backend uses `QORA_ALLOWED_ORIGINS` to control which browser origins can call the API.

| Setting | Behavior |
|---------|----------|
| `QORA_ALLOWED_ORIGINS=*` (default) | All origins allowed — safe for local development |
| `QORA_ALLOWED_ORIGINS=https://app.example.com` | Only that origin allowed |
| Multiple origins | Comma-separated: `https://a.com,https://b.com` |

In production, always set an explicit allow-list to prevent unauthorized browser clients from calling admin endpoints.

---

## Table of Contents

1. [All Endpoints — Quick Reference](#1-all-endpoints--quick-reference)
2. [Meta](#2-meta)
3. [Voice](#3-voice)
4. [Demo](#4-demo)
5. [Calls](#5-calls)
6. [Analytics](#6-analytics)
7. [Clients](#7-clients)
8. [Agents](#8-agents)
9. [Leads](#9-leads)
10. [Scheduler](#10-scheduler)
11. [Static Pages](#11-static-pages)

---

## 1. All Endpoints — Quick Reference

### Voice

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/voice/signed-url` | Public | Generate ElevenLabs signed WebSocket URL |
| POST | `/api/v1/voice/{client_id}/custom-llm/chat/completions` | Webhook secret (optional) | Multi-tenant Custom LLM webhook (primary) |
| POST | `/api/v1/voice/custom-llm` | Webhook secret (optional) | Legacy Custom LLM webhook (deprecated) |
| POST | `/api/v1/voice/initiation` | Webhook secret (optional) | Call initiation webhook — injects lead context |

### Demo

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/demo/context` | Public | Demo agent metadata (safe for browser) |
| GET | `/api/v1/demo/leads` | Public | Leads scoped to the demo client |
| POST | `/api/v1/demo/sessions/{id}/end` | Public | Close a demo call session (demo-scoped) |

### Calls

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/calls` | Bearer | List call sessions for a client |
| GET | `/api/v1/calls/metrics` | Bearer | Aggregated call metrics |
| GET | `/api/v1/calls/{session_id}` | Bearer | Get a single call session |
| GET | `/api/v1/calls/{session_id}/transcript` | Bearer | Get all transcript turns |
| POST | `/api/v1/calls/{conversation_id}/end` | Bearer | Close a call session (idempotent) |
| POST | `/api/v1/calls/elevenlabs-postcall` | Webhook secret (optional) | ElevenLabs post-call webhook |

### Analytics

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/analytics/{client_id}/overview` | Bearer | Aggregated metrics for a period |
| GET | `/api/v1/analytics/{client_id}/service-issues` | Bearer | Ranked service issue breakdown |
| GET | `/api/v1/analytics/{client_id}/interests` | Bearer | Top interests with trend direction |
| GET | `/api/v1/analytics/{client_id}/agent-stats` | Bearer | Per-agent call statistics |

### Clients

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/clients` | Bearer | Create a new client (tenant) |
| GET | `/api/v1/clients` | Bearer | List all active clients |
| GET | `/api/v1/clients/{client_id}` | Bearer | Get a single client |
| PATCH | `/api/v1/clients/{client_id}` | Bearer | Partial update |
| DELETE | `/api/v1/clients/{client_id}` | Bearer | Soft delete (sets `is_active=False`) |
| GET | `/api/v1/tenants/{client_id}` | Bearer | Read-only alias for GET `/clients/{client_id}` (deprecated) |

### Agents

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/clients/{client_id}/agents` | Bearer | Create a new agent |
| GET | `/api/v1/clients/{client_id}/agents` | Bearer | List active agents for a client |
| GET | `/api/v1/clients/{client_id}/agents/{agent_id}` | Bearer | Get a single agent |
| PATCH | `/api/v1/clients/{client_id}/agents/{agent_id}` | Bearer | Partial update |
| POST | `/api/v1/clients/{client_id}/agents/{agent_id}/deactivate` | Bearer | Soft delete agent |
| POST | `/api/v1/clients/{client_id}/agents/{agent_id}/make-default` | Bearer | Atomically swap default agent |

### Leads

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/v1/leads` | Bearer | List leads for a client |
| GET | `/api/v1/leads/{lead_id}` | Bearer | Get lead details + extracted facts |
| POST | `/api/v1/leads` | Bearer | Create a new lead |
| PATCH | `/api/v1/leads/{lead_id}/status` | Bearer | Transition lead status (state machine) |
| GET | `/api/v1/leads/{lead_id}/history` | Bearer | Call session history for a lead |

### Scheduler

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/api/v1/scheduler/{client_id}/queue` | Bearer | Create manual scheduled call |
| GET | `/api/v1/scheduler/{client_id}/queue` | Bearer | List scheduled calls (filterable) |
| GET | `/api/v1/scheduler/{client_id}/queue/{id}` | Bearer | Get a single scheduled call |
| POST | `/api/v1/scheduler/{client_id}/queue/{id}/cancel` | Bearer | Cancel a pending call |
| PATCH | `/api/v1/scheduler/{client_id}/queue/{id}` | Bearer | Reschedule a pending call |
| PATCH | `/api/v1/clients/{client_id}/scheduled-calls/{id}/complete` | Bearer | Mark a scheduled call as completed |

---

## 2. Meta — `/api/v1/health` (public)

### `GET /api/v1/health`

Returns service health status and uptime.

**Response 200**:
```json
{
  "status": "healthy",
  "uptime_seconds": 3600.1,
  "version": "0.1.0"
}
```

---

## 3. Voice (webhook secret optional)

### `GET /api/v1/voice/signed-url`

Generates an ElevenLabs signed WebSocket URL for the demo UI. Using a signed URL forces WebSocket transport (not WebRTC) regardless of ElevenLabs agent settings.

**Response 200**:
```json
{
  "signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?agent_id=...&token=..."
}
```

---

### `POST /api/v1/voice/{client_id}/custom-llm/chat/completions`

**Primary** Custom LLM webhook. ElevenLabs posts here on every conversational turn. Returns an OpenAI-compatible Server-Sent Events (SSE) stream.

**What this endpoint does**:
1. Validates `client_id` and loads the tenant's default active agent.
2. Extracts `lead_id` from `elevenlabs_extra_body` (optional).
3. Renders the system prompt with lead context, memory, and skills index.
4. Streams GPT-4o via SSE, intercepting tool calls.
5. Persists each agent turn to `transcript_turns`.

**Path parameter**: `client_id` — tenant slug (e.g. `quintana-seguros`)

**Request body** (OpenAI-compatible):
```json
{
  "model": "gpt-4o",
  "messages": [
    { "role": "user", "content": "Hola, me llamo Juan" }
  ],
  "stream": true,
  "elevenlabs_extra_body": {
    "client_id": "quintana-seguros",
    "lead_id": "lead-uuid-here"
  }
}
```

**Response**: SSE stream with OpenAI-compatible `data:` chunks, terminated by `data: [DONE]`.

**Errors**:

| Code | Reason |
|------|--------|
| `422` | `client_id` missing from `elevenlabs_extra_body` |
| `404` | Client not found |
| `403` | Client is inactive |

---

### `POST /api/v1/voice/custom-llm` (legacy)

Also available at:
- `POST /api/v1/voice/custom-llm/chat/completions`
- `POST /api/v1/voice/chat/completions`

Legacy Custom LLM webhook routes. Extract `client_id` from `elevenlabs_extra_body` (or top-level field / `model_extra`) instead of the URL path. **Deprecated** — use the path-based route above. Every call emits a `custom_llm_legacy_route_used` warning log.

---

### `POST /api/v1/voice/initiation`

ElevenLabs call initiation webhook. Called by ElevenLabs at the start of a new conversation, before the first turn. Qora uses this to inject lead context as dynamic variables and to create the `CallSession` record.

**Request body** (all fields optional — `client_id`/`lead_id` can also be query params):
```json
{
  "client_id": "quintana-seguros",
  "lead_id": "lead-uuid",
  "conversation_id": "conv_xxxx",
  "agent_id": "agent_xxxx",
  "called_number": "+54911234567"
}
```

**Response 200**:
```json
{
  "type": "conversation_initiation_client_data",
  "dynamic_variables": {
    "lead_name": "Juan Pérez",
    "car_make": "Toyota",
    "is_returning_caller": true,
    "call_history": "...",
    "confirmed_facts": "..."
  }
}
```

---

## 4. Demo (public — no auth required)

Demo endpoints are served by the `/api/v1/demo/` router. They are intentionally auth-exempt and safe to call from a browser. Identity is resolved server-side from `QORA_DEMO_CLIENT_ID` — the browser never sends or receives admin credentials.

### `GET /api/v1/demo/context`

Returns safe metadata for the demo flow — no secrets, no cross-tenant data.

**Response 200**:
```json
{
  "elevenlabs_agent_id": "agent_xxxx",
  "client_name": "Acme Demo",
  "agent_name": "Sofia",
  "demo_client_id": "acme-demo"
}
```

**Response 503**: `QORA_DEMO_CLIENT_ID` or `QORA_DEMO_AGENT_ID` not configured.

---

### `GET /api/v1/demo/leads`

Returns leads scoped to the demo client. Cross-tenant access is impossible — `client_id` comes from server config, not from user input.

**Response 200**: Array of lead objects (id, name, status, phone, notes, client_id, custom_fields).

**Response 503**: `QORA_DEMO_CLIENT_ID` not configured.

---

### `POST /api/v1/demo/sessions/{session_id}/end`

Close a demo call session. Scoped to the configured demo client — attempts to close sessions belonging to other tenants return `403`.

**Request body**:
```json
{ "reason": "user_hangup", "conversation_id": null, "client_id": null, "lead_id": null }
```

**Response 200**:
```json
{ "id": "session-uuid", "status": "completed", "duration_seconds": 120.0, "closed_reason": "user_hangup" }
```

**Response 403**: Session belongs to a different tenant.

**Response 404**: Session not found.

---

## 5. Calls (Bearer auth required)

### `GET /api/v1/calls`

List all call sessions for a client.

**Query parameters**:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | ✅ | Tenant client ID |
| `lead_id` | — | Filter by specific lead |

Returns sessions ordered by `started_at` DESC. Ghost sessions (status=`initiated`, no turns, no duration) are filtered out.

**Response 200**:
```json
[
  {
    "id": "session-uuid",
    "client_id": "quintana-seguros",
    "lead_id": "lead-uuid",
    "status": "completed",
    "outcome": null,
    "closed_reason": "user_closed",
    "started_at": "2025-04-15T14:30:00Z",
    "ended_at": "2025-04-15T14:35:22Z",
    "duration_seconds": 322.5,
    "billable_minutes": 6,
    "total_user_turns": 12,
    "total_agent_turns": 12,
    "summary": "El lead mostró interés en seguro de auto...",
    "extracted_facts": { "interest_level": 72, "call_outcome": { "..." } },
    "merged_into_session_id": null
  }
]
```

---

### `GET /api/v1/calls/metrics`

Returns aggregated call metrics for a client.

**Query parameters**:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | ✅ | Tenant client ID |
| `lead_id` | — | Filter to a specific lead |
| `date_from` | — | ISO 8601 datetime lower bound (inclusive) |
| `date_to` | — | ISO 8601 datetime upper bound (inclusive) |

**Response 200**:
```json
{
  "total_calls": 48,
  "completed_calls": 41,
  "avg_duration_seconds": 287.3,
  "period": {
    "date_from": null,
    "date_to": null
  }
}
```

---

### `GET /api/v1/calls/{session_id}`

Get a single call session by ID.

**Response 200**: Full call session object (same structure as list, plus `elevenlabs_conversation_id`).

**Response 404**: Session not found.

---

### `GET /api/v1/calls/{session_id}/transcript`

Get all transcript turns for a call session.

**Response 200**:
```json
{
  "session_id": "session-uuid",
  "turn_count": 24,
  "turns": [
    {
      "id": "turn-uuid",
      "role": "user",
      "content": "Hola, me llamo Juan",
      "timestamp": "2025-04-15T14:30:05Z",
      "filler_detected": false
    },
    {
      "id": "turn-uuid-2",
      "role": "agent",
      "content": "Hola Juan, soy Jaumpablo...",
      "timestamp": "2025-04-15T14:30:08Z",
      "filler_detected": false
    }
  ]
}
```

---

### `POST /api/v1/calls/{conversation_id}/end`

Close a call session. The path parameter is the ElevenLabs `conversation_id`.

**Idempotent**: if the session is already completed, returns `200` without double-incrementing `Lead.call_count`.

**What this does**:
- Sets `status="completed"`, `ended_at`, `duration_seconds`, `billable_minutes`, `closed_reason`
- Increments `Lead.call_count` and `Lead.last_called_at` on first close only
- Triggers the post-call analysis summarizer asynchronously

**Request body**:
```json
{
  "reason": "user_closed",
  "client_id": "quintana-seguros",
  "lead_id": "lead-uuid",
  "conversation_id": "conv_xxxx"
}
```

**Response 200**:
```json
{
  "id": "session-uuid",
  "status": "completed",
  "duration_seconds": 322.5,
  "closed_reason": "user_closed"
}
```

**Response 404**: Session not found.

---

### `POST /api/v1/calls/elevenlabs-postcall`

ElevenLabs post-call webhook. Called by ElevenLabs after every conversation ends.

**Handles two cases**:
- **Session was `initiated`** (never closed by frontend): closes it with `reason="network_drop"` and increments lead counters.
- **Session was `completed`**: merges any extra transcript turns ElevenLabs has that aren't in the DB yet. If turns were merged, re-triggers the summarizer.

**Request body** (ElevenLabs post-call payload):
```json
{
  "conversation_id": "conv_xxxx",
  "agent_id": "agent_xxxx",
  "transcript": [
    { "role": "user", "message": "Hola" },
    { "role": "agent", "message": "Hola, soy Jaumpablo..." }
  ]
}
```

**Response 200**:
```json
{ "status": "ok", "session_id": "session-uuid" }
```

**Response 404**: No session found for the given `conversation_id`.

---

## 6. Analytics (Bearer auth required)

All analytics endpoints share the same query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `month` | One of: `day`, `week`, `month`, `custom` |
| `start_date` | date | — | Required when `period=custom` (ISO 8601, e.g. `2025-04-01`) |
| `end_date` | date | — | Required when `period=custom` |
| `agent_id` | string | — | Filter to a specific agent |

**Common errors**:
- `400` — invalid period value, or `custom` period without `start_date`/`end_date`
- `404` — client not found

---

### `GET /api/v1/analytics/{client_id}/overview`

Returns aggregated call metrics for the period.

**Response 200**:
```json
{
  "total_calls": 120,
  "completed_calls": 98,
  "avg_interest_level": 54.3,
  "outcome_breakdown": {
    "completed_positive": 22,
    "completed_neutral": 38,
    "completed_negative": 18,
    "no_answer": 12,
    "busy": 8,
    "callback_requested": 15,
    "do_not_contact": 2,
    "hostile": 1,
    "other": 4
  },
  "next_action_breakdown": {
    "follow_up": 35,
    "retry_call": 20,
    "schedule_call": 15,
    "close_lead": 21,
    "human_review": 7
  },
  "period": "month",
  "start_date": "2025-04-01",
  "end_date": "2025-04-30",
  "agent_id": null
}
```

---

### `GET /api/v1/analytics/{client_id}/service-issues`

Returns ranked service issues extracted from calls in the period.

**Response 200**:
```json
{
  "issues": [
    {
      "category": "delay",
      "count": 12,
      "pct": 28.5,
      "source_breakdown": {
        "current_provider": 8,
        "previous_provider": 3,
        "our_company": 1
      }
    }
  ],
  "period": "month",
  "start_date": "2025-04-01",
  "end_date": "2025-04-30",
  "agent_id": null
}
```

---

### `GET /api/v1/analytics/{client_id}/interests`

Returns top interests with trend direction (up/down/flat) compared to the previous period.

**Response 200**:
```json
{
  "interests": [
    {
      "product": "auto",
      "count": 45,
      "avg_score": 68.2,
      "trend": "up"
    },
    {
      "product": "vida",
      "count": 22,
      "avg_score": 52.1,
      "trend": "flat"
    }
  ],
  "period": "month",
  "start_date": "2025-04-01",
  "end_date": "2025-04-30",
  "agent_id": null
}
```

---

### `GET /api/v1/analytics/{client_id}/agent-stats`

Returns per-agent call statistics for the period.

**Response 200**:
```json
{
  "agents": [
    {
      "agent_id": "agent-uuid",
      "agent_name": "Jaumpablo",
      "total_calls": 98,
      "completed_calls": 82,
      "avg_duration_seconds": 295.1,
      "avg_interest_level": 56.8
    }
  ],
  "period": "month",
  "start_date": "2025-04-01",
  "end_date": "2025-04-30"
}
```

---

## 7. Clients (Bearer auth required)

### `POST /api/v1/clients`

Create a new client (tenant). Automatically bootstraps a default `Agent` for the new client.

When `client_id` is omitted, a URL-safe slug is auto-generated from `name` (e.g. `"Acme Corp"` → `"acme-corp"`). Collisions are resolved by appending `-2`, `-3`, etc.

**Request body** (only `name` is required):
```json
{
  "name": "Acme Corp",
  "client_id": "acme-corp",
  "agent_name": "Sofia",
  "voice_id": "voice_xxxx",
  "system_prompt_override": null,
  "scheduler_enabled": true,
  "scheduler_max_attempts": 5,
  "scheduler_cooldown_minutes": 60,
  "scheduler_allowed_hours_start": 9,
  "scheduler_allowed_hours_end": 20,
  "scheduler_retry_on_outcomes": ["no_answer", "busy"],
  "scheduler_timezone": "America/Argentina/Buenos_Aires"
}
```

**Response 201**: `ClientResponse` object.

**Response 409**: `client_id` or `name` already exists.

---

### `GET /api/v1/clients`

List all active clients (where `is_active=True`).

**Response 200**:
```json
[
  {
    "client_id": "quintana-seguros",
    "name": "Quintana Seguros",
    "agent_name": "Jaumpablo",
    "voice_id": "voice_xxxx",
    "is_active": true,
    "created_at": "2025-01-01T00:00:00Z",
    "agent_count": 1,
    "scheduler_enabled": true,
    "scheduler_max_attempts": 5,
    "scheduler_cooldown_minutes": 60,
    "scheduler_allowed_hours_start": 9,
    "scheduler_allowed_hours_end": 20,
    "scheduler_retry_on_outcomes": ["no_answer", "busy"],
    "scheduler_timezone": "America/Argentina/Buenos_Aires"
  }
]
```

---

### `GET /api/v1/clients/{client_id}`

Get a single client by ID.

**Response 200**: `ClientResponse` object.

**Response 404**: Client not found.

---

### `PATCH /api/v1/clients/{client_id}`

Partially update a client. Only provided fields are updated. `client_id` is NOT updatable.

**Request body** (all fields optional):
```json
{
  "name": "Acme Corp Renovado",
  "agent_name": "Sofia",
  "voice_id": "new_voice_id",
  "scheduler_enabled": false,
  "scheduler_allowed_hours_start": 10,
  "scheduler_allowed_hours_end": 18
}
```

Validates that `scheduler_allowed_hours_start < scheduler_allowed_hours_end` after merging with existing values.

**Response 200**: Updated `ClientResponse`.

**Response 404**: Client not found.

**Response 422**: Invalid hour window (`start >= end`).

---

### `DELETE /api/v1/clients/{client_id}`

Soft-delete a client (sets `is_active=False`). The record is **not** removed from the database. Associated leads, sessions, and agents remain intact.

Inactive clients receive `403 Forbidden` on any webhook call.

**Response 200**: `ClientResponse` with `is_active=false`.

**Response 404**: Client not found.

---

### `GET /api/v1/tenants/{client_id}` (deprecated)

Read-only backward-compatibility alias for `GET /api/v1/clients/{client_id}`. Returns basic tenant configuration fields. New integrations should use `/clients` routes instead.

**Response 200**:
```json
{
  "id": "quintana-seguros",
  "name": "Quintana Seguros",
  "name": "Quintana",
  "agent_name": "Nico",
  "voice_id": "...",
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 300,
  "tools_enabled": "[\"get_lead_details\"]",
  "is_active": true,
  "created_at": "2025-01-01T00:00:00Z"
}
```

**Response 404**: Client not found.

---

## 8. Agents (Bearer auth required)

All agent endpoints are nested under `/api/v1/clients/{client_id}/agents`.

### `GET /api/v1/clients/{client_id}/agents`

List all active agents for a client.

**Response 200**:
```json
[
  {
    "agent_id": "agent-uuid",
    "client_id": "quintana-seguros",
    "slug": "jaumpablo",
    "name": "Jaumpablo",
    "voice_id": "voice_xxxx",
    "system_prompt": null,
    "knowledge_base": null,
    "model": "gpt-4o",
    "temperature": 0.7,
    "max_tokens": 300,
    "tools_enabled": ["get_lead_details", "register_interest"],
    "is_active": true,
    "is_default": true,
    "created_at": "2025-01-01T00:00:00Z",
    "elevenlabs_agent_id": "agent_xxxx",
    "custom_llm_url": "/api/v1/voice/quintana-seguros/custom-llm/chat/completions",
    "has_prompt": false,
    "has_elevenlabs_agent_id": true,
    "is_conversation_ready": false,
    "tts_speed": 0.95,
    "tts_stability": 0.60,
    "tts_similarity_boost": 0.75
  }
]
```

**Response 404**: Client not found.

---

### `POST /api/v1/clients/{client_id}/agents`

Create a new agent for a client. Only `slug` and `name` are required.

**Request body**:
```json
{
  "slug": "sofia",
  "name": "Sofia",
  "voice_id": "voice_xxxx",
  "system_prompt": null,
  "knowledge_base": null,
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 300,
  "tools_enabled": ["get_lead_details"],
  "is_default": false,
  "elevenlabs_agent_id": null,
  "tts_speed": 0.95,
  "tts_stability": 0.50,
  "tts_similarity_boost": 0.75
}
```

**Response 201**: `AgentResponse` object.

**Response 404**: Client not found.

**Response 409**: Slug already exists for this client, or `is_default` conflict.

---

### `GET /api/v1/clients/{client_id}/agents/{agent_id}`

Get a single agent by ID.

**Response 200**: `AgentResponse` object.

**Response 404**: Client or agent not found.

---

### `PATCH /api/v1/clients/{client_id}/agents/{agent_id}`

Partially update an agent. Only provided fields are updated.

**Request body** (all fields optional):
```json
{
  "name": "Sofia v2",
  "voice_id": "new_voice_id",
  "tts_stability": 0.65,
  "elevenlabs_agent_id": "agent_xxxx",
  "tools_enabled": ["get_lead_details", "register_interest", "load_skill"]
}
```

**Response 200**: Updated `AgentResponse`.

**Response 404**: Client or agent not found.

---

### `POST /api/v1/clients/{client_id}/agents/{agent_id}/deactivate`

Soft-delete an agent (sets `is_active=False`).

**Response 200**: `AgentResponse` with `is_active=false`.

**Response 404**: Agent not found.

**Response 409**: Cannot deactivate the sole active default agent for a client.

---

### `POST /api/v1/clients/{client_id}/agents/{agent_id}/make-default`

Atomically swap the default agent. Sets `agent_id` as default, unsets all other agents' `is_default`.

**Response 200**: `AgentResponse` with `is_default=true`.

**Response 404**: Agent not found.

**Response 409**: Cannot set an inactive agent as default.

---

## 9. Leads (Bearer auth required)

### `GET /api/v1/leads`

List leads for a client.

**Query parameters**:

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | ✅ | Tenant client ID to scope results |

**Response 200**: Array of lead objects with CRM fields, profile facts, interest history, and next scheduled call time.

---

### `GET /api/v1/leads/{lead_id}`

Get a single lead by ID. Includes full `extracted_facts`, active `profile_facts`, and `interest_history`.

**Response 200**:
```json
{
  "id": "lead-uuid",
  "client_id": "quintana-seguros",
  "name": "Juan Pérez",
  "phone": "+54911234567",
  "email": null,
  "age": null,
  "car_make": "Toyota",
  "car_model": "Corolla",
  "car_year": 2019,
  "current_insurance": "Mapfre",
  "status": "called",
  "notes": null,
  "call_count": 3,
  "last_called_at": "2025-04-30T14:35:22Z",
  "interest_level": 72,
  "objections_heard": ["price", "current_provider"],
  "summary_last_call": "El lead mostró interés pero quiere comparar precios.",
  "do_not_call": false,
  "next_action": "follow_up",
  "next_action_at": "2025-05-05T10:00:00Z",
  "extracted_facts": { "..." },
  "profile_facts": [
    {
      "fact_key": "profile:decision_style",
      "fact_value": "{\"category\": \"decision_style\", \"fact\": \"Consulta con su esposa antes de decidir\"}",
      "recorded_at": "2025-04-30T14:40:00Z"
    }
  ],
  "interest_history": [
    { "interest_level": 30, "recorded_at": "2025-04-01T10:00:00Z" },
    { "interest_level": 55, "recorded_at": "2025-04-15T14:35:00Z" },
    { "interest_level": 72, "recorded_at": "2025-04-30T14:40:00Z" }
  ],
  "next_scheduled_call_at": "2025-05-05T10:00:00Z"
}
```

**Response 404**: Lead not found.

---

### `POST /api/v1/leads`

Create a new lead.

**Request body**:
```json
{
  "client_id": "quintana-seguros",
  "name": "Juan Pérez",
  "phone": "+54911234567",
  "car_make": "Toyota",
  "car_model": "Corolla",
  "car_year": 2019,
  "current_insurance": "Mapfre",
  "notes": null
}
```

**Response 201**: Lead object.

---

### `PATCH /api/v1/leads/{lead_id}/status`

Transition lead status (state machine enforced).

**Valid transitions**:

| From | To |
|------|----|
| `new` | `called` |
| `called` | `interested`, `not_interested`, `follow_up` |
| `follow_up` | `called` |

**Request body**:
```json
{ "status": "interested" }
```

**Response 200**: Updated lead object.

**Response 404**: Lead not found.

**Response 409**: Invalid state transition.

---

### `GET /api/v1/leads/{lead_id}/history`

Get all call sessions for a lead, ordered by `started_at` DESC.

**Response 200**: Array of session summaries.

---

## 10. Scheduler (Bearer auth required)

All scheduler endpoints are also available under `/api/v1/clients/{client_id}/scheduled-calls` (alias path).

### `POST /api/v1/scheduler/{client_id}/queue`

Create a manual scheduled call for a client's lead.

`scheduled_at` must be within the client's `scheduler_allowed_hours` window (local timezone).

**Request body**:
```json
{
  "lead_id": "lead-uuid",
  "scheduled_at": "2025-05-05T10:00:00Z",
  "notes": "Lead requested callback on Monday morning"
}
```

**Response 201**: `ScheduledCallResponse` object.

**Errors**:

| Code | Reason |
|------|--------|
| `404` | Client or lead not found |
| `403` | Lead does not belong to this client |
| `409` | An active scheduled call already exists for this lead |
| `422` | `scheduled_at` is outside allowed hours |

---

### `GET /api/v1/scheduler/{client_id}/queue`

List scheduled calls with optional filters.

**Query parameters**:

| Parameter | Description |
|-----------|-------------|
| `status` | Comma-separated status filter (e.g. `pending,in_progress`) |
| `lead_id` | Filter by lead |
| `scheduled_from` | ISO 8601 datetime lower bound |
| `scheduled_to` | ISO 8601 datetime upper bound |

**Response 200**:
```json
[
  {
    "id": "scheduled-uuid",
    "client_id": "quintana-seguros",
    "lead_id": "lead-uuid",
    "agent_id": "agent-uuid",
    "status": "pending",
    "trigger_reason": "auto",
    "scheduled_at": "2025-05-05T10:00:00Z",
    "source_session_id": "session-uuid",
    "attempt_number": 2,
    "max_attempts": 5,
    "notes": null,
    "created_at": "2025-04-30T14:45:00Z",
    "updated_at": "2025-04-30T14:45:00Z"
  }
]
```

---

### `GET /api/v1/scheduler/{client_id}/queue/{scheduled_call_id}`

Get a single scheduled call.

**Response 200**: `ScheduledCallResponse` object.

**Response 404**: Not found or belongs to a different client.

---

### `POST /api/v1/scheduler/{client_id}/queue/{scheduled_call_id}/cancel`

Cancel a pending or in_progress scheduled call (transitions to `cancelled`).

**Response 200**: `ScheduledCallResponse` with `status=cancelled`.

**Response 404**: Not found.

**Response 409**: Call is in a non-cancellable state (e.g. already `completed` or `failed`).

---

### `PATCH /api/v1/scheduler/{client_id}/queue/{scheduled_call_id}`

Reschedule a pending call to a new datetime. Must be within client's allowed hours.

**Request body**:
```json
{ "scheduled_at": "2025-05-06T11:00:00Z" }
```

**Response 200**: Updated `ScheduledCallResponse`.

**Response 404**: Not found.

**Response 422**: Outside allowed hours or call is not in `pending` status.

---

### `PATCH /api/v1/clients/{client_id}/scheduled-calls/{id}/complete`

Mark a scheduled call as completed.

**Response 200**: `ScheduledCallResponse` with `status=completed`.

**Response 404**: Not found.

**Response 409**: Call is not in a completable state.

---

## 11. Static Pages

| Path | Description |
|------|-------------|
| `GET /demo/` | Browser voice call demo (ElevenLabs WebSocket simulator) |
| `GET /admin` | Redirects to frontend admin at `http://localhost:5173/admin` |
| `GET /docs` | Swagger UI (interactive API documentation) |
| `GET /redoc` | ReDoc (API documentation) |
