# Proposal: Qora Config Phase 6 — Data MCP + Onboarding Harness

## Intent

Today, inspecting Qora's own data — which clients exist, what an agent's effective config resolves to, which leads a client has, how a call analyzed — requires either direct DB access or going through the panel/API with a human in the loop. There is no way for Qora's own AI tooling (Claude Code, Codex, or a future Qora agent) to ask "what does client X's leads-agent actually resolve to right now" without a human running queries by hand. Separately, onboarding a new client end-to-end is a fully manual, 41-step checklist (`skills/qora-client-agent-setup/SKILL.md`) spanning the ElevenLabs dashboard, `.env` edits, DB rows, and filesystem files — error-prone, slow, and undocumented in any automatable form beyond the skill file itself.

This change adds two independent, additive capabilities: (1) a **read-only MCP server** exposing Qora's service layer as structured tools for internal AI callers — never secrets, always explicit `client_id` scoping, in-process against the same `DATABASE_URL` the API uses — and (2) an **onboarding harness** (CLI + admin endpoint) that takes a declarative client/agent spec and performs the DB-side steps the skill's Phase 3-4 checklist currently requires a human to do by hand, then returns a verification checklist covering both what it automated and the ElevenLabs-dashboard steps it cannot.

## Scope

### In Scope

**Data MCP (M-D1)**
- A read-only MCP server (official `mcp` Python SDK, new `backend/pyproject.toml` dependency), stdio transport, launched as `uv run python -m app.mcp` from inside `backend/`.
- Runs in-process against `DATABASE_URL` — calls the existing service layer (`app/{clients,tenants,agents,leads,calls}/service.py`) directly, no HTTP hop, no new auth boundary beyond "whoever can launch this process has DB read access" (internal-only: Qora's own agents, Claude Code, Codex — not exposed to any customer-facing surface).
- Tools: `list_clients`, `get_client`, `list_agents`, `get_agent` (effective config with provenance — which layer each field resolved from, e.g. agent override vs. client default vs. Qora standard), `list_leads` (requires `client_id`, supports filters + pagination), `get_lead`, `list_calls` (requires `client_id`), `get_call` (includes post-call analysis).
- **Never returns secrets** — no tool touches `client_secrets`, API keys, webhook secrets, or any encrypted/raw-credential field, at any layer of any response.
- Every tool touching tenant-scoped data requires an explicit `client_id` parameter — no tool enumerates across all clients' tenant data implicitly (`list_clients`/`list_agents` are the only cross-client listings, and they return only client/agent identity + config shape, never lead/call data).
- Output size limits on every tool (pagination defaults, a hard max page size) so a single call cannot return an unbounded result set into an LLM context.
- Customer-scoped tokens and any write tool are explicit, named future work — not built, not stubbed, in this phase.

**Onboarding Harness (M-D2)**
- `uv run python -m app.onboarding` CLI and `POST /api/v1/admin/onboarding` (superadmin-gated), both taking the same declarative spec: client `id`/`name`/`language`; agent `slug`/`name`/`goal`/`system_prompt`/`voice_id`; optional `analysis_vertical`; optional CRM provider config (shape only, never a secret value inline).
- Performs: create the client (config revision 1), create the agent (revision 1), create the analysis profile from the named vertical if given, create an integration row if CRM config is given (non-secret fields only — a secret, if needed, is a separate, explicit step per `client-integrations-secrets`' own write-only secret endpoint, never embedded in the onboarding spec), trigger an ElevenLabs sync when the agent already has an `elevenlabs_agent_id` set.
- Returns a verification checklist: active revision present for both client and agent, effective config resolves completely (no missing required field), analysis profile attached (if requested), integration status (if requested), ElevenLabs sync status (if an `elevenlabs_agent_id` was given) — plus the manual ElevenLabs-dashboard steps from `skills/qora-client-agent-setup/SKILL.md`'s Phase 1/Phase 5, printed as a checklist, since those remain genuinely manual (confirmed by the skill's own "Automatable vs Requires Dashboard" table).
- Idempotent dry-run mode: validates the spec and reports what would be created/changed without writing anything.

**Docs (M-D3, deferred to a task)**
- A README section describing both tools' existence and invocation.
- An update to `skills/qora-client-agent-setup/SKILL.md` pointing operators at the harness for Phase 3-4 steps, keeping Phase 1/2/5 (genuinely manual/dashboard/env) as-is.

### Out of Scope

- Any write tool on the MCP server — the server is read-only in this phase; a future phase may add customer-scoped tokens and scoped write tools, named explicitly as future work, not designed here.
- The MCP server exposing itself over HTTP/SSE or any network transport — stdio only, matching "internal callers running the process locally" (Claude Code, Codex, a future internal Qora agent runtime).
- Automating the ElevenLabs-dashboard-only steps (agent creation, voice selection, Custom LLM URL, initiation webhook, first message, phone number resource, post-call webhook secret) — the skill's own table already marks these "No — Dashboard only"; the harness's verification checklist prints them as a manual follow-up, it does not attempt them.
- Automating `.env` edits (API keys, `ENABLE_OUTBOUND_CALLS`, webhook secrets) — these are deploy-environment concerns outside the harness's DB-and-filesystem scope; the checklist names them, the harness does not write them.
- Secret values inside the onboarding spec — a CRM secret, if the client needs one, is written through `client-integrations-secrets`' own write-only endpoint as a deliberate follow-up step, never accepted as a plaintext field in the onboarding spec (which would otherwise risk landing a secret in a CLI history, a request log, or a spec file checked into a repo).
- Rewriting `skills/qora-client-agent-setup/SKILL.md` wholesale — only the pointer update (M-D3) is in scope; the skill's Phase 1/2/5 manual content stays.

## Capabilities

> This section is the CONTRACT between proposal and specs phases.

### New Capabilities

- `data-mcp`: the read-only MCP server, its stdio transport and in-process service-layer wiring, its tool set (`list_clients`/`get_client`/`list_agents`/`get_agent`/`list_leads`/`get_lead`/`list_calls`/`get_call`), the never-secrets guarantee, the explicit-`client_id`-required rule for tenant data, and output size limits.
- `onboarding-harness`: the declarative onboarding spec shape, the CLI + admin-endpoint pair, the DB-side provisioning steps it performs (client/agent/analysis-profile/integration creation, EL sync trigger), the idempotent dry-run mode, and the verification-checklist output including the printed manual-steps follow-up.

### Modified Capabilities

- None. Both capabilities are additive, read-only (MCP) or write-but-idempotent-and-net-new (harness); neither supersedes an existing spec requirement.

## Approach

**MCP server and onboarding harness are independent tracks; within each, read/list tools first, then detail tools, then the harness's provisioning steps, then its verification output, then docs**:

1. MCP: server scaffold (stdio transport, in-process service-layer wiring) + `list_clients`/`get_client`
2. MCP: `list_agents`/`get_agent` (effective config with provenance)
3. MCP: `list_leads`/`get_lead`/`list_calls`/`get_call` (client_id-required, pagination, output limits)
4. Harness: spec schema + CLI/endpoint scaffold + dry-run validation
5. Harness: provisioning steps (client, agent, analysis profile, integration, EL sync trigger) + verification checklist output
6. Docs: README section + `skills/qora-client-agent-setup/SKILL.md` pointer update

## Affected Areas

| Area | Impact | Description |
|------|--------|--------------|
| `backend/pyproject.toml` | Modified | Add `mcp` (official Python SDK) dependency |
| `backend/app/mcp/__init__.py`, `backend/app/mcp/__main__.py` (new) | New | `python -m app.mcp` entrypoint, stdio transport setup |
| `backend/app/mcp/server.py` (new) | New | MCP server instance, tool registration |
| `backend/app/mcp/tools/clients.py`, `agents.py`, `leads.py`, `calls.py` (new) | New | One module per tool group, each calling the existing service layer in-process |
| `backend/app/mcp/schemas.py` (new) | New | Tool input/output Pydantic shapes — no secret fields anywhere |
| `backend/app/onboarding/__init__.py`, `backend/app/onboarding/__main__.py` (new) | New | `python -m app.onboarding` CLI entrypoint |
| `backend/app/onboarding/spec.py` (new) | New | Declarative onboarding spec Pydantic shape (client, agent, optional analysis vertical, optional CRM config — no secret field) |
| `backend/app/onboarding/service.py` (new) | New | Provisioning logic: create client/agent/profile/integration, trigger EL sync, build the verification checklist |
| `backend/app/onboarding/router.py` (new) | New | `POST /api/v1/admin/onboarding` (superadmin-gated), reuses `onboarding/service.py` |
| `backend/app/main.py` | Modified | Mount the onboarding router |
| `README.md` | Modified | New section describing both tools |
| `skills/qora-client-agent-setup/SKILL.md` | Modified (deferred task) | Point Phase 3-4 at the onboarding harness; Phase 1/2/5 unchanged |

## Safety Model

1. **The MCP server never returns a secret, at any layer** — no tool's response schema includes a `client_secrets` field, an encrypted/raw credential, or a webhook secret; this is a response-shape guarantee verified by an explicit test asserting no tool's Pydantic output model contains a field that could carry secret-shaped data.
2. **Tenant-scoped data always requires an explicit client_id** — `list_leads`/`get_lead`/`list_calls`/`get_call` reject a call missing `client_id`; there is no "list every client's leads" tool and no implicit cross-tenant default.
3. **The MCP server is read-only — structurally, not just by convention** — no tool in this phase calls a service-layer function that mutates state; the tool registry itself is reviewed to confirm every registered tool maps to a read-only service function.
4. **The onboarding harness never accepts a secret value in its spec** — the spec schema has no field shaped like a credential; a CRM secret, when needed, is a deliberate, separate follow-up call to the existing write-only secret endpoint, keeping the "secrets never land in a spec file, a CLI argument, or a request log" guarantee the rest of the config-refactor program already established (phase 3).
5. **The harness is idempotent and dry-run-safe** — dry-run mode performs every validation step (spec shape, vertical exists, slug uniqueness) without writing any row; a real run that is re-invoked against an already-provisioned client/agent reports "already exists" per entity rather than erroring or duplicating.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| A future tool addition to the MCP server accidentally exposes a secret-shaped field | Med | The never-secrets response-shape test (Safety Model #1) runs against every registered tool's output schema, not just the ones built in this phase — any future tool addition is caught by the same test |
| The MCP server's in-process DB access becomes a second, divergent code path from the HTTP API for the same data | Low | Every tool calls the existing service layer directly (no new query logic) — the MCP server is a new transport/consumer, not a new data-access implementation |
| The onboarding harness's "effective config resolves completely" verification check gives a false "complete" for a field that is technically present but semantically wrong (e.g. an empty string) | Low | The verification checklist defines "complete" per-field (non-null AND, where applicable, non-empty) explicitly in the spec, not left to an implicit truthiness check |
| An operator pastes a secret into the onboarding spec's CRM config field anyway, despite the schema not having a dedicated field for it | Low | The CRM config field in the spec schema only accepts the shape `client-integrations-secrets` already defines as non-secret (base_id, table_id, field_mappings) — there is no generic free-text field a secret could be smuggled into |

## Rollback Plan

- **MCP server (tasks 1-3)**: the entire capability is a new, separate entrypoint (`python -m app.mcp`) not invoked by the existing FastAPI app or any existing process — reverting the PR(s) removes the module; nothing else depends on it.
- **Onboarding harness scaffold + dry-run (task 4)**: new, separate entrypoint and router; reverting removes the CLI/endpoint, no other code calls it.
- **Harness provisioning (task 5)**: revert the PR; no existing onboarding flow depends on this capability (today's flow is the fully manual skill checklist, untouched).
- **Docs (task 6)**: revert the PR; the skill file's prior content is restored from git history.

## Dependencies

- New third-party dependency: the official `mcp` Python SDK.
- Depends on the existing service layer under `backend/app/{clients,tenants,agents,leads,calls}/service.py` — no changes to that layer are required or made by this change; both new capabilities are pure new consumers of it.
- Depends on `skills/qora-client-agent-setup/SKILL.md`'s existing documented manual steps as the source of truth for the harness's provisioning scope and its printed manual-follow-up checklist.
- Independent of `elevenlabs-reconciler` — no shared tables, no shared code paths; the harness's "trigger EL sync" step calls the existing `sync_agent_config`/`sync_to_elevenlabs` entrypoints unchanged.

## Review / Deployment Strategy

Six task groups, each sized to review within a single PR (~≤400 changed lines target): (1) MCP scaffold + client tools, (2) MCP agent tools, (3) MCP lead/call tools, (4) harness scaffold + dry-run, (5) harness provisioning + verification output, (6) docs. See tasks.md for the full forecast and per-task RED/GREEN/rollback detail.

## Success Criteria

- [ ] `python -m app.mcp` starts a stdio MCP server exposing all eight listed tools
- [ ] No tool's response schema can carry a secret-shaped field — verified by an explicit schema-inspection test
- [ ] Every tenant-data tool rejects a call missing `client_id`
- [ ] `python -m app.onboarding` and `POST /api/v1/admin/onboarding` accept the same spec shape and produce the same provisioning result
- [ ] Dry-run mode performs full validation and writes nothing
- [ ] A real onboarding run produces a client with an active config revision, an agent with an active config revision, and (when requested) an analysis profile and an integration row — plus a verification checklist naming every automated step's status and every remaining manual dashboard step
- [ ] Re-running the harness against an already-provisioned client/agent is idempotent — no duplicate rows, no error, a clear "already exists" per entity
- [ ] README and `skills/qora-client-agent-setup/SKILL.md` both reference the harness for Phase 3-4 steps
- [ ] Full backend test suite passes before closing the change

## Next Recommended Phase

**sdd-tasks** → the six-task breakdown in `tasks.md`. See `specs/data-mcp/spec.md` and `specs/onboarding-harness/spec.md` for the behavioral contracts.
