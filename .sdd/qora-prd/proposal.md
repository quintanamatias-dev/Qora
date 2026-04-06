# Proposal: QORA — Product Requirements Document

> **Change**: qora-prd
> **Date**: 2026-04-05
> **Status**: Final — no decisions open

---

## 1. Executive Summary

**QORA** (Quintana Operational Response Architecture) is an AI-powered outbound call center-as-a-service. It deploys AI voice agents that call leads, qualify them in natural Rioplatense Spanish, and route outcomes to a CRM — replacing the cold-call SDR workflow entirely.

**Problem**: Insurance brokers (and similar SMBs) need to call hundreds of leads per week. Human SDR teams are expensive, inconsistent, and don't scale. Existing voice AI tools sell "minutes" — they don't sell a complete sales workflow with CRM integration, lead state management, and business logic.

**Why now**: ElevenLabs Conversational AI reached production quality for Spanish. GPT-4o latency is under 300ms. The "custom LLM webhook" pattern lets us own the brains while delegating audio to ElevenLabs. This combination makes a natural-sounding, intelligent Spanish-speaking agent buildable in weeks, not years.

**Pilot**: Quintana Seguros (Argentina insurance broker). First client, first revenue, first proof.

---

## 2. Target Users

### Primary Buyer — Business Owner (e.g., Quintana)
- Wants leads converted to cotizaciones without hiring more SDRs
- Cares about: cost per qualified lead, calls per day, conversion rate
- Does NOT configure software — we do it for them

### Primary User — Operations/Sales Manager
- Monitors dashboard: conversion rate, call status, lead pipeline
- Reviews leads marked "cotizar" and follows up manually
- Needs: simple lead list with clear states, no ambiguity

### User Journeys

**Journey A — Lead enters pipeline**
1. Lead imported (CSV or CRM sync)
2. AI agent calls lead (outbound, scheduled or immediate)
3. Conversation in Rioplatense Spanish: qualify, collect data
4. Outcome: `interested` → marked `cotizar` + data stored | `rejected` → marked `sin_interés`
5. Sales manager reviews `cotizar` queue and follows up

**Journey B — Client onboarding**
1. QORA team configures: system prompt, KB, voice, tools per client
2. Test calls run internally
3. Client gets dashboard access
4. Calls go live

---

## 3. Product Phases

### Phase 0 — Local Proof of Concept
**Goal**: Validate the core conversation experience. Zero infrastructure cost.

- ElevenLabs Conversational AI + Custom LLM webhook (local, ngrok tunnel)
- SQLite mock CRM with 5 test leads
- Agent speaks natural Rioplatense Spanish with dynamic fillers (never silent)
- Tools: `get_lead_info`, `register_interest`, `mark_not_interested`, `schedule_followup`
- Full conversation: intro → qualify → collect data → close with CRM update

**Exit criteria**: Agent maintains natural 3+ minute conversation without awkward silence.

---

### Phase 1 — Multi-Client Foundation
**Goal**: Validate one codebase serves multiple isolated clients.

- Multi-tenant architecture: per-client DB isolation
- Per-client configuration: system prompt, knowledge base, voice ID, tool set
- Client provisioning flow (internal tooling — no self-serve UI)
- Configuration hot-reload without restart

**Exit criteria**: 2 simulated clients run simultaneously on same backend with isolated data.

---

### Phase 2 — Complete Conversation Orchestration
**Goal**: Validate full production-ready conversation flow.

- Call memory: second call to same lead knows about first call
- Full call lifecycle: initiated → in_progress → completed/failed/abandoned
- Call recording + transcript storage (per call, per client)
- Basic metrics collection: duration, outcome, call count per lead
- Retry logic: max attempts, cooldown between calls

**Exit criteria**: Agent on second call references prior interaction naturally.

---

### Phase 3 — Real Calls (first real cost)
**Goal**: Validate end-to-end with real telephony.

- Deploy backend to Railway/Render (~$5/month)
- Twilio integration: outbound calls via Twilio → ElevenLabs → backend
- Public webhook endpoint (ElevenLabs Custom LLM over SSE)
- Twilio phone number provisioned per client
- First real call to a real mobile phone in Argentina

**Exit criteria**: Complete real call from dial to CRM update, recorded, no errors.

---

### Phase 4 — Sellable Product
**Goal**: First paying client live.

- Real CRM integration (client's existing tool or QORA native CRM)
- Client dashboard: conversion rate, calls completed/abandoned, call duration, lead pipeline
- Lead management UI: states visible, filter by state, manual override
- Per-minute billing tracking (usage logs per client per call)
- Client onboarding runbook (internal — WE run it with client)
- SLA monitoring: uptime during business hours

**Exit criteria**: First invoice sent and paid. Client calling leads via QORA.

---

## 4. Functional Requirements

### Phase 0
| ID | Requirement |
|----|-------------|
| F0-1 | ElevenLabs agent calls backend webhook via SSE for every conversation turn |
| F0-2 | Backend responds with GPT-4o completion in <500ms perceived (fillers bridge latency) |
| F0-3 | System prompt instructs agent to open EVERY response with a contextual Spanish filler |
| F0-4 | `get_lead_info` tool returns lead name, product interest, prior notes from SQLite |
| F0-5 | `register_interest` tool stores lead data + marks state = `cotizar` |
| F0-6 | `mark_not_interested` tool marks state = `sin_interés` |
| F0-7 | `schedule_followup` tool stores preferred callback time + marks state = `follow_up` |
| F0-8 | Agent never says "un momento" and goes silent — fillers are mandatory |

### Phase 1
| ID | Requirement |
|----|-------------|
| F1-1 | Each client has isolated DB schema or separate DB file |
| F1-2 | Webhook URL accepts `client_id` to route to correct tenant |
| F1-3 | System prompt loaded from per-client config at conversation start |
| F1-4 | Knowledge base (FAQ, product info) injected into system prompt per client |
| F1-5 | Voice ID configurable per client (ElevenLabs voice selection) |
| F1-6 | Tool set configurable per client (some clients may not have `schedule_followup`) |

### Phase 2
| ID | Requirement |
|----|-------------|
| F2-1 | On conversation start, load all prior calls for this lead from DB |
| F2-2 | Prior call summaries injected into system prompt context |
| F2-3 | Call record created at start: `call_id`, `lead_id`, `client_id`, `started_at` |
| F2-4 | Call record updated at end: `ended_at`, `duration_seconds`, `outcome`, `transcript` |
| F2-5 | Transcript stored as structured turn array (role + content + timestamp) |
| F2-6 | Metrics endpoint: calls today, conversion rate (interested/total), avg duration |
| F2-7 | Max 3 call attempts per lead; 24h cooldown between attempts |

### Phase 3
| ID | Requirement |
|----|-------------|
| F3-1 | Twilio webhook receives inbound call leg and bridges to ElevenLabs stream |
| F3-2 | Backend deployed with public HTTPS URL (Railway/Render) |
| F3-3 | ElevenLabs Custom LLM webhook URL points to deployed backend |
| F3-4 | Outbound call triggered via API: `POST /calls/initiate` with `lead_id` |
| F3-5 | Call recording stored (Twilio recording or ElevenLabs audio) |
| F3-6 | Error handling: Twilio no-answer, busy, failed — all update call record |

### Phase 4
| ID | Requirement |
|----|-------------|
| F4-1 | Dashboard shows: total calls, conversion %, avg duration, calls by state |
| F4-2 | Lead list with state filter: new / called / interested / not_interested / follow_up |
| F4-3 | Per-call detail: transcript, duration, outcome, recording link |
| F4-4 | Usage log per client: `call_id`, `client_id`, `duration_seconds`, `cost_per_min` |
| F4-5 | Billing report: total minutes per billing period per client |
| F4-6 | Lead import via CSV upload (QORA team runs this, not client self-serve) |

---

## 5. Non-Functional Requirements

| Requirement | Target | Notes |
|-------------|--------|-------|
| **Perceived Latency** | <500ms | Dynamic fillers bridge real LLM latency; GPT-4o target <300ms |
| **Availability** | 99.9% during business hours (8am–8pm ART) | Maintenance in off-hours |
| **Data Isolation** | Hard per-client boundary | No cross-tenant data leak ever |
| **Concurrent Calls** | 10 per client | Scale-up path: horizontal FastAPI workers |
| **Transcript Retention** | Indefinite | Never delete — legal + training value |
| **Recording Storage** | 90 days hot, then archive | S3 or Twilio native storage |
| **Auth** | API key per client (Phase 3+) | JWT for dashboard (Phase 4) |
| **Language** | Rioplatense Spanish only (MVP) | Multi-language deferred |

---

## 6. Out of Scope (MVP)

| Feature | Why Deferred |
|---------|-------------|
| Inbound calls | Different flow; not client priority |
| Auto-quoting | Requires insurance pricing engine integration |
| Email automation | Separate channel; out of call flow |
| Self-serve client configuration | We onboard — reduces support overhead |
| Mobile app | Web dashboard sufficient for Phase 4 |
| Multi-language support | Argentina pilot is Spanish-only |
| Predictive dialer / bulk scheduling | Phase 5+ |
| Real-time agent supervisor monitoring | Post-MVP |
| Sentiment analysis | Valuable but not blocking |

---

## 7. Success Metrics

| Phase | Metric | Target |
|-------|--------|--------|
| Phase 0 | Conversation quality | 3+ min natural conversation, 0 awkward silences |
| Phase 0 | Tool reliability | 100% of test conversations update CRM correctly |
| Phase 1 | Multi-tenancy | 2 clients run simultaneously, zero data cross-contamination |
| Phase 2 | Memory | Agent references prior call in 100% of second calls |
| Phase 3 | Real telephony | First end-to-end real call with CRM update |
| Phase 3 | Reliability | <5% call failure rate (network/telephony) |
| Phase 4 | Business | First invoice paid by Quintana Seguros |
| Phase 4 | Conversion | >15% lead-to-cotizar rate (vs. human SDR baseline) |
| Phase 4 | Unit economics | Cost per qualified lead < 30% of human SDR cost |

---

## 8. Technical Stack

### Core
| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Backend** | Python 3.12 + FastAPI | Async, fast, Python ML ecosystem compatibility |
| **Voice Interface** | ElevenLabs Conversational AI | Best Spanish TTS quality; Custom LLM mode gives us full control |
| **LLM** | OpenAI GPT-4o | Best latency/quality for Spanish; function calling native |
| **DB (MVP)** | SQLite | Zero infra cost for Phase 0-2; file-based |
| **DB (Prod)** | PostgreSQL | Phase 3+; Railway managed |
| **Telephony** | Twilio | Phase 3+; programmable voice, Argentina numbers available |
| **Deploy** | Railway | $5/month; Git push deploy; auto HTTPS |

### Architecture Pattern
```
Lead → Twilio (PSTN) → ElevenLabs (STT+TTS+VAD) ←→ FastAPI Backend (GPT-4o + Business Logic + CRM)
```

- ElevenLabs handles: audio quality, VAD, silence detection, streaming
- Our backend handles: conversation state, GPT-4o calls, tool execution, CRM writes
- Custom LLM webhook via SSE: ElevenLabs streams conversation turns, we respond with completions + tool calls

### File Structure (current)
```
backend/
├── app/           # FastAPI app, routes, config
├── agents/        # Agent logic, system prompts, tools
├── tests/         # Test suite
└── callcenter.db  # SQLite (Phase 0)
```

---

## Intent

Enable Quintana Seguros (and future clients) to run AI outbound call campaigns with full lead qualification, CRM integration, and per-minute billing — replacing SDR cold-calling at a fraction of the cost.

## Scope

### In Scope
- Phases 0–4 feature delivery as defined above
- Rioplatense Spanish voice agent with dynamic fillers
- Multi-tenant backend with per-client isolation
- Lead lifecycle: new → called → interested/not_interested/follow_up
- Dashboard for ops/sales managers
- Per-minute billing tracking

### Out of Scope
- Everything in Section 6 above

## Capabilities

### New Capabilities
- `outbound-call-agent`: AI voice agent that conducts outbound qualification calls in Rioplatense Spanish
- `lead-management`: Lead state machine (new/called/interested/not_interested/follow_up) with CRM ops
- `multi-tenant-config`: Per-client isolation of data, prompts, KB, and tool configuration
- `call-memory`: Cross-call context — agent knows prior conversation history per lead
- `call-lifecycle`: Full call record: initiation, transcript, duration, outcome, recording
- `metrics-dashboard`: Conversion rate, call stats, lead pipeline view per client
- `billing-tracking`: Per-minute usage logs per client for invoice generation
- `telephony-integration`: Twilio outbound call bridging to ElevenLabs stream

### Modified Capabilities
- None (greenfield product)

## Approach

**Phase 0–2**: Build locally. ElevenLabs + ngrok + FastAPI + SQLite. Zero infra cost. Validate conversation quality and business logic before spending a dollar on telephony.

**Phase 3**: Lift to Railway. Add Twilio. One real call proves the full stack.

**Phase 4**: Add dashboard, billing tracking, CSV import. Hand off to Quintana.

Key technical bets:
1. ElevenLabs Custom LLM webhook — we own GPT-4o calls, ElevenLabs owns audio
2. Dynamic fillers via system prompt — agent always sounds thinking, never silent
3. SQLite → PostgreSQL migration path — not a rewrite, same ORM models

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/` | Modified | Routes for webhook, call initiation, metrics |
| `backend/agents/` | Modified | System prompts, tool definitions, conversation logic |
| `backend/callcenter.db` | Modified | Schema: leads, calls, clients, transcripts, usage |
| `backend/app/config/` | New | Per-client configuration store |
| `frontend/` (Phase 4) | New | Dashboard — React or simple HTML+HTMX TBD |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ElevenLabs Spanish quality degrades on Rioplatense accent | Low | Test in Phase 0 with real Argentine phrases; voice selection |
| GPT-4o latency spikes >500ms | Med | Dynamic fillers buy 2–3s; fallback to shorter completions |
| Twilio Argentina number availability | Low | Verify in Phase 3 before committing; Vonage fallback |
| SQLite → PostgreSQL migration breaks in Phase 3 | Med | Use SQLAlchemy ORM from day 1; test migration script in Phase 2 |
| ElevenLabs Custom LLM webhook SSE drops connection mid-call | Med | Reconnect logic + conversation state persisted to DB, not RAM |
| Client data isolation bug (multi-tenant) | Low | Every DB query scoped by `client_id`; tested in Phase 1 |

## Rollback Plan

- **Phase 0–2** (local): No rollback needed — no production traffic
- **Phase 3**: Keep previous Railway deployment slug. Twilio webhook URL can be reverted in Twilio console in <1min
- **Phase 4**: Feature flags per client. If dashboard breaks, disable for client without affecting calls

## Dependencies

- ElevenLabs API key (Conversational AI + Custom LLM mode enabled)
- OpenAI API key (GPT-4o)
- Twilio account with Argentina DID (Phase 3)
- Railway account (Phase 3)
- Quintana Seguros lead data (CSV with name, phone, product interest)

## Success Criteria

- [ ] Phase 0: Agent completes 3+ minute natural conversation with 0 awkward silences
- [ ] Phase 0: All 4 tools (`get_lead_info`, `register_interest`, `mark_not_interested`, `schedule_followup`) execute correctly in conversation
- [ ] Phase 1: 2 simulated clients run on same backend with zero data cross-contamination
- [ ] Phase 2: Second call to same lead references prior call context naturally
- [ ] Phase 3: First real phone call completes end-to-end with CRM update
- [ ] Phase 4: Quintana Seguros pays first invoice
