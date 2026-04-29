# Exploration: n8n Orchestration for Post-Call Analysis Pipeline

## Current State

### Trigger Mechanism
The summarizer pipeline (`generate_summary_and_facts`) is triggered via fire-and-forget `asyncio.create_task` in THREE places:
1. **`close_session()`** in `calls/service.py:626` — when a call session ends normally via `/{conversation_id}/end`
2. **`_reconcile_session()`** in `calls/service.py:526` — when a session is reconciled via ElevenLabs post-call webhook
3. **`sweep_stale_sessions()`** in `sweeper.py:83` — when background sweeper marks abandoned sessions

All three call `_schedule_summarize(session_id)` which creates an asyncio background task with its own independent DB session.

### Pipeline Steps (in `_run_summarizer`)
1. Load transcript turns from DB (`SELECT TranscriptTurn WHERE session_id ORDER BY timestamp`)
2. Skip if 0 turns (no GPT call, no side-effects)
3. Load CallSession to get `lead_id`, `client_id`
4. Format transcript as text (role: content lines)
5. Load client `ExtractionConfig` (per-client axes, disabled axes, prompt addendum)
6. Count user/agent turns
7. Call GPT-4o-mini via OpenAI Structured Outputs (`.parse()` with PostCallAnalysis model)
8. On GPT failure: persist failure marker to CallSession + CallAnalysis (within savepoint)
9. On success (within single savepoint for atomicity):
   - a. Persist summary + facts to CallSession (legacy path)
   - b. Upsert CallAnalysis row (analysis v2 dual-write)
   - c. Merge facts into Lead (objections union, interest_level, do_not_call, etc.)
   - d. Write LeadProfileFact rows (upsert semantics with superseded_at)
   - e. Write LeadInterestHistory row (append-only)
   - f. Auto-schedule follow-up call if eligible (Phase 6 scheduler)

### N8N Migration Boundary (Explicitly Marked in Code)
`analysis_schema.py` header states:
> "This module is the N8N migration boundary. When migrating to N8N:
> - Copy this file + ANALYSIS_SYSTEM_PROMPT to the N8N webhook handler.
> - Remove from this codebase."

The schema module is designed to be self-contained: only imports pydantic + enum + re + functools. NO app dependencies.

## Affected Areas
- `backend/app/summarizer.py` — main pipeline (853 lines)
- `backend/app/analysis_schema.py` — schema + prompts (733 lines, N8N boundary module)
- `backend/app/calls/service.py` — trigger points (`_schedule_summarize`, `close_session`, reconcile)
- `backend/app/calls/router.py` — elevenlabs-postcall webhook endpoint
- `backend/app/sweeper.py` — stale session sweeper (also triggers summarizer)
- `backend/app/scheduler/service.py` — `auto_schedule` called at end of pipeline
- `backend/app/core/config.py` — will need N8N_URL, N8N_WEBHOOK_SECRET env vars
- `backend/tests/unit/test_summarizer.py` — 50+ tests covering the pipeline

## Migration Boundary Map

### Moves to n8n (orchestration + GPT call)
| Component | Current Location | n8n Node Type |
|-----------|-----------------|---------------|
| Transcript formatting | `_format_transcript()` | Code node |
| System prompt building | `build_system_prompt(config)` | Code node (or pre-built by backend) |
| Model selection | `build_analysis_model(config)` | Provided by backend as JSON Schema |
| GPT-4o-mini call | `_call_gpt_summarize()` | OpenAI node OR HTTP Request node |
| Refusal/None handling | In `_call_gpt_summarize()` | IF node + error branches |
| Retry logic | Currently none (single attempt) | Retry mechanism (n8n native) |

### MUST Stay in Backend (data persistence)
| Component | Reason |
|-----------|--------|
| DB reads (transcript, session, lead, config) | SQLAlchemy async sessions, ORM relationships |
| CallSession + CallAnalysis writes | Savepoint atomicity, upsert semantics |
| Lead merge logic | Complex union/supersede/append logic |
| LeadProfileFact + LeadInterestHistory | Deduplication, namespace logic |
| Auto-scheduling | Depends on scheduler service + client config |
| ExtractionConfig loading | Per-client, stored in Client table as JSON |

### Webhook Fire Point
- AFTER `close_session()` flushes (session is committed, transcript is in DB)
- Same spot where `_schedule_summarize` is called today (service.py line 626)
- Payload: `{session_id, client_id}`

## n8n-MCP Plugin Summary

**Repository:** https://github.com/czlonkowski/n8n-mcp (18.9k stars, MIT, v2.48.1)

**What it provides:**
- MCP server that bridges AI assistants ↔ n8n instance
- 7 core tools: search_nodes, get_node, validate_node, validate_workflow, search_templates, get_template, tools_documentation
- 13 management tools: CRUD workflows, execute, manage credentials, audit, health check
- Supports: Claude Desktop, Claude Code, Windsurf, Cursor, VS Code Copilot

**Configuration:**
- `N8N_API_URL` — n8n instance URL
- `N8N_API_KEY` — n8n API key
- Runs via npx, Docker, or hosted service

**Value for Qora:**
- Future agents can inspect/modify n8n workflows programmatically
- Validate workflow configurations before deploy
- Template library for common patterns
- Primarily a Phase 2+ benefit (agent-assisted workflow iteration)

## Approaches

### 1. Backend-orchestrated with n8n for GPT + retry only
- Backend POSTs transcript + config to n8n webhook
- n8n handles: GPT call, retry on failure (2-3 retries), parse response
- n8n calls back to `/api/v1/internal/analysis-result` with parsed facts
- Backend persists everything (same atomic savepoint logic)
- **Pros:** Minimal code change, GPT retries visible in n8n, DB logic stays proven
- **Cons:** n8n is a middleman for a single API call, limited observability benefit
- **Effort:** Medium

### 2. Full pipeline in n8n with callback API (RECOMMENDED for Phase 2)
- Backend POSTs session_id + client_id to n8n webhook (lightweight trigger)
- n8n workflow steps:
  1. Fetch transcript via backend API
  2. Fetch extraction config
  3. Format transcript (Code node)
  4. Build prompt
  5. Call GPT-4o-mini (structured output)
  6. Retry branch (failure → retry 2x → fallback → mark failed)
  7. POST results back to backend callback endpoint
- Backend callback: receives parsed analysis, runs persist+merge logic
- **Pros:** Full observability, each step inspectable, retry logic visual, easy to modify
- **Cons:** More endpoints needed, n8n needs network access to backend, slightly higher latency
- **Effort:** High (but most value)

### 3. Dual-write bridge pattern (Phase 1 of migration)
- Keep existing `_schedule_summarize` working AS-IS (fallback)
- Add parallel n8n webhook trigger alongside it
- n8n runs pipeline and calls back with results
- Callback endpoint compares n8n results vs local results
- Log discrepancies, measure agreement rate
- Once agreement > 99%, disable local path
- **Pros:** Zero-risk migration, verifiable, instant rollback
- **Cons:** Temporary double GPT costs, complex transient state
- **Effort:** Medium (additive, no destructive changes)

## Recommendation

**Phase 1:** Dual-write bridge (Approach 3) — run both paths in parallel, compare results.
**Phase 2:** Full pipeline in n8n (Approach 2) — once verified, n8n becomes primary.

## Integration Architecture

```
Backend (call ends)                    n8n
─────────────────                    ────
close_session()
  └─ _schedule_summarize(session_id)
       ├─ asyncio.create_task(local)   # Phase 1: keep as fallback
       └─ httpx.post(N8N_WEBHOOK_URL,  # NEW: trigger n8n
            json={session_id, client_id})
                                        ↓
                                    Webhook Trigger
                                        ↓
                                    HTTP Request → GET /internal/transcript/{sid}
                                        ↓
                                    HTTP Request → GET /internal/extraction-config/{cid}
                                        ↓
                                    Code Node → format transcript + build prompt
                                        ↓
                                    OpenAI Node → GPT-4o-mini structured output
                                        ├─ Success → POST /internal/analysis-result
                                        └─ Failure → Retry (2x) → Fallback → POST failed
                                        ↓
Backend (callback)
─────────────────
POST /internal/analysis-result
  └─ _persist_analysis(session_id, summary, facts)
       ├─ Same savepoint logic
       ├─ CallSession + CallAnalysis
       ├─ Lead merge + LeadProfileFact
       ├─ LeadInterestHistory
       └─ Auto-schedule
```

## Configuration (New Env Vars)

| Variable | Purpose | Example |
|----------|---------|---------|
| `N8N_WEBHOOK_URL` | Full URL to n8n webhook trigger | `https://n8n.qora.io/webhook/post-call-analysis` |
| `N8N_WEBHOOK_SECRET` | Shared secret for HMAC verification | (generated) |
| `N8N_ENABLED` | Feature flag (default: false) | `true` |
| `N8N_API_URL` | n8n instance API (for n8n-mcp) | `https://n8n.qora.io` |
| `N8N_API_KEY` | n8n API key (for n8n-mcp) | (from n8n settings) |

## Error Handling

- **n8n unreachable:** httpx.post with 5s timeout — log warning, local path still runs (Phase 1)
- **n8n webhook fails:** n8n has native retry — if all retries fail, POST /internal/analysis-failed
- **Callback endpoint fails:** n8n will retry the HTTP Request node
- **After cutover (Phase 2):** Retry queue with exponential backoff, alert on repeated failures

## Risks

1. **Latency increase** — n8n adds network hops. Mitigated: pipeline is fire-and-forget, no user-facing impact.
2. **Network dependency** — n8n must be reachable. Mitigated: Phase 1 dual-write keeps local fallback.
3. **Data consistency** — If callback fails after GPT succeeds. Mitigated: n8n retry + local fallback.
4. **ExtractionConfig complexity** — Dynamic model building hard in n8n. Mitigated: Backend provides pre-built prompt via API.
5. **Test regression** — 811 tests must pass. Mitigated: Feature-flagged, additive only.
6. **Double GPT costs** — During dual-write phase. Mitigated: Short verification window.
7. **Security** — Internal endpoints exposed. Mitigated: Webhook secret + network restrictions.

## Open Questions

1. Where will n8n be hosted? Same server? Separate container? Cloud?
2. What n8n version to deploy? (n8n-mcp supports 2.16.1+)
3. Authentication between n8n ↔ backend? (Shared secret HMAC? API key? mTLS?)
4. Should n8n call GPT directly (needs OpenAI key in n8n) or via backend proxy?
5. How long should dual-write verification phase last? (X calls match? Time-based?)
6. Should /internal/* endpoints be on separate port for security isolation?

## Test Strategy Considerations

- **Webhook trigger test:** Mock httpx.post, verify payload format, verify feature flag
- **Callback endpoint test:** Unit test POST /internal/analysis-result with valid/invalid payloads
- **Dual-write comparison:** Test comparison logic with matching and divergent results
- **n8n down scenario:** Test timeout handling, verify local path still executes
- **No live n8n needed:** All backend tests use mocked HTTP calls (httpx already used throughout)
- **811 existing tests:** Unaffected — n8n integration is additive behind feature flag

## Ready for Proposal
Yes — exploration complete with clear boundary map, recommended phased approach, and integration architecture. Proceed to proposal phase.
