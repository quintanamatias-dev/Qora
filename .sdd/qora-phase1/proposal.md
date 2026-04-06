# Proposal: QORA Phase 1 — Multi-client Foundation

## Intent

QORA Phase 0 proved the core call loop works for a single hardcoded client (`quintana-seguros`).
Phase 1 makes QORA genuinely multi-tenant: each client gets their own prompt, knowledge base, and identity — while sharing one ElevenLabs agent and one backend deployment. This unblocks onboarding new brokers without code deploys.

## Scope

### In Scope
- Per-client prompt system (`backend/clients/{client_id}/prompt.md`)
- Per-client knowledge base (`backend/clients/{client_id}/knowledge.md`) injected into system prompt
- Client CRUD API (`POST/GET/PATCH /api/v1/clients`)
- Client onboarding CLI (`python -m qora.cli create-client`)
- Web demo client selector (dropdown in `index.html`)
- ElevenLabs agent routing — `client_id` resolved from initiation webhook URL params (removes hardcoded default)
- Second pilot client: `demo-inmobiliaria` (proves multi-tenancy end-to-end)
- Remove `default_client_id` workaround — proper 404 when client not found

### Out of Scope
- Client dashboard UI
- Per-client ElevenLabs accounts or agents
- Vector DB / semantic search RAG
- Billing / usage metering
- Phone call orchestration

## Capabilities

### New Capabilities
- `client-prompt-system`: Per-client markdown prompt templates loaded from filesystem, rendered into system prompt at call time
- `client-knowledge-base`: Per-client `knowledge.md` files injected as context block into system prompt
- `client-crud-api`: REST API for creating, reading, and updating client records with validation
- `client-onboarding-cli`: CLI command to scaffold new client directory structure and seed DB record
- `web-demo-client-selector`: Frontend dropdown to select active client in the web demo widget

### Modified Capabilities
- `client-routing` (existing `CAP-6`): Remove `default_client_id` silent fallback; `client_id` must be explicit in webhook URL or return 404

## Approach

### Architectural Decision 1: One Shared ElevenLabs Agent

**Decision**: Use a single ElevenLabs Conversational AI agent for all clients.

**Rationale**:
- ElevenLabs charges per agent seat — N agents = N× cost with no benefit at this stage
- The Custom LLM webhook already receives `client_id` via URL params at initiation time
- System prompt is dynamically generated per-call by our backend → persona is 100% client-controlled
- Per-client voice can be set via `client.voice_id` in DB — no need for separate agents
- Scaling to N clients = zero ElevenLabs config changes, only DB/filesystem additions

### Architectural Decision 2: Markdown Knowledge Base (No RAG)

**Decision**: Store knowledge as a flat `knowledge.md` file per client, injected verbatim into the system prompt.

**Rationale**:
- Phase 1 knowledge is small (< 2k tokens): pricing tiers, products, FAQs — fits in context window
- RAG adds infra complexity (vector DB, embeddings, retrieval) with no benefit at this scale
- Markdown is human-editable by non-technical client admins
- If knowledge grows, Phase 2 can swap the injection strategy without changing the file format

### Prompt Loading Strategy

`render_system_prompt()` will be updated to:
1. Check if `backend/clients/{client_id}/prompt.md` exists → use it as template
2. Fall back to the hardcoded `JAUMPABLO_PROMPT_TEMPLATE` (backward-compat for existing client)
3. Append `knowledge.md` contents if it exists (as a clearly delimited block)

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/prompts/insurance_agent.py` | Modified | `render_system_prompt()` reads per-client markdown files |
| `backend/clients/` | New | Directory tree: `{client_id}/prompt.md` + `knowledge.md` |
| `backend/app/tenants/router.py` | Modified | Extend to full CRUD (POST/PATCH), rename to `clients` |
| `backend/app/voice/webhook.py` | Modified | Remove `default_client_id` fallback — raise 404 explicitly |
| `backend/app/voice/initiation.py` | Modified | Remove `default_client_id` fallback — raise 404 explicitly |
| `backend/app/config.py` | Modified | Remove `default_client_id` / `broker_name` settings |
| `backend/app/static/index.html` | Modified | Add client selector dropdown |
| `backend/qora/cli.py` | New | `create-client` command scaffolds directory + seeds DB |
| `backend/clients/quintana-seguros/` | New | Migrate existing hardcoded prompt to markdown files |
| `backend/clients/demo-inmobiliaria/` | New | Second pilot client for multi-tenancy validation |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Existing `quintana-seguros` breaks during prompt migration | Med | Keep `JAUMPABLO_PROMPT_TEMPLATE` as fallback until `prompt.md` exists and is tested |
| `knowledge.md` injection exceeds context window | Low | Cap at 1500 tokens; log a warning and truncate if exceeded |
| `default_client_id` removal breaks web demo before selector is added | Med | Implement selector and routing removal in the same PR |
| Markdown template variables differ between clients | Low | CLI scaffolds a validated template with required `{variables}` |

## Rollback Plan

- Per-client markdown files are additive — removing them reverts to hardcoded prompt automatically
- `default_client_id` removal: revert `webhook.py` / `initiation.py` to restore fallback in one commit
- No DB migrations for Phase 1 — `Client` model already has `system_prompt_override` and `knowledge_base` fields (Phase 1 uses filesystem, not DB columns, but schema is unchanged)

## Dependencies

- Phase 0 complete (clients table exists, `quintana-seguros` record seeded) ✅
- ElevenLabs Conversational AI agent already configured with Custom LLM webhook ✅

## Success Criteria

- [ ] `python -m qora.cli create-client demo-inmobiliaria` creates directory structure and DB record
- [ ] Web demo dropdown allows switching between `quintana-seguros` and `demo-inmobiliaria`
- [ ] Calling with `?client_id=demo-inmobiliaria` loads the inmobiliaria prompt and knowledge, not insurance
- [ ] Calling with unknown `client_id` returns HTTP 404 (not silently falling back)
- [ ] `POST /api/v1/clients` creates a new client and returns it
- [ ] All existing tests pass after removing `default_client_id`
- [ ] `quintana-seguros` behavior is functionally identical to Phase 0 (regression-free)
