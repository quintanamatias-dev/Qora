# QORA Phase 0 — Specification

> **Change**: qora-phase0
> **Date**: 2026-04-05
> **Status**: Draft
> **Scope**: Local proof of concept — ElevenLabs + FastAPI + SQLite

---

## Purpose

Define behavioral requirements for QORA Phase 0: the local PoC that validates AI-powered outbound call quality, CRM tool execution, and natural Rioplatense Spanish conversation — before any real telephony or infrastructure cost.

---

## CAP-1: Custom LLM Webhook

### Requirement: SSE Stream Response

The endpoint `POST /api/v1/elevenlabs/custom-llm` MUST accept an OpenAI-compatible chat completion request from ElevenLabs and return a Server-Sent Events (SSE) stream.

The system MUST extract `client_id`, `lead_id`, and session metadata from the `elevenlabs_extra_body` field of the incoming request.

The system MUST use `client_id` to route the request to the correct tenant configuration before invoking GPT-4o.

The system MUST stream the first SSE token within 500ms of receiving the request.

The stream MUST conform to OpenAI streaming format (`data: {"choices":[{"delta":{"content":"..."}}]}`).

#### Scenario: Happy path — turn processed and streamed

- GIVEN ElevenLabs sends a valid conversation turn to the Custom LLM endpoint
- WHEN the system extracts `client_id` and `lead_id` from `elevenlabs_extra_body`
- THEN a dynamic filler token MUST be the first content emitted in the SSE stream
- AND the full GPT-4o response MUST stream as subsequent SSE tokens
- AND the stream MUST end with `data: [DONE]`

#### Scenario: Missing client_id

- GIVEN ElevenLabs sends a request with no `client_id` in `elevenlabs_extra_body`
- WHEN the endpoint receives the request
- THEN the system MUST return HTTP 422
- AND MUST NOT attempt a GPT-4o call

#### Scenario: Unknown client_id

- GIVEN `client_id` does not match any registered tenant
- WHEN routing is attempted
- THEN the system MUST return HTTP 404 with `{"error": "client not found"}`

---

## CAP-2: Conversation Initiation Webhook

### Requirement: Pre-Call Lead Injection

The endpoint `POST /api/v1/elevenlabs/initiation` MUST be called by ElevenLabs at call start, before the agent speaks.

The system MUST respond within 2000ms (call fires during Twilio ring tone).

The system MUST extract `lead_id` from the request and fetch the corresponding lead from the mock CRM.

The system MUST return a `dynamic_variables` object containing: `lead_name`, `car_make`, `car_model`, `car_year`, `current_insurance`, `lead_status`, `lead_notes`.

#### Scenario: Lead found — variables injected

- GIVEN ElevenLabs fires the initiation webhook with a valid `lead_id`
- WHEN the system fetches the lead from SQLite
- THEN the response MUST include `dynamic_variables` with all 7 lead fields
- AND MUST respond within 2000ms

#### Scenario: Lead not found

- GIVEN `lead_id` does not exist in the mock CRM
- WHEN the system queries SQLite
- THEN the system MUST return `dynamic_variables` with all fields set to empty strings
- AND MUST NOT return an error status — call proceeds with unknown lead

#### Scenario: CRM lookup timeout

- GIVEN the SQLite query takes longer than 1800ms
- WHEN the timeout elapses
- THEN the system MUST return partial `dynamic_variables` with available data
- AND MUST log the timeout event

---

## CAP-3: Mock CRM — Lead Management

### Requirement: Lead Schema and CRUD

The system MUST maintain a `leads` table in SQLite with the following fields:

| Field | Type | Required |
|-------|------|----------|
| `id` | TEXT (UUID) | MUST |
| `client_id` | TEXT | MUST |
| `name` | TEXT | MUST |
| `phone` | TEXT | MUST |
| `car_make` | TEXT | SHOULD |
| `car_model` | TEXT | SHOULD |
| `car_year` | INTEGER | SHOULD |
| `current_insurance` | TEXT | MAY |
| `status` | TEXT | MUST |
| `notes` | TEXT | MAY |
| `created_at` | DATETIME | MUST |
| `updated_at` | DATETIME | MUST |
| `last_called_at` | DATETIME | MAY |
| `call_count` | INTEGER | MUST (default 0) |

### Requirement: Lead State Machine

The system MUST enforce valid state transitions. Invalid transitions MUST be rejected with HTTP 409.

```
new → called → interested
             → not_interested
             → follow_up
follow_up → called
```

`called` MUST be set automatically when a conversation initiation webhook fires for a lead.
`interested`, `not_interested`, and `follow_up` MUST only be set via the agent tools (CAP-4).

### Requirement: Seed Data

The system MUST seed 5 test leads for `client_id = "quintana-seguros"` at startup if no leads exist.

Each seed lead MUST cover a distinct initial status: at least 2 `new`, 1 `called`, 1 `interested`, 1 `not_interested`.

#### Scenario: Valid state transition

- GIVEN a lead with `status = "called"`
- WHEN the system receives a request to set `status = "interested"`
- THEN the lead MUST be updated with `status = "interested"` and `updated_at` refreshed

#### Scenario: Invalid state transition

- GIVEN a lead with `status = "new"`
- WHEN the system receives a request to set `status = "not_interested"` directly
- THEN the system MUST return HTTP 409 with `{"error": "invalid_transition", "from": "new", "to": "not_interested"}`

#### Scenario: Duplicate seed guard

- GIVEN the database already contains leads for `quintana-seguros`
- WHEN the application starts
- THEN the system MUST NOT insert duplicate seed leads

---

## CAP-4: Tools — Agent Actions

### Requirement: get_lead_details

The tool `get_lead_details` MUST accept `lead_id` and return the full lead record from the mock CRM.

#### Scenario: Lead exists

- GIVEN the agent calls `get_lead_details` with a valid `lead_id`
- WHEN the tool executes
- THEN the tool MUST return all lead fields as a JSON object
- AND MUST increment `call_count` and set `last_called_at`

#### Scenario: Lead not found

- GIVEN `lead_id` does not exist
- WHEN the tool executes
- THEN the tool MUST return `{"error": "lead_not_found"}`

### Requirement: register_interest

The tool `register_interest` MUST accept `lead_id`, `car_make`, `car_model`, `car_year`, `current_insurance`, and an optional `notes` field.

The tool MUST update the lead record and transition status to `interested`.

#### Scenario: Successful interest registration

- GIVEN the agent confirms the lead wants a quote
- WHEN the agent calls `register_interest` with collected data
- THEN the lead status MUST be set to `interested`
- AND all collected fields MUST be persisted to the lead record
- AND `updated_at` MUST be refreshed

#### Scenario: Missing required field

- GIVEN `register_interest` is called without `car_make`
- WHEN the tool validates input
- THEN the tool MUST return `{"error": "missing_field", "field": "car_make"}`
- AND the lead record MUST NOT be modified

### Requirement: mark_not_interested

The tool `mark_not_interested` MUST accept `lead_id` and `reason` (free text, REQUIRED).

The tool MUST transition the lead to `not_interested` and persist the reason in `notes`.

#### Scenario: Rejection recorded

- GIVEN the lead declines interest
- WHEN the agent calls `mark_not_interested` with a reason
- THEN the lead status MUST be set to `not_interested`
- AND the reason MUST be stored in `notes`
- AND the lead record MUST NEVER be deleted

### Requirement: schedule_followup

The tool `schedule_followup` MUST accept `lead_id`, `followup_date` (ISO 8601), and an optional `note`.

The tool MUST transition the lead to `follow_up` and store the scheduled date in `notes`.

#### Scenario: Follow-up scheduled

- GIVEN the lead requests a callback on a specific date
- WHEN the agent calls `schedule_followup` with a valid date
- THEN the lead status MUST be set to `follow_up`
- AND the followup date and note MUST be persisted

---

## CAP-5: Dynamic Filler System

### Requirement: Mandatory Contextual Fillers

The system MUST instruct GPT-4o via the system prompt to begin EVERY response with a contextual Rioplatense Spanish filler phrase before the substantive reply.

Fillers MUST vary by conversational context:

| Context | Example Fillers |
|---------|----------------|
| Thinking / searching | "A ver...", "Mmm, dejame ver...", "Estoy chequeando..." |
| Processing / computing | "Dale, ya lo estoy mirando...", "Un segundo..." |
| Transitioning | "Bueno, entonces...", "Perfecto, y ahí..." |

The system MUST NOT allow the same filler to repeat twice consecutively within the same conversation.

### Requirement: 500ms Fallback Filler

If the GPT-4o response stream has not begun within 500ms of the turn start, the system MUST inject a static fallback filler via SSE before the real response arrives.

The fallback filler MUST be a safe, context-neutral phrase (e.g., "Mmm, dejame ver...").

#### Scenario: Fast LLM response — no fallback needed

- GIVEN GPT-4o begins streaming within 300ms
- WHEN the SSE stream is sent to ElevenLabs
- THEN the dynamic filler from the prompt MUST be the first tokens
- AND no additional fallback filler MUST be injected

#### Scenario: Slow LLM — fallback triggered

- GIVEN GPT-4o has not begun streaming after 500ms
- WHEN the 500ms timer fires
- THEN the system MUST immediately emit a static filler SSE token
- AND MUST continue streaming the real response when it arrives

#### Scenario: Filler repetition prevention

- GIVEN the agent used "A ver..." in the previous turn
- WHEN GPT-4o generates "A ver..." as the next filler
- THEN the system MUST substitute a different filler from the same context group

---

## CAP-6: Multi-Tenant Routing

### Requirement: client_id-Based Routing

Every incoming webhook request MUST carry a `client_id`.

The system MUST use `client_id` to load the corresponding tenant configuration: `system_prompt`, `voice_id`, `agent_name`, `knowledge_base`.

The system MUST scope ALL database queries with `client_id`. A query MUST NEVER return data from a different tenant.

### Requirement: Per-Client Configuration

The system MUST store per-client configuration as a record in SQLite (`clients` table) or a config file, containing: `client_id`, `agent_name`, `voice_id`, `system_prompt_template`, `knowledge_base`.

#### Scenario: Correct tenant config loaded

- GIVEN `client_id = "quintana-seguros"` arrives in a webhook
- WHEN the system loads configuration
- THEN the system prompt for Quintana MUST be used — NOT the default prompt
- AND the voice_id for Quintana MUST be passed to GPT-4o context

#### Scenario: Cross-tenant isolation

- GIVEN two clients exist: `quintana-seguros` and `acme-insurance`
- WHEN a request for `quintana-seguros` fetches leads
- THEN ONLY leads with `client_id = "quintana-seguros"` MUST be returned

---

## CAP-7: Call Session Management

### Requirement: Call Record Lifecycle

The system MUST create a call record when a conversation initiation webhook fires.

Each call record MUST contain: `call_id` (UUID), `lead_id`, `client_id`, `started_at`, `status`.

The system MUST update the call record at call end with: `ended_at`, `duration_seconds`, `outcome` (`completed` | `abandoned` | `failed`), and `transcript`.

### Requirement: Turn-Level Transcript

The system MUST store each conversation turn in the call record as a structured array entry: `{role, content, timestamp}`.

### Requirement: Billable Minutes Calculation

The system MUST calculate `billable_minutes` as `CEIL(duration_seconds / 60)` and store it on the call record.

### Requirement: Graceful Disconnection

If ElevenLabs closes the SSE connection unexpectedly, the system MUST finalize the call record with `outcome = "abandoned"` and store the partial transcript.

#### Scenario: Normal call completion

- GIVEN a call starts and the agent concludes the conversation
- WHEN the call end event is received
- THEN the call record MUST be updated with `ended_at`, `duration_seconds`, and `outcome = "completed"`
- AND `billable_minutes` MUST equal `CEIL(duration_seconds / 60)`

#### Scenario: Unexpected disconnection

- GIVEN the SSE connection is dropped mid-call
- WHEN the disconnect event fires
- THEN the call record MUST be finalized with `outcome = "abandoned"`
- AND the partial transcript MUST be saved

#### Scenario: Transcript storage

- GIVEN a 5-turn conversation completes
- WHEN the call ends
- THEN the transcript MUST contain exactly 5 entries
- AND each entry MUST include `role`, `content`, and `timestamp`

---

## CAP-8: Jaumpablo — Insurance Agent Prompt

### Requirement: Configurable System Prompt

The system MUST provide a complete system prompt template for the Quintana Seguros insurance agent use case.

The prompt MUST support the following template variables: `{{ agent_name }}`, `{{ broker_name }}`, `{{ lead_name }}`, `{{ car_make }}`, `{{ car_model }}`, `{{ car_year }}`, `{{ current_insurance }}`, `{{ lead_status }}`, `{{ lead_notes }}`.

All template variables MUST be replaced with real values before the prompt is sent to GPT-4o.

### Requirement: Conversation Flow

The prompt MUST guide the agent through the following phases in order:

| Phase | Goal |
|-------|------|
| Greeting | Introduce as `{{ agent_name }}` from `{{ broker_name }}`, confirm the lead's name |
| Qualification | Confirm car details: make, model, year |
| Current insurance | Ask who they're currently insured with |
| Interest check | Gauge interest in a better rate |
| Pitch | Present value proposition (not a hard sell — warm and natural) |
| Objection handling | Address price, trust, or timing objections |
| Close | Offer to register for a quote (calls `register_interest`) or follow up |

### Requirement: Language and Persona

The prompt MUST specify:
- Language: Rioplatense Spanish (voseo: "vos", "te", "tu auto")
- Tone: warm, professional, conversational — NOT robotic or scripted-sounding
- Fillers: mandatory before every substantive reply (see CAP-5)
- NEVER use "un momento" followed by silence
- Agent name MUST be `{{ agent_name }}` — default `"Jaumpablo"`

### Requirement: Tool Invocation Rules

The prompt MUST instruct the agent:
- Call `get_lead_details` at conversation start if lead data is missing
- Call `register_interest` ONLY when the lead explicitly agrees to receive a quote
- Call `mark_not_interested` when the lead clearly declines AND provides a reason
- Call `schedule_followup` when the lead requests a callback date
- NEVER call a tool without user intent confirmation

#### Scenario: Warm greeting with known lead

- GIVEN `lead_name = "Carlos"` and `car_make = "Toyota"` are injected into the prompt
- WHEN the call starts and the agent greets
- THEN the agent MUST use "Carlos" and reference his Toyota in the greeting
- AND MUST use voseo ("¿Cómo estás vos?")

#### Scenario: Interest confirmed — tool fires

- GIVEN the lead says "Sí, mandame la cotización"
- WHEN the agent processes the response
- THEN the agent MUST call `register_interest` with collected car data
- AND MUST verbally confirm to the lead that the quote is being registered

#### Scenario: Rejection handled gracefully

- GIVEN the lead says "No me interesa, gracias"
- WHEN the agent processes the response
- THEN the agent MUST acknowledge politely without pressure
- AND MUST call `mark_not_interested` with the stated reason
- AND MUST end the call warmly

---

## Acceptance Criteria Summary

| Capability | Passing Condition |
|------------|-------------------|
| CAP-1 | SSE stream starts within 500ms; dynamic filler is first token; `client_id` routing works |
| CAP-2 | Initiation webhook responds in <2s; all 7 `dynamic_variables` present for known leads |
| CAP-3 | State machine rejects invalid transitions; 5 seed leads present; `client_id` scoping enforced |
| CAP-4 | All 4 tools execute without errors in a test conversation; CRM reflects correct state post-call |
| CAP-5 | No two consecutive identical fillers; fallback fires at 500ms; filler varies by context |
| CAP-6 | Two tenants run simultaneously with zero cross-contamination in DB queries |
| CAP-7 | Call record created at start; transcript stored per turn; `billable_minutes` correct; abandoned calls finalized |
| CAP-8 | Agent completes 3+ minute natural conversation; all template vars injected; voseo enforced; tools fire on correct intent |
