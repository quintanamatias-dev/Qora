# Qora Production Roadmap

> Living document. Update as items are completed or scope changes.
> Last updated: 2026-06-23

## Current State

Qora is a working AI call center platform with browser-based voice demo, CRM integration (Airtable), dynamic custom fields, and post-call analysis. The pilot client is Quintana Seguros.

**What works today:**
- Browser demo with ElevenLabs WebSocket voice
- GPT-4o streaming via Custom LLM webhook
- Dynamic per-client tools (capture_data, get_lead_details, etc.)
- Airtable CRM integration with 2-phase field mapping UI
- Post-call analysis, data corrections, CRM sync
- Scheduler queue (creates scheduled calls, does not dial)
- Admin panel with agent config, integration setup, tools management
- Lead list/detail with custom fields, call history, transcripts

**What does NOT work yet:**
- No real phone calls (outbound or inbound)
- No public deployment (local + ngrok only)
- No authentication
- SQLite only (no production DB)
- No monitoring or alerting

---

## Phase A — Enriched Lead Intelligence View

**Goal:** See everything Qora knows about a lead in one place, with a preview of the next call context.

**Why first:** Speeds up debugging, testing, and product iteration for every subsequent phase.

| # | Item | Status | Notes |
|---|------|--------|-------|
| A1 | Backend lead detail aggregate endpoint | - [x] | Lead detail now exposes lead fields, custom-field context, call history, analyses, accumulated facts, quote readiness, and dimension rollups/rankings |
| A2 | Next-call context preview endpoint | - [x] | Returns what the agent context builder assembles, including lead profile, call history, misc notes, available skills/tools, and prompt/model context |
| A3 | Expose missing lead fields in API | - [x] | `email`, `external_crm_id`, `external_lead_id`, `call_count`, `last_called_at`, `next_scheduled_call_at` available in lead detail flows |
| A4 | Join CRM config metadata to custom fields | - [x] | Custom fields include display metadata needed by the lead detail and quote-readiness views |
| A5 | Frontend: collapsible lead detail sections | - [x] | Lead detail includes organized inspection sections for record, readiness, accumulated facts, call history, CRM/Airtable, and next-call preview |
| A6 | Frontend: quote-ready progress indicator | - [x] | Quote readiness shows filled vs missing quote fields |
| A7 | Frontend: next-call context preview panel | - [x] | Lead detail includes a preview of what the agent will receive for the next call |

---

## Phase B — Production Deployment Foundation

**Goal:** Qora accessible from the internet with basic security and a real database.

| # | Item | Status | Notes |
|---|------|--------|-------|
| B1 | Dockerfile + docker-compose | - [x] | Completed in PR #105: single-container FastAPI + React SPA image, compose runtime, SQLite named volume |
| B2 | Deploy to VPS/cloud (Railway, Fly, DigitalOcean, etc.) | - [ ] | Public HTTPS endpoint for webhooks; do last after security hardening |
| B3 | Replace SQLite with PostgreSQL | - [ ] | Deferred for now; continue with SQLite + migrations unless production needs change |
| B4 | Database migrations (Alembic) | - [x] | Completed in PR #103: Alembic migration foundation and startup DDL cleanup |
| B5 | API authentication | - [x] | Completed in PRs #107, #109, #111: admin API key auth, session-scoped demo/pipeline auth, tool scope validation |
| B6 | Webhook signature verification | - [x] | Completed in PR #111: opt-in webhook secret auth for initiation and Custom LLM routes |
| B7 | CORS lockdown | - [x] | Completed in PR #111: configurable `QORA_ALLOWED_ORIGINS` replaces hardcoded allow-all for production |
| B8 | Secrets management | - [x] | Completed in PRs #113, #115: startup validation, active CRM credential checks, root `.env` convention, pre-flight script, operator runbook |
| B9 | Structured logging + error monitoring | - [ ] | Sentry/equivalent, structured log shipping |
| B10 | Background job durability | - [x] | Completed in PRs #119, #120, #121, #122: DB-backed executor, durable summarize/CRM/transcript jobs, feature flag, off-call only |

---

## Phase C — Real Outbound Calls

**Goal:** Qora dials real phone numbers for scheduled calls.

**ElevenLabs phone options (from repo docs):**
1. Native Twilio integration (ElevenLabs manages the call)
2. SIP trunk (bring your own provider)
3. Batch outbound calls API (ElevenLabs initiates multiple calls)

| # | Item | Status | Notes |
|---|------|--------|-------|
| C1 | Choose telephony path | - [ ] | Evaluate Twilio native vs SIP vs Batch API for cost/control/latency |
| C2 | Implement outbound dialer worker | - [ ] | Takes pending ScheduledCall, initiates real call via chosen path |
| C3 | Extend ScheduledCall state machine | - [ ] | pending → dialing → ringing → connected / no_answer / busy / voicemail / failed / completed |
| C4 | Phone number management | - [ ] | Assign numbers per client or shared pool, caller ID policy |
| C5 | Voicemail detection policy | - [ ] | ElevenLabs supports voicemail_detection; define Qora behavior |
| C6 | Failed/busy/no-answer handling | - [ ] | Retry policy, backoff, max attempts |
| C7 | Store telephony metadata | - [ ] | Provider call IDs, duration, cost, quality metrics |
| C8 | End-to-end outbound test | - [ ] | Place a real call to a test number, verify full pipeline |

---

## Phase D — Inbound Calls

**Goal:** Qora receives incoming calls and routes them to the right agent.

| # | Item | Status | Notes |
|---|------|--------|-------|
| D1 | Phone number → client/agent routing | - [ ] | Model: PhoneNumber belongs to Client, routes to Agent |
| D2 | Caller ID → lead resolution | - [ ] | Match incoming phone to existing lead, or create new |
| D3 | Unknown caller flow | - [ ] | Create anonymous lead, collect info during call |
| D4 | Human transfer | - [ ] | ElevenLabs transfer_to_number support + Qora policy/config |
| D5 | Inbound webhook hardening | - [ ] | Initiation webhook exists but needs real routing logic |

---

## Phase E — Production Operations

**Goal:** Qora is reliable, observable, and commercially viable.

| # | Item | Status | Notes |
|---|------|--------|-------|
| E1 | Billing/minute tracking per client | - [ ] | Use billable_minutes from CallSession |
| E2 | Tenant isolation audit | - [ ] | Verify no cross-client data leaks |
| E3 | Call recording/transcript retention policy | - [ ] | Define retention windows, PII handling |
| E4 | Admin operational dashboard | - [ ] | Call volume, success rates, errors, costs |
| E5 | Automated health checks | - [ ] | ElevenLabs connectivity, DB health, webhook latency |
| E6 | Incident playbook | - [ ] | What to do when calls fail, webhooks drop, LLM errors |

---

## Known Issues (fix alongside phases)

### P2 — Important

| Issue | Related Phase | Notes |
|-------|--------------|-------|
| Client CRM status vs Qora internal status conflated | A | `leads.status` serves both purposes; need separate fields |
| Post-call extraction outputs prose instead of tags | A | `lead_profile_facts` gets sentences as `fact_key`; need structured extraction |
| `lead_profile_facts` polluted by CRM dual-write | A | `capture_data` writes `captured:*` facts for backward compat |
| `data_corrections` merge-order bug in summarizer | A | `extracted_facts` merged before corrections applied |

### P3 — Should Fix

| Issue | Related Phase | Notes |
|-------|--------------|-------|
| Duplicate agent/user turns in streaming webhook | C | Double generation visible in transcript |
| Integration mapping UI visual polish | A | Functional but rough |
| Custom field row key remount flicker | A | `key={field_key}-{index}` causes re-render per keystroke |
| Call history endpoint weaker than calls list | A | `/leads/{id}/history` returns limited fields |

### P4 — Nice to Have

| Issue | Related Phase | Notes |
|-------|--------------|-------|
| Generated API types instead of manual TypeScript sync | B | Reduce frontend/backend type drift |
| Programmatic ElevenLabs sync beyond soft timeout | C | Background music, turn timeout, eagerness, phone settings |
| Production runbook | E | Document operational procedures |

---

## Suggested Execution Order

```
Phase A (lead view)     ████████░░░░░░░░░░░░  ← START HERE
Phase B (deploy)        ░░░░████████░░░░░░░░  ← parallel with late A
Phase C (outbound)      ░░░░░░░░░░░░████████  ← after B deployed
Phase D (inbound)       ░░░░░░░░░░░░░░░░████  ← after C stable
Phase E (operations)    ░░░░░░░░████████████  ← continuous from B onward
```

Phase A is pure product value with zero infrastructure risk.
Phase B enables everything else.
Phase C is the first real revenue milestone.
