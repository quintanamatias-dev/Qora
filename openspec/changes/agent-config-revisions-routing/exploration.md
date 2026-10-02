# Exploration: Qora Config Phase 1a — Agent Config Revisions & Routing

## Survey Source

`/tmp/qora-survey-wt/docs/reports/2026-10-config-survey/build_report.py` — 46-row configuration inventory covering every place Qora configuration lives today, plus the target model, roadmap, critical-defect list, and field-level glossary used throughout this change.

## Current State: Configuration Lives in Six Places

| Location | Examples |
|----------|----------|
| Database (`agents`, `clients` tables) | `Agent.system_prompt`, `voice_id`, `tts_*`, `model`, `temperature`, deprecated `Client` agent-shaped columns |
| Repository file | `backend/clients/{client}/agents/{slug}/system-prompt.md`, `knowledge.md`, `registry.yaml` |
| ElevenLabs dashboard | Turn eagerness, soft timeout (manually set, periodically reconciled by `ElevenLabsService.sync_agent_config`) |
| Environment variables | Platform default voice/agent env vars |
| Hardcoded | `JAUMPABLO_PROMPT_TEMPLATE` fallback in `app/prompts/insurance_agent.py` |
| WorkOS | Auth/user identity, out of scope for config |

46 inventory rows total. No single source of truth; no audit trail of who changed what config and when; no way to know which config version a given call actually used.

## Target Model (from the Survey)

- **3-level inheritance**: Qora standard → Client → Agent. Standard is locked (platform-wide floor); Agent is the leaf and is the only level where `goal`/`system_prompt`/`voice_id` are mandatory. Client-level override and the full inheritance resolution are **phase 1b**, out of scope for this change.
- **Immutable versioned revisions**: every config change produces a new revision with author + timestamp; `agents` has a 1:N relationship to `agent_config_revisions` with a single active-pointer per agent. Every call stores the revision it used, so support can reconstruct exactly what config an agent spoke with on any given call.
- **ElevenLabs is a reconciled projection, not a source of truth**: Qora's DB is authoritative; `ElevenLabsService.sync_agent_config` computes a diff and PATCHes EL; `_verify_synced_config` detects dashboard drift. This mechanism (phase-0, already shipped) is reused unchanged by this slice.
- **One EL agent per Qora agent**: unique 1:1 mapping (EL bills per-minute + concurrency, not per-agent-count, so unlimited Qora agents is not an EL cost problem).
- **No default agent**: "each call identifies its agent; a client has active agents, not a main one." This is the architectural principle D1 encodes below.
- **Later-phase entities** (not touched by this change): `client_integrations`, `client_secrets`, `elevenlabs_bindings`, `skill_packages`, `skills` + skill revisions, `analysis_profiles`.

## Roadmap (Survey ROADMAP Constant)

| Phase | Scope | Status |
|-------|-------|--------|
| P0 | Quick wins (voice config propagation, EL hang-up capability) | Done — PR #178 merged as `62d80ea` |
| P1 | Agent config in DB: prompt, voice, turn-taking, tools in versioned revisions; files become a one-time import | **This change (1a pulls routing forward from P2)** |
| P2 | EL as reflection: full sync, drift detection, per-agent routing | Routing pulled forward into 1a (see rationale below) |
| P3 | Integrations / secrets | Future |
| P4 | Skill packages | Future |
| P5 | Analysis profiles | Future |
| P6 | Onboarding harness + MCP | Future |

## Decisions (Survey DECISIONS Constant)

- One configuration panel: Qora sees all clients, partners see their assigned clients, the client sees itself — plus a separate operations panel.
- Qora standards are locked; the concrete standard list is defined in phase 1 (1b), not here.
- A "partner" is a user associated with several clients.
- Internal tooling and code stay in English; client-facing deliverables are in the client's language.
- Memory = last 3 calls + lead-evidenced profile facts, placed at the END of the prompt.
- Prompt structure: fixed content first, variable content last (protects prompt caching).
- Product catalog becomes per-client in a later phase (not this one).

## Critical Defects (Survey CRITICAL Constant)

| # | Defect | Status |
|---|--------|--------|
| 1 | Voice config never reached calls | Fixed in P0 |
| **2** | **Calls always use the client's default agent — no per-agent routing** | **Fixed in this change (1a)** |
| 3 | `crm.yaml` edits lost on deploy | P3 |
| 4 | A missing client API key kills startup | P3 |
| 5 | Universal analysis hardcodes Quintana's 9 products | P5 |
| 6 | EL couldn't hang up | Fixed in P0 |

**Why defect #2 is pulled forward**: the survey roadmap originally placed per-agent routing in phase 2 (EL-as-reflection). We pull it into 1a because (a) it is the one remaining critical defect from the original six, and (b) versioned config revisions are not meaningful if every call still resolves to "the client's one true agent" — a revision only has value if it is possible to know, and control, *which agent* used it.

**Before-state evidence**: `quintana-seguros` has two agents today (`jaumpablo`, `leads-agent`) but only the `is_default` one is ever reachable by any runtime code path — the second agent exists in the DB and is invisible to every call, webhook, scheduler, or tool invocation.

## Code-Verified Facts (read before writing design decisions)

### Do call_sessions / scheduled_calls / leads already carry an agent_id?

**Yes, partially — Phase 7 already added `agent_id` columns, but every call site falls back to `is_default` when the caller does not supply one explicitly.**

- `backend/tests/unit/calls/test_agent_propagation.py`: `create_session()` accepts an explicit `agent_id`; when omitted, it resolves via `get_default_agent(session, client_id)`.
- `backend/tests/unit/scheduler/test_agent_propagation.py`: `create_scheduled_call()` accepts an explicit `agent_id`; `auto_schedule()` inherits the source session's `agent_id`, falling back to the default agent only when the session itself has none.
- `backend/app/calls/service.py:69-93` (`create_session`): `agent_id: Optional Agent UUID. When None, resolved from client's default agent.` Raises `ValueError` only when **no** default agent exists at all — never when the client has 0 defaults *or* more than one (this is the gap D2 must close for legacy routes).
- Leads do not carry an `agent_id` column; lead voice-context preview resolves an agent via `get_default_agent` at request time (`leads/router.py:812-815`).

**Conclusion**: the schema plumbing for agent-aware call/schedule records exists; what is missing is (1) every runtime entry point actually supplying an explicit `agent_id` instead of silently falling through to `is_default`, and (2) the live-call route itself being agent-scoped rather than client-scoped.

### What does the ElevenLabs conversation-initiation webhook payload give us?

`backend/app/voice/initiation.py`:

- `InitiationRequest` (lines 40-48) already declares an **optional `agent_id: str | None` field** in the payload — but it is a pre-Phase-7 case/decoration: the handler **never reads `body.agent_id`**. Agent resolution at line 110 is unconditional:
  ```python
  agent = await get_default_agent(session, resolved_client_id)
  ```
- Fields actually used from the payload: `client_id` (query param or body, required), `lead_id` (optional), `conversation_id` (optional, used for voice-context caching), `called_number` is declared on the model but is **never read** in the handler body today.
- **Correction to the task brief's assumption**: the webhook does not currently resolve the Qora agent from `agent_id` or from caller/called number — it always resolves via `get_default_agent`. D1's "initiation webhook resolves the Qora agent from the ElevenLabs agent_id" is therefore new work, not an existing capability to wire through — the field exists on the Pydantic model but the resolution logic must be added. This is reflected in design.md's affected-areas table.

### How is the custom_llm URL / extra body set?

`backend/app/voice/webhook.py:654-793`:

- Legacy global route: `@router.post("/custom-llm")` / `/custom-llm/chat/completions` / `/chat/completions` — resolves `client_id` from `elevenlabs_extra_body.client_id` → top-level `body.client_id` → `model_extra["client_id"]`, in that priority order. Every successful call to this route logs `custom_llm_legacy_route_used` with a `migration_hint` pointing at the path-based route (line 720-726) — the deprecation-marker logging infrastructure D2 requires **already exists** for this specific route and is reused, not built from scratch.
- Path-based route: `@router.post("/{client_id}/custom-llm/chat/completions")` (CAP-1, line 737) — `client_id` comes from the URL path (authoritative), with a mismatch warning if the body disagrees.
- **Both routes are client_id-scoped only. Neither route is agent-scoped today.** Inside `_process_custom_llm_request` (confirmed at `webhook.py:1026`), the per-turn agent is resolved via `agent = await get_default_agent(db, client_id)` — this is the single call site D1's agent-scoped route must replace.
- `ElevenLabsExtraBody` (webhook.py:121) carries `client_id`, `lead_id`, `conversation_id` — **no `agent_id` field exists on this model today**; adding one (or encoding agent_id in the URL path, per D1) is new work.

### How are the custom_llm URL / extra body set for outbound sync (ElevenLabsService)?

`backend/app/elevenlabs/service.py:638` (`_build_config_payload`): already fully agent-scoped — builds a PATCH payload from `agent.voice_id`, `agent.tts_model`, `agent.tts_speed`, `agent.tts_stability`, `agent.tts_similarity_boost`, `agent.soft_timeout_*`, `agent.voicemail_detection_enabled`, `agent.max_call_duration_seconds`. NULL-means-skip semantics: fields not set on the agent are omitted from the PATCH, and the function returns `{}` (caller skips the HTTP call) when every field is NULL. This sync path requires **no changes** for 1a — it is already the per-agent projection D7 reuses.

### Where does render_for_agent read system-prompt.md?

`backend/app/prompts/loader.py`:

- `load_agent_system_prompt()` (line ~222): reads `clients/{client_id}/agents/{agent_slug}/system-prompt.md`. Returns `None` if absent.
- `render_for_agent()` (line ~202-onward, confirmed near line 138 per task-brief line numbers): priority order is **(1) filesystem `system-prompt.md`, (2) `agent.system_prompt` DB column (legacy fallback), (3) filesystem `clients/{client_id}/prompt.md` or hardcoded `JAUMPABLO_PROMPT_TEMPLATE`** (legacy client fallback). The filesystem file wins over the DB column today — confirmed, matches the task brief. D6's one-time import must therefore read `system-prompt.md` when present and only fall back to `Agent.system_prompt` when the file is absent, to accurately capture "what a call actually used" as revision 1.
- `load_agent_skills()` reads `clients/{client_id}/agents/{agent_slug}/skills/registry.yaml` — confirmed unrelated to this change; registry.yaml stays on the filesystem per D5 (phase 4 scope).

## Resolution Points — Every `is_default` / Routing Call Site

| Location | Current behavior | 1a disposition |
|----------|------------------|-----------------|
| `tenants/service.py:622` `get_default_agent` (WHERE `client_id` AND `is_default` AND `is_active`) | Core resolution function | Deleted; callers migrate to explicit `agent_id` or legacy-fallback (D2) |
| `tenants/service.py:769` `set_default_agent` | Atomic default-swap | Deleted |
| `tenants/service.py:~742` deactivate guard (sole-active-default check in `deactivate_agent`) | Blocks deactivating the only active default agent | Replaced — D3 decides and justifies the new guard (see design.md) |
| `voice/webhook.py:654-740` custom-llm routes | Resolve only `client_id`, agent resolved later via default | D1: agent-scoped route added; legacy client-scoped route kept per D2 |
| `voice/webhook.py:1026` per-turn `get_default_agent` call inside `_process_custom_llm_request` | Every turn re-resolves the default agent | D1: replaced by resolving the agent once from the route/session, matching D2's legacy-fallback semantics for the old route |
| `voice/initiation.py:110` | Unconditional `get_default_agent` call; `agent_id` field on payload unused | D1: resolve from ElevenLabs `agent_id` → Qora agent mapping first |
| `scheduler/router.py:150-152` | Default-agent resolution for manual schedule creation | D1: take `agent_id` from request/lead/session; D2 fallback for legacy callers |
| `scheduler/service.py:524-526, 677-679, 1021, 1068` | Multiple default-agent resolution points across scheduling lifecycle | D1: propagate explicit `agent_id` through `auto_schedule`/retry/recontact paths (schema already supports it per Phase 7 tests) |
| `tools/schedule_followup.py:237-240` | `schedule_followup` tool resolves default agent | D1: take agent_id from the active call session |
| `leads/router.py:812-815` | Lead voice-context preview resolves default agent | D1: explicit `agent_id` param required |
| `outbound/router.py:238` | Outbound trigger resolves default agent | D1: explicit `agent_id` required, no silent default |
| `calls/service.py:75-77` | `create_session()` fallback to default agent when `agent_id` is `None` | D2: legacy-compatible fallback, but only succeeds with exactly one active agent (fails closed otherwise) |
| `voice/context.py` `build_voice_context` | Already agent-agnostic — takes an `Agent` instance as a parameter | No change — this function already works correctly for any agent, confirming the agent **resolution** points (not the context builder) are the actual defect surface |
| `elevenlabs/service.py` `sync_agent_config` | Already agent-scoped | No change (see above) |
| `seed_quintana` / `seed_qora_demo` | Only ever create/touch the default agent | Must create/activate the imported revision 1 for every seeded agent, not just the default |
| `frontend/.../agents-section.tsx` | `useMakeAgentDefault` hook + "Make default" / "Default" badge action | D3: removed from admin UI |

## Field-Level Glossary: Today → Target Level

| Field | Today | Target Level (this change encodes `1a` scope only) |
|-------|-------|------|
| `is_default` (DB column) | `agents.is_default` boolean | **Removed** from runtime semantics (D3); column drop is a later cleanup migration |
| `goal` | Missing entirely today | Agent-mandatory field — **optional in 1a**, mandatory in 1b (D5) |
| System prompt | Filesystem `system-prompt.md` wins over `Agent.system_prompt` DB column | Agent-level, DB-versioned via `agent_config_revisions`; filesystem file becomes a one-time import source only (D6) |
| `voice_id` | `agents.voice_id`, not-nullable | Agent-mandatory |
| `tts_model` / `tts_speed` / `tts_stability` / `tts_similarity_boost` | `agents.tts_*` columns | Agent-overridable |
| `model` / `temperature` / `max_tokens` | `agents.*` columns | Qora standard + per-agent override |
| `turn_eagerness` / soft timeout | Manually set in EL dashboard, periodically reconciled | Qora standard + per-agent override |
| `tools_enabled` | `agents.tools_enabled` (JSON text) | Agent-level |
| First message / conversation language | Set manually in EL dashboard | Agent-level |
| `soft_timeout_*` | `agents.soft_timeout_seconds/message/use_llm` | Agent-level |
| `voicemail_detection_enabled` / `max_call_duration_seconds` | `agents.*` columns | Agent-level |
| Deprecated `Client` agent-shaped columns (`agent_name`, `voice_id`, `system_prompt_override`, `knowledge_base`, `model`, `temperature`, `max_tokens`, `tools_enabled`) | Present on `Client` table, legacy, not read by new code | **Never read** in any path touched by this change; eliminated in a later cleanup slice |
| `analysis_language` | `clients.analysis_language` | Client-level, unaffected by this change |
| `elevenlabs_agent_id` | `agents.elevenlabs_agent_id` | Automatic 1:1 mapping, confirmed already agent-scoped |
| Platform default voice/agent env vars | `Settings.elevenlabs_agent_id` fallback (`webhook.py:88,94`) | Eliminated in a later phase — not touched by 1a (still used as a signed-URL fallback for widget mode, out of this change's scope) |

## Constraints

- SQLite remains the database; all migrations use Alembic batch mode (confirmed: `backend/alembic/versions/` uses batch-mode-compatible revisions through `20260930_0013_multi_tenant_auth`, the current head).
- No SSH access to Railway production — all verification happens via API calls, never direct DB/file inspection on the server.
- Production data is test-only (no real customer PII at stake in today's prod DB).
- Telnyx (real telephony) is blocked in this environment — live-call verification uses ElevenLabs' `simulate-conversation` API instead of a real phone call.
- All internal code, comments, and documentation are in English per project convention.

## Ready for Proposal

Yes — the exploration confirms the task brief's factual assumptions with two corrections (the initiation webhook payload already *declares* `agent_id` but does not *use* it; the `is_default`-based routing gap spans more call sites than just the live-call route, several of which already accept — but do not require — an explicit `agent_id`). Both corrections are reflected in the design and resolution-point table above. Proceed to proposal.md, design.md, tasks.md, and the two capability specs.
