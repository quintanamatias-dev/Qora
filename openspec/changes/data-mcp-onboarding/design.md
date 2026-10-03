# Design: Data MCP + Onboarding Harness

## Technical Approach

Two independent, additive capabilities, both new consumers of the existing service layer with zero changes to it. The data MCP server wraps `app/{clients,tenants,agents,leads,calls}/service.py` in read-only MCP tools over stdio, for internal AI callers (Claude Code, Codex, Qora's own agents) to introspect live config/data without a human running queries. The onboarding harness wraps the same service layer's write paths (client/agent/profile/integration creation) behind a declarative spec, automating the DB-and-filesystem steps of `skills/qora-client-agent-setup/SKILL.md`'s Phase 3-4 while leaving the genuinely-manual ElevenLabs-dashboard steps (Phase 1/5) as a printed checklist, not an automation target.

## Architecture Decisions

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **M-D1 — Read-only MCP, stdio, in-process, internal-only** | The official `mcp` Python SDK, stdio transport, launched as `uv run python -m app.mcp` inside `backend/`. Calls the service layer in-process against `DATABASE_URL` — no HTTP hop. No write tools. No network transport. Tools: `list_clients`, `get_client`, `list_agents`, `get_agent`, `list_leads` (client_id required), `get_lead`, `list_calls` (client_id required), `get_call`. | (a) Expose the same tools over HTTP/SSE for remote MCP clients. (b) Add write tools now, gated by a separate scope/token. (c) Build a thin HTTP client wrapper around the existing REST API instead of calling the service layer directly. | (a) is rejected because the stated caller set (Claude Code, Codex, Qora's own agent runtime) all run as local processes that can launch a stdio subprocess directly — a network transport adds auth-boundary design work (who can reach it, how is that caller authenticated) with no caller in scope today who needs it; explicitly named as future work if a remote caller appears. (b) is rejected per the parent decision: customer-scoped tokens and write tools are explicitly future work, not stubbed — building a write tool without the access-control model that should gate it (which this phase does not design) would ship an unreviewed capability. (c) is rejected because an HTTP round-trip through the existing REST API would require either a service-account bearer token (new auth surface, not justified by an internal-only, locally-launched caller) or reusing `QORA_API_KEY` in a way that conflates "programmatic external API access" with "internal introspection tool" — calling the service layer directly, in-process, is the same access pattern the API layer itself already uses, just from a second, equally-trusted entrypoint. |
| **M-D1 — Never-secrets guarantee is a response-shape test, not a convention** | Every tool's output Pydantic model is enumerated and checked by one test that no field name or type could carry a `client_secrets` ciphertext, a raw API key, or a webhook secret. `get_agent`'s "effective config with provenance" explicitly includes provenance (which config layer each field resolved from) but never a secret-shaped value — CRM API keys and webhook secrets are never part of "agent config" in the resolver's existing output shape to begin with (confirmed: `client-integrations-secrets`' `client_secrets` table is a separate read path, `resolve_client_secret`, never folded into `CRMConfig`/agent config). | (a) Rely on code review alone to catch a future secret leak. (b) Allow-list specific fields to redact, applied per-response. | (a) is rejected because the entire reason `client-integrations-secrets` (phase 3) exists is that a secret landing somewhere it shouldn't (a file, a log) is exactly the failure mode that phase was built to close structurally, not by review discipline alone — the same discipline applies here, and a structural test is cheap. (b) is rejected as strictly weaker than (a) in the chosen design: an allow-list of "fields to redact" requires someone to remember to add a new secret-shaped field to the redaction list every time one is introduced, whereas a schema-shape test that forbids secret-shaped fields entirely catches an accidental introduction without anyone remembering anything. |
| **M-D1 — client_id required for every tenant-data tool** | `list_leads`, `get_lead`, `list_calls`, `get_call` all require `client_id` as a non-optional parameter. `list_clients`/`list_agents` are the only tools that enumerate across clients, and they return identity/config shape only — never lead or call records. | (a) Allow an optional `client_id` that, when omitted, lists across every client (convenient for an internal caller who wants a global view). (b) A separate `list_all_leads`/`list_all_calls` tool explicitly for cross-tenant enumeration. | (a) is rejected because an LLM-driven caller omitting a parameter by mistake (a very real failure mode for tool-calling LLMs) must not silently become "return every client's tenant data" — requiring the parameter turns a plausible mistake into an immediate, loud validation error instead of an accidental cross-tenant data dump. (b) is rejected as unnecessary scope: no caller named in this phase (Claude Code, Codex, Qora's own agents doing per-client introspection) has a stated need for a global cross-tenant lead/call view; adding the capability without a named consumer is speculative, and the explicit-client_id rule already satisfies every named use case. |
| **M-D2 — CLI and admin endpoint share one spec schema and one service function** | `backend/app/onboarding/spec.py` defines the single Pydantic spec shape; both `python -m app.onboarding` and `POST /api/v1/admin/onboarding` parse into it and call the same `onboarding/service.py` function. No duplicated provisioning logic between the two entrypoints. | (a) Build the CLI as a thin wrapper that shells out to the HTTP endpoint. (b) Build two independent implementations, one for local/CLI use and one for the API, diverging as needed. | (a) is rejected because it would require the CLI to have network access to a running Qora instance and valid superadmin credentials just to run locally against the same DB the CLI could otherwise reach directly — disproportionate coupling for what is fundamentally a local provisioning script. (b) is rejected outright: two independent implementations of the same provisioning logic is the exact kind of duplication this program's other phases (3, 4, 5) have consistently avoided by sharing one service-layer function behind multiple entrypoints — there is no reason the CLI and the endpoint should ever disagree about what onboarding a client means. |
| **M-D2 — No secret field in the onboarding spec; secrets are a deliberate follow-up** | The spec's optional CRM config field accepts only the non-secret shape `client-integrations-secrets` already defines (`base_id`, `table_id`, `field_mappings`, etc.) — there is no field anywhere in the spec that accepts a credential value. A CRM secret, if the client needs one, is written afterward via the existing `PUT .../integrations/{provider}/secret` write-only endpoint. | (a) Accept an optional secret value in the spec and immediately forward it to the secret-write endpoint internally, saving the operator one call. (b) Accept the secret but only ever hold it in memory, never logging or persisting the spec itself. | (a) is rejected because it reintroduces exactly the risk phase 3 exists to close: an onboarding spec is a natural artifact to save to a file, paste into a ticket, or keep in shell history for reuse across clients — any one of those would land a plaintext secret somewhere unsafe. A separate, explicit follow-up call to the dedicated secret endpoint keeps the "secrets never travel through a general-purpose config/spec document" guarantee intact. (b) is rejected as a false safety: "don't log/persist the spec" cannot be guaranteed by this code once a secret is inside the spec object at all — a future logging change, an error handler that dumps the spec for debugging, or a CLI history capture are all realistic leak vectors that only not-accepting-the-field-at-all fully closes. |
| **M-D2 — Idempotent dry-run and idempotent real-run** | Dry-run validates (spec shape, vertical exists, slug/client-id uniqueness) without writing. A real run checks each entity (client, agent, profile, integration) for existence first; an already-existing entity is reported `"already exists"` in the verification checklist, not re-created or erroring. | (a) Dry-run only validates shape, not DB-state conflicts (e.g. slug collision). (b) A real re-run against an existing client raises an error rather than reporting idempotently. | (a) is rejected because the whole value of a dry-run for an onboarding operation is confidence that the *real* run will succeed — a dry-run that only checks the spec's JSON shape and ignores "does this client_id already exist" gives false confidence exactly where onboarding most often fails in practice (typo'd or reused IDs). (b) is rejected because an operator re-running the harness after a partial failure (e.g. client created, agent creation failed on a transient error) must be able to safely re-invoke the same spec and have it pick up from where it left off, not be told the client already exists as a hard stop. |

## Data Flow

```
MCP TOOL CALL (e.g. get_agent)
─────────────────────────────────────
MCP client (Claude Code / Codex / internal agent) → stdio → app/mcp/server.py
       │
       ▼
validate input (client_id, agent_slug required; Pydantic)
       │
       ▼
call existing service layer in-process (app/agents/service.py)
       │
       ▼
build response shape (effective config + provenance per field)
       │
       ▼
assert response contains no secret-shaped field (structural guarantee, not a runtime filter —
   enforced by the schema itself never defining such a field)
       │
       ▼
return to MCP client over stdio


ONBOARDING HARNESS — REAL RUN
───────────────────────────────
spec (CLI arg file or POST body) → onboarding/spec.py validation
       │
       ▼
   client exists? ──yes──► report "already exists", skip creation
       │ no
       ▼
   create client (config revision 1)
       │
       ▼
   agent exists (client_id, slug)? ──yes──► report "already exists", skip creation
       │ no
       ▼
   create agent (config revision 1)
       │
       ▼
   analysis_vertical given? ──yes──► create/attach analysis profile from vertical
       │
       ▼
   crm config given? ──yes──► create client_integrations row (non-secret fields only)
       │
       ▼
   agent.elevenlabs_agent_id set? ──yes──► trigger sync_agent_config (existing entrypoint)
       │
       ▼
build verification checklist:
   - client active revision: present?
   - agent active revision: present?
   - effective config: every required field non-null/non-empty?
   - analysis profile: attached? (if requested)
   - integration: status? (if requested)
   - EL sync: outcome? (if elevenlabs_agent_id given)
   - print manual dashboard steps (Phase 1/5 from the skill) as a follow-up checklist
       │
       ▼
return checklist to CLI stdout / POST response body


ONBOARDING HARNESS — DRY RUN
──────────────────────────────
spec → validate shape (Pydantic) → validate vertical exists (if given) →
check client_id/agent slug for conflicts → return "what would happen" report,
no row written anywhere
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/pyproject.toml` | Modify | Add `mcp` dependency |
| `backend/app/mcp/__main__.py` | Create | `python -m app.mcp` entrypoint, starts the stdio server |
| `backend/app/mcp/server.py` | Create | MCP server instance, tool registration list |
| `backend/app/mcp/tools/clients.py` | Create | `list_clients`, `get_client` |
| `backend/app/mcp/tools/agents.py` | Create | `list_agents`, `get_agent` (effective config + provenance) |
| `backend/app/mcp/tools/leads.py` | Create | `list_leads` (client_id required), `get_lead` |
| `backend/app/mcp/tools/calls.py` | Create | `list_calls` (client_id required), `get_call` (includes analysis) |
| `backend/app/mcp/schemas.py` | Create | Tool I/O Pydantic shapes; no secret-shaped field anywhere |
| `backend/app/onboarding/__main__.py` | Create | `python -m app.onboarding` CLI entrypoint |
| `backend/app/onboarding/spec.py` | Create | Declarative spec shape; CRM config field restricted to non-secret shape |
| `backend/app/onboarding/service.py` | Create | Provisioning logic + verification checklist builder, idempotent per entity |
| `backend/app/onboarding/router.py` | Create | `POST /api/v1/admin/onboarding`, superadmin-gated |
| `backend/app/main.py` | Modify | Mount the onboarding router |
| `README.md` | Modify | New section: data MCP + onboarding harness |
| `skills/qora-client-agent-setup/SKILL.md` | Modify | Point Phase 3-4 at the harness |

## Interfaces / Contracts

```python
# backend/app/mcp/schemas.py
class AgentEffectiveConfig(BaseModel):
    """get_agent's response. Every field's provenance names which config layer
    it resolved from (agent override | client default | Qora standard).
    Never includes any secret-shaped field — CRM keys/webhook secrets live in
    client_secrets, a separate table this schema has no field for."""
    agent_id: str
    client_id: str
    slug: str
    config: dict[str, EffectiveField]   # EffectiveField = {value, source_layer}


# backend/app/onboarding/spec.py
class OnboardingSpec(BaseModel):
    client_id: str
    client_name: str
    client_language: str
    agent_slug: str
    agent_name: str
    agent_goal: str
    agent_system_prompt: str
    agent_voice_id: str
    analysis_vertical: str | None = None
    crm_integration: CrmIntegrationSpec | None = None   # non-secret fields only, no credential field


class CrmIntegrationSpec(BaseModel):
    provider: str
    base_id: str
    table_id: str
    field_mappings: dict[str, str]
    # No field here accepts a secret value, by design (M-D2).


# backend/app/onboarding/service.py
async def run_onboarding(spec: OnboardingSpec, db: AsyncSession, *, dry_run: bool) -> OnboardingResult:
    """Idempotent per-entity. dry_run=True writes nothing. Returns a checklist
    naming each automated step's outcome plus the manual dashboard follow-up steps."""
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | Every MCP tool's response schema contains no secret-shaped field | A schema-inspection test enumerates every registered tool's output model and asserts no field name/type matches the secret-shape allowlist-of-forbidden-patterns (`ciphertext`, `api_key`, `secret`, `token`) |
| Unit | Tenant-data tools reject a missing client_id | `list_leads`/`get_lead`/`list_calls`/`get_call` called without `client_id` → validation error, no DB query executed |
| Unit | `get_agent` provenance is correct | Seed an agent with one overridden field and one inherited field; assert the response names the correct source layer for each |
| Unit | Output size limits | `list_leads`/`list_calls` called with a page size above the hard max → capped, not unbounded |
| Unit | Onboarding spec rejects a secret-shaped field | Attempting to construct `CrmIntegrationSpec` with an extra `api_key`/`secret` field fails Pydantic validation (`extra="forbid"`) |
| Unit | Dry-run writes nothing | Run `run_onboarding(spec, dry_run=True)` against a clean DB; assert zero rows exist in `clients`/`agents` afterward |
| Integration | Real run provisions client + agent + profile + integration | Full spec with all optional fields; assert all four entities exist with correct linkage after the run |
| Integration | Idempotent re-run | Run the same spec twice; assert the second run reports `"already exists"` for every entity, creates no duplicate rows |
| Integration | EL sync trigger only fires when elevenlabs_agent_id is set | Spec without `elevenlabs_agent_id` on the agent → no sync call attempted; spec with it set → `sync_agent_config` is called |
| Integration | CLI and endpoint produce identical results for the same spec | Run the same spec through both entrypoints (CLI against a tmp DB, endpoint via TestClient against the same tmp DB) and assert identical checklist output |

## Migration / Rollout

1. MCP scaffold + client tools — additive, new entrypoint, nothing else depends on it
2. MCP agent tools — additive
3. MCP lead/call tools — additive
4. Harness scaffold + dry-run — additive, new entrypoint
5. Harness provisioning + verification output — the first write-capable task; still net-new, no existing flow depends on it
6. Docs — README + skill pointer update

No schema migration is required by either capability — both are pure consumers of the existing service layer and existing tables.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After tasks 1-3 (MCP) | Revert PR(s) | New, separate entrypoint; nothing else invokes `python -m app.mcp` |
| After task 4 (harness scaffold) | Revert PR | New, separate entrypoint and router; nothing else invokes it |
| After task 5 (harness provisioning) | Revert PR | No existing onboarding flow depends on this; today's flow (fully manual skill) is untouched |
| After task 6 (docs) | Revert PR | Skill file content restored from git history |

## Open Questions

- [ ] Should the MCP server eventually support a remote/network transport for a non-local internal caller? Not blocking — no such caller is named in this phase; revisit if one appears.
- [ ] Should the onboarding harness's verification checklist be extended to attempt a live health-check call (matching the skill's Phase 5 steps 37-39) once the ElevenLabs-dashboard steps are confirmed done by the operator? Deferred — those steps require the dashboard configuration this harness does not perform, so an automated check would need the operator to confirm dashboard completion first; not designed in this phase.
