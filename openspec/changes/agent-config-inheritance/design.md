# Design: Qora Config Phase 1b — Standard/Client/Agent Inheritance

## Technical Approach

Layer a three-level inheritance model on top of 1a's `AgentConfigV1`/`agent_config_revisions` (D1–D8): a code-defined, versioned `AgentConfigStandard` (the floor), a new `client_config_revisions` layer (shared across a client's agents, reusing 1a's revision mechanics), and 1a's existing agent revisions — now sparse overrides (`AgentConfigV2`) instead of full snapshots. A single field-policy registry gives every field exactly one policy, and a pure `resolve_effective_config` function computes the value a call actually uses plus which level it came from. 1a's immutability, routing, and EL-sync mechanics are reused unchanged; this slice only changes *what a revision contains* and *how it resolves*, not *how revisions are created, activated, or synced*.

## Architecture Decisions

Decisions continue 1a's numbering (D1–D8 are defined in `agent-config-revisions-routing/design.md`); this slice adds D9–D16.

| Decision | Choice | Alternatives Rejected | Rationale |
|----------|--------|------------------------|-----------|
| **D9 — Three levels, one policy per field** | Qora standard → Client → Agent. Every `AgentConfigV1` field (1a) gets exactly one policy from the registry: `locked` (standard only, no override anywhere), `overridable` (Qora default, client may override, agent may override the client), `client_only` (set at client level, inherited by every agent, not overridable per agent), `agent_required` (no default at any level — must be set per agent: `system_prompt`, `goal`, `voice_id`). | (a) A single "overridable: yes/no" boolean per field. (b) Per-field policy decided ad hoc at write time instead of a registry. | (a) collapses `client_only` and `agent_required` into one bucket, losing the distinction between "a client sets this once for all its agents" (e.g. conversation language) and "every agent must set this itself" (e.g. `voice_id` — two agents sharing a client should not share a voice by default). (b) makes the policy un-auditable and lets a bug silently change what "locked" means for one field but not another; a registry is reviewable in one PR diff. |
| **D10 — Standard lives in code, not the DB** | `AgentConfigStandard` is a versioned Python module with a `STANDARD_VERSION` string literal. No database table backs it; no API or panel can write to it. Every call records the `standard_version` active when it ran. | (a) A DB table editable by superadmin, gated by a permission check. (b) A DB table with no UI but an internal-only API. | (a) and (b) both still allow *some* write path to exist, which means "no panel touches it" is a promise enforced by a permission check someone could get wrong — not a guarantee. Code review is Qora's existing change-control mechanism for everything else platform-wide (plans catalog, retry constants); the standard is no different, and PR review is strictly more auditable than a DB write with an audit-log side table. |
| **D11 — Client-level revisions, reusing 1a's mechanics** | New table `client_config_revisions` (same shape as 1a's `agent_config_revisions`: insert-only, `revision_number` monotonic per client, `source` enum, `created_by`, `created_at`, `note`) + `clients.active_config_revision_id`. Client config rows store sparse overrides only — fields the client has actually set, not a full copy of the standard. | (a) A generic `config_revisions` table parameterized by owner type (`client` \| `agent`), one table for both levels. (b) Client overrides stored as a single mutable JSON column on `clients`, no revision history. | (a) was considered — "reusing generic mechanics where cheap" is explicitly requested — but was rejected because the two levels have different consumers (client revisions feed every one of that client's agents; agent revisions feed one agent) and different propagation triggers (D15), and a shared table would need a nullable `agent_id` XOR nullable client-only marker, which is a worse shape than two small tables with an identical *pattern* but no forced coupling. The *service-layer functions* (`create_revision`, `activate_revision`, `rollback_to_revision`) ARE reused as generic helpers parameterized by table/model — that is the cheap reuse this decision targets. (b) loses the audit trail D4 (1a) established as non-negotiable for agent config; there is no reason client config deserves a weaker guarantee. |
| **D12 — AgentConfigV2 sparse overrides; V1 stays frozen** | Agent revisions created AFTER this change use `AgentConfigV2` (`schema_version=2`): only the fields the agent has explicitly overridden relative to the resolved client/standard value. All of 1a's existing `AgentConfigV1` (`schema_version=1`) revisions stay exactly as recorded — full snapshots, no inheritance awareness — and remain readable forever. No migration converts V1 rows to V2. | (a) Migrate every V1 revision to V2 by dropping fields equal to the newly-resolved inherited value. (b) Keep V1 as the only schema and simulate "sparse" by convention (nulls mean inherit). | (a) is explicitly the unsafe option the task brief flagged: computing "equal to the inherited value" requires the NEW resolver and the NEW standard to already exist and be correct at migration time — any bug in either one silently corrupts history that used to prove what a past call actually used, which is the entire point of 1a's immutability guarantee. The safer option — do not touch history, write V2 going forward — is chosen specifically so the hard acceptance criterion ("effective config unchanged for every existing agent") can be verified by comparing against 1a's actual V1 rows, not against a migration's guess. (b) was 1a's `AgentConfigV1` field defaults (e.g. `language: str | None = None`) which cannot distinguish "explicitly set to the client's default" from "never set, inherit" — a real schema_version bump is needed, not a convention. |
| **D13 — Resolver with provenance, call-time attribution** | `resolve_effective_config(standard, client_overrides, agent_overrides) -> EffectiveConfig` is a pure function (no DB, no IO) returning, per field, the resolved value AND its provenance (`standard` \| `client` \| `agent`). Used identically by `build_voice_context`, the EL projection payload builder, and the admin `GET .../effective-config` endpoint. Every call session stores `standard_version` + `client_config_revision_id` + `agent_config_revision_id` (the last one already exists per 1a). No separate effective-config snapshot/hash is stored per call. | (a) Store a full effective-config JSON blob (or hash of one) per call session. (b) Compute effective config differently in each of the three consumers (runtime, sync, API). | (a) is redundant: `standard_version` + both revision ids are together sufficient to reconstruct the exact effective config for any past call, by construction, because the resolver is pure and deterministic — a stored snapshot would be a cache that could drift from what the three ids actually resolve to if the resolver's logic ever changes, which is a worse failure mode than recomputing on demand (recomputing is cheap — all three inputs are already in memory at call time). (b) is rejected on the same principle as 1a's single-sync-mechanism decision (D7, 1a): three independent implementations of the same resolution logic WILL drift; one pure function used by all three consumers cannot. |
| **D14 — Write validation: locked and required fields** | Setting a `locked` field at client or agent level returns 422 with the exact field list. Creating a NEW agent revision missing an `agent_required` field (`system_prompt`, `goal`, `voice_id`) returns 422. Agents that existed before this change without `goal` (it did not exist as a field until 1a, and was optional in 1a) are grandfathered: their current active revision keeps working, the admin API/UI marks them `"incomplete"`, and any NEW revision for that agent must include `goal`. Creating a brand-new agent (not a revision on an existing one) always requires every `agent_required` field — no grandfathering for net-new agents. | (a) Block the grandfathered agents from receiving ANY new revision until `goal` is backfilled. (b) Synthesize a placeholder `goal` for grandfathered agents so validation never has to special-case them. | (a) would turn a backward-compatibility accommodation into an operational trap — an unrelated config fix (e.g. a voice tweak) for an old agent would be blocked on an unrelated field nobody asked about yet, which is worse than today's behavior. (b) hides a real data gap behind a fake value; "incomplete" visible in the UI is more honest and matches 1a's own precedent of surfacing gaps loudly (D2, 1a: fail-closed and visible, never a silent guess) rather than papering over them. |
| **D15 — Propagation: client changes auto-sync, standard changes require an explicit action** | Activating a new client revision immediately re-resolves and re-syncs (EL projection) every active agent of that client, reusing 1a's existing per-agent sync status mechanism. A new `STANDARD_VERSION` deploy does NOT automatically re-sync anyone; re-syncing after a standard bump requires an explicit admin endpoint, with drift detection comparing each agent's last-synced config against its freshly-resolved one before acting. | (a) Both client and standard changes auto-sync immediately. (b) Neither auto-syncs; both require the explicit admin action. | (a) means a code deploy (standard bump) could silently fan out an API-rate-limited burst of PATCH calls to ElevenLabs across every client in production the moment a PR merges — the exact "deploy-time API storm" the task brief calls out to avoid. A client-level change, by contrast, is a human explicitly editing one client's config right now and expecting it to take effect, matching the UX 1a already shipped for agent-level PATCH-then-sync. (b) would make every standard-driven improvement (e.g. a better default prompt phrase) invisible until someone remembers to click a button, and more importantly would make client-level edits feel broken compared to 1a's existing agent-level behavior, which syncs immediately on PATCH. |
| **D16 — Language policy** | Internal tooling/code/comments stay in English always (platform-wide, not a field). Conversation language and analysis/deliverable language are `client_only`: set once per client, inherited by every agent of that client, not overridable per agent by default. An agent MAY override conversation language only through a Qora-reviewed field-policy change for that specific agent (not a self-service panel toggle) — documented as an open question below, not built in this slice. | (a) `language` is `overridable` by default, like `tts_model`. (b) `language` is `locked` (one language platform-wide). | (a) is rejected because most clients run every agent in one language, and an accidental per-agent language override (e.g. someone pastes a Spanish prompt into the English-labeled field) is far more likely than a deliberate one — `client_only` makes the common case the only self-service case, and an uncommon one (a client genuinely needing one multilingual agent) explicit and reviewed rather than one dropdown click away. (b) is rejected because clients legitimately serve different markets (confirmed: analysis language is already a per-client column, `clients.analysis_language`, inherited today) — a platform-wide single language is factually wrong for a multi-client platform. |

## Field-Policy Table

Every `AgentConfigV1` field from 1a (`agent-config-revisions-routing/design.md` D5), plus the Qora standards enumerated from code and the survey that were previously enforced only by convention, hardcoded values, or env vars. This table is the "concrete list of Qora standards" the 1a survey deferred to phase 1b.

### 1a `AgentConfigV1` fields — policy assignment

| Field | Policy | Qora standard value | Rationale |
|-------|--------|----------------------|-----------|
| `system_prompt` | `agent_required` | — (no default) | Carries the agent's entire behavior; two agents of one client legitimately need different prompts (D1, 1a's original routing fix exists precisely because a second agent needs its own voice) |
| `goal` | `agent_required` | — (no default); grandfathered for pre-1b agents (D14) | Same reasoning as `system_prompt` — a goal-less agent has no measurable success criterion; 1a left it optional only because it did not yet exist as a concept |
| `voice_id` | `agent_required` | — (no default) | Confirmed in code: `Agent.voice_id` is `nullable=False` with no column default — the schema already treats it as mandatory; this policy formalizes that |
| `tts_model` | `overridable` | `eleven_v4_turbo` | Confirmed in test fixtures (`tests/unit/elevenlabs/test_tts_sync.py`) as the model currently synced to production agents. **Contradiction**: the `Agent.tts_model` DB column default is `eleven_flash_v2_5` (confirmed in `tenants/models.py`) — the Qora standard default is being SET to the architect-specified production value here, not imported from today's column default; see Open Questions |
| `tts_speed` | `overridable` | `0.95` | Matches both `Agent.tts_speed` column default and `Settings.elevenlabs_speed` (confirmed, `core/config.py`) |
| `tts_stability` | `overridable` | `0.4` | Matches `Agent.tts_stability` column default and `Settings.elevenlabs_stability` |
| `tts_similarity_boost` | `overridable` | `0.75` | Matches `Agent.tts_similarity_boost` column default and `Settings.elevenlabs_similarity_boost` |
| `model` (LLM) | `overridable` | `gpt-4.1-mini` | Architect-specified production value: OpenAI Tier 1 gives `gpt-4o` only 30k TPM, insufficient for concurrent call volume. **Contradiction**: the `Agent.model` DB column default is `gpt-4o` (confirmed in `tenants/models.py` and `core/config.py`'s `openai_model`) — same pattern as `tts_model`: the standard is being set here, not imported; see Open Questions |
| `temperature` | `overridable` | `0.7` | Matches `Agent.temperature` column default |
| `max_tokens` | `overridable` | `300` | Matches `Agent.max_tokens` column default |
| `tools_enabled` | `overridable` | `["get_lead_details"]` | Matches `Agent.tools_enabled` column default; each client's agents legitimately need different tool sets (quoting, scheduling, etc.) |
| `first_message` | `overridable` | `None` (empty — EL speaks first via its own greeting) | Confirmed: survey inventory notes the first message is "manual (vacío hoy)" — empty is today's de facto floor |
| `language` (conversation) | `client_only` | — (no platform default; set per client) | D16 |
| `turn_eagerness` | `overridable` | `"normal"` | Confirmed resolved in Phase 0 (survey PHASE0 table: "Turnos menos agresivos — Juanma pasó de «eager» a «normal»"); `"eager"` was the pre-Phase-0 problem, not the standard |
| `soft_timeout_seconds` | `overridable` | `None` (NULL = use EL dashboard default, no PATCH sent) | Confirmed: `Agent.soft_timeout_seconds` column comment states "NULL = use ElevenLabs dashboard defaults — no PATCH is sent" |
| `soft_timeout_message` | `overridable` | `None` | Same NULL-means-skip semantics as above |
| `soft_timeout_use_llm` | `overridable` | `None` | Same NULL-means-skip semantics as above |
| `voicemail_detection_enabled` | `overridable` | `true` | No agent should talk into a voicemail by default; a client/agent may still disable it for a flow that intentionally leaves voicemail messages |
| `max_call_duration_seconds` | `overridable` | `120` | Confirmed: `tenants/service.py` sets `agent.max_call_duration_seconds = 120` as the fallback default in two places. Platform-wide bounds `30 ≤ value ≤ 7200` (confirmed in `agents/schemas.py` field validators) remain a hard validation ceiling/floor regardless of override — this is not a separate inheritance field, it is a locked constraint on the overridable field's range |

### New locked Qora standards (not in 1a's `AgentConfigV1`, fixed today in code/env)

| Standard | Policy | Qora standard value | Rationale |
|----------|--------|----------------------|-----------|
| `end_call_tool_enabled` | `locked` | `true` (always forwarded as an EL system tool) | Confirmed critical defect #6 (survey) — resolved in Phase 0; an agent unable to hang up is a compliance/UX failure, not a per-client preference |
| `analysis_model` | `locked` | `gpt-4o-mini` | Confirmed `Settings.openai_model_fast` default, used directly in `summarizer.py:645` for post-call analysis; analysis consistency and cost control are platform concerns, not a per-client knob |
| `memory_window_calls` | `locked` | `3` | Confirmed survey decision ("las últimas 3 llamadas rotan") and `memory.py`'s rotation logic; memory depth affects prompt-caching cost platform-wide |
| `memory_profile_facts_placement` | `locked` | `"end of prompt, after memory, lead-evidenced facts only"` | Confirmed survey decision: profile facts enter the prompt "categorized and at the end ... only if the evidence is something the person said" |
| `prompt_assembly_order` | `locked` | `"fixed content first, variable content (lead data, memory, time) last"` | Confirmed survey decision explicitly tied to OpenAI prompt caching: "OpenAI caches the start of the prompt; any variable data cuts the cache from that point on" |
| `load_skill_force_injection` | `locked` | `"load_skill tool always present when the agent has a skills registry.yaml"` | Confirmed in `voice/webhook.py`'s tool-dispatch logic (cache short-circuit + filler handling built around `load_skill` specifically, not a configurable tool) |
| `elevenlabs_system_tool_passthrough` | `locked` | `"forward every EL system tool not already claimed by a Qora tool name"` | Confirmed in `webhook.py`'s `_merge_passthrough_tools` — "Qora tools always win on name collisions"; this merge rule is a platform tool contract, not a per-agent setting |
| `technical_retry_max_attempts` | `locked` | `2` | Confirmed `scheduler/service.py`'s `_TECH_RETRY_MAX_ATTEMPTS = 2` — "Qora-owned technical retries, separate from recontact"; a platform reliability constant, not a client-tunable recontact policy (recontact itself — `scheduler_max_attempts` — is already a `Client` column and stays client-level, unaffected by this change) |
| `max_call_duration_seconds_bounds` | `locked` | `floor=30, ceiling=7200` | Confirmed `agents/schemas.py` Pydantic field validators (`ge=30, le=7200`) on every schema that accepts this field; this is the hard bound on the `overridable` field above, not an independent field |
| `post_call_webhook_secret_required` | `locked` | `enforced when QORA_WEBHOOK_AUTH_ENABLED=true` (operator/infra toggle, never client/agent-exposed) | Confirmed `Settings.qora_webhook_secret` / `qora_webhook_auth_enabled`; this is an operational security floor, not a per-client configurable |

## Data Flow

```
RESOLUTION (used by runtime, EL sync, and the admin API identically)
──────────────────────────────────────────────────────────────────
AgentConfigStandard (code, STANDARD_VERSION pinned)
       │
       ▼
load client's active_config_revision → ClientConfigRevision.config (sparse overrides)
       │
       ▼
load agent's active_revision_id → AgentConfigRevision.config
   (schema_version=1 → full snapshot, legacy; schema_version=2 → sparse overrides)
       │
       ▼
resolve_effective_config(standard, client_overrides, agent_overrides)
   → EffectiveConfig { field: (value, provenance) }
       │
       ├──► build_voice_context()  — runtime prompt/TTS/model assembly
       ├──► ElevenLabsService._build_config_payload()  — EL projection sync
       └──► GET /agents/{id}/effective-config  — admin API, provenance badges


WRITE PATH — CLIENT LEVEL
──────────────────────────
PATCH /clients/{client_id}/config
       │
       ▼
validate: reject any `locked` field present in the payload (422, field list)
       │
       ▼
create_revision(client_id, overrides, source="api")   ← reuses 1a's generic helper
       │
       ▼
activate_revision(client_id, new_revision_id)
       │
       ▼
for each active agent of this client:                  (D15)
    re-resolve effective config
    enqueue EL projection sync (reuses 1a's sync mechanism, per agent)


WRITE PATH — AGENT LEVEL
─────────────────────────
PATCH /agents/{agent_id}/config
       │
       ▼
validate: reject any `locked` field (422); reject missing `agent_required`
          field on a NEW agent, or on any revision for a non-grandfathered agent (422)
       │
       ▼
create_revision(agent_id, overrides, source="api", schema_version=2)
       │
       ▼
activate_revision(agent_id, new_revision_id)
       │
       ▼
enqueue EL projection sync (1a's mechanism, unchanged)


STANDARD VERSION BUMP (code deploy)
────────────────────────────────────
Deploy ships new AgentConfigStandard.STANDARD_VERSION
       │
       ▼
NO automatic re-sync (D15)
       │
       ▼
Admin explicitly calls POST /admin/standards/resync
       │
       ▼
for each active agent platform-wide:
    re-resolve effective config against the NEW standard
    compare against last-synced-config (drift check)
    enqueue EL projection sync only for agents whose resolved config actually changed
```

## File Changes

| File | Action | Description |
|------|--------|--------------|
| `backend/app/tenants/config_standard.py` | Create | `AgentConfigStandard` dataclass/module with every `locked` field's value; `STANDARD_VERSION: str` |
| `backend/app/tenants/field_policy.py` | Create | `FIELD_POLICY: dict[str, Literal["locked","overridable","client_only","agent_required"]]` — the registry table above, as code |
| `backend/app/tenants/config_resolver.py` | Create | `resolve_effective_config(...)`, `EffectiveConfig`, `FieldProvenance` — pure, no DB/IO imports |
| `backend/app/tenants/models.py` | Modify | `ClientConfigRevision` model; `Client.active_config_revision_id` FK; `AgentConfigRevision.schema_version` gains `2`; `CallSession` gains `standard_version`, `client_config_revision_id` |
| `backend/alembic/versions/{rev}_client_config_revisions_schema.py` | Create | `CREATE TABLE client_config_revisions`; `clients.active_config_revision_id`; `call_sessions` new columns (batch mode, chained after 1a's head) |
| `backend/app/tenants/agent_config_schema.py` | Modify | Add `AgentConfigV2` (sparse, `schema_version=2`); `AgentConfigV1` unchanged |
| `backend/app/tenants/revisions_service.py` | Modify | `create_revision` validates against `FIELD_POLICY` before insert (locked/required); add client-level `create_revision`/`activate_revision`/`rollback_to_revision` as the same generic helpers parameterized by table |
| `backend/app/tenants/revisions_router.py` | Modify | New `PATCH /clients/{client_id}/config`, `GET /clients/{client_id}/revisions`, `POST /clients/{client_id}/revisions/{id}/rollback`; existing agent endpoints return 422 on policy violations |
| `backend/app/tenants/router.py` | Modify | `GET /agents/{agent_id}/effective-config` (per-field provenance); `POST /admin/standards/resync` |
| `backend/app/voice/context.py` | Modify | `build_voice_context` calls `resolve_effective_config` instead of reading `Agent.*` columns directly |
| `backend/app/elevenlabs/service.py` | Modify | `_build_config_payload` reads from `EffectiveConfig`, not `Agent.*` |
| `backend/app/calls/service.py` | Modify | `create_session` records `standard_version` + `client_config_revision_id` alongside 1a's `agent_config_revision_id` |
| `frontend/src/features/admin/agents-section.tsx` | Modify | Provenance badge per field (`Qora standard` / `Client` / `Agent`); locked fields rendered read-only, not just disabled |
| `docs/architecture.md` | Modify | Document the 3-level inheritance model as the config source of truth, superseding 1a's flat-revision description |

## Interfaces / Contracts

```python
# backend/app/tenants/field_policy.py
FieldPolicy = Literal["locked", "overridable", "client_only", "agent_required"]

FIELD_POLICY: dict[str, FieldPolicy] = {
    "system_prompt": "agent_required",
    "goal": "agent_required",
    "voice_id": "agent_required",
    "tts_model": "overridable",
    "tts_speed": "overridable",
    "tts_stability": "overridable",
    "tts_similarity_boost": "overridable",
    "model": "overridable",
    "temperature": "overridable",
    "max_tokens": "overridable",
    "tools_enabled": "overridable",
    "first_message": "overridable",
    "language": "client_only",
    "turn_eagerness": "overridable",
    "soft_timeout_seconds": "overridable",
    "soft_timeout_message": "overridable",
    "soft_timeout_use_llm": "overridable",
    "voicemail_detection_enabled": "overridable",
    "max_call_duration_seconds": "overridable",
    # Locked Qora standards (no AgentConfigV1 counterpart; validated, never overridden)
    "end_call_tool_enabled": "locked",
    "analysis_model": "locked",
    "memory_window_calls": "locked",
    "memory_profile_facts_placement": "locked",
    "prompt_assembly_order": "locked",
    "load_skill_force_injection": "locked",
    "elevenlabs_system_tool_passthrough": "locked",
    "technical_retry_max_attempts": "locked",
    "max_call_duration_seconds_bounds": "locked",
    "post_call_webhook_secret_required": "locked",
}
```

```python
# backend/app/tenants/config_resolver.py — contract
FieldProvenance = Literal["standard", "client", "agent"]

@dataclass(frozen=True)
class EffectiveField:
    value: Any
    provenance: FieldProvenance

@dataclass(frozen=True)
class EffectiveConfig:
    fields: dict[str, EffectiveField]

def resolve_effective_config(
    standard: "AgentConfigStandard",
    client_overrides: dict[str, Any],   # from ClientConfigRevision.config
    agent_overrides: dict[str, Any],    # from AgentConfigRevision.config (V2; V1 handled separately)
) -> EffectiveConfig:
    """Pure function. For each field in FIELD_POLICY:
    - locked: value = standard's value, provenance = "standard" (overrides ignored/rejected upstream)
    - agent_required: value = agent_overrides[field] (no fallback — validated present upstream)
    - client_only: value = client_overrides.get(field, standard's value), provenance "client" or "standard"
    - overridable: agent_overrides[field] if present (provenance "agent"),
                   else client_overrides[field] if present (provenance "client"),
                   else standard's value (provenance "standard")
    """
```

```python
# backend/app/tenants/models.py — new model, mirrors AgentConfigRevision (1a)
class ClientConfigRevision(Base):
    __tablename__ = "client_config_revisions"
    id: Mapped[str]
    client_id: Mapped[str]  # FK clients.id
    revision_number: Mapped[int]
    config: Mapped[str]  # JSON/Text, sparse overrides only
    schema_version: Mapped[int]
    source: Mapped[str]  # "import" | "api" | "rollback"
    created_by: Mapped[str]
    created_at: Mapped[datetime]
    note: Mapped[str | None]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|---------------|----------|
| Unit | `FIELD_POLICY` is exhaustive | Every field in `AgentConfigV1` (1a) has an entry; no unknown field is referenced by the resolver |
| Unit | `resolve_effective_config` correctness per policy | One test per policy type × override-present/absent combination (locked always standard; agent_required always agent; client_only client-or-standard; overridable agent-or-client-or-standard) |
| Unit | `resolve_effective_config` provenance correctness | Same matrix, asserting provenance, not just value — catches the "right value, wrong reason" bug class |
| Unit | Write validation rejects locked-field writes | PATCH with a `locked` field present → 422 listing exactly that field, for both client and agent endpoints |
| Unit | Write validation rejects missing `agent_required` on new revisions | New agent revision missing `goal`/`system_prompt`/`voice_id` → 422; grandfathered agent's EXISTING revision still resolves successfully |
| Integration | **Equivalence test (hard acceptance criterion)** | For every existing agent (post-1a), compute `resolve_effective_config(...)` using empty client overrides and the agent's 1a `AgentConfigV1` values as agent overrides; assert every field's resolved VALUE equals the pre-1b value, for every agent seeded by the 1a seeders |
| Integration | Client revision propagation | Activate a new client revision for a client with 2+ active agents; assert an EL sync is enqueued for each, and each agent's effective config reflects the new client override |
| Integration | Standard version bump does NOT auto-sync | Bump `STANDARD_VERSION` in a test fixture; assert no sync is enqueued until the explicit resync endpoint is called |
| Integration | Standard resync only syncs drifted agents | Call the resync endpoint; assert only agents whose resolved config actually changed get a sync call, not every agent platform-wide |
| Regression | 1a's `AgentConfigV1` revisions still readable and resolvable | Existing `tests/unit/tenants/test_revisions_service.py` (1a) continues to pass unmodified; a V1 revision resolves through the SAME `resolve_effective_config` path treating its full snapshot as if every field were an agent override |
| Smoke | Admin UI provenance badges | Manual check: a field inherited from the standard shows "Qora standard"; from the client shows "Client"; agent-set shows "Agent"; locked fields render read-only, not merely disabled |

## Migration / Rollout

**Staged rollout** (see tasks.md for full per-task RED/GREEN/rollback breakdown):

1. Field-policy registry + standard module — additive, nothing reads it yet
2. Resolver — pure function, additive, nothing calls it yet
3. Client revisions schema + migration + API — additive
4. `AgentConfigV2` + write validation + grandfathering — additive (new revisions only; 1a's V1 write path untouched)
5. Runtime + EL projection cutover + client-revision propagation — the only behavioral-cutover task; gated on the equivalence test passing first
6. Admin API effective-config + minimal UI — additive
7. Prod rollout + verification (API-only, no SSH; `simulate-conversation`, Telnyx blocked — same constraints as 1a)

**Existing-agent safe path**: no historical revision is ever rewritten (D12). If the resolver produces a wrong effective value for some agent, the fix is a corrective `source=api` revision — never an edit to the resolver's inputs retroactively re-interpreted against old data.

## Rollback Plan

| Stage | Action | Notes |
|-------|--------|-------|
| After task 1 (registry + standard) | Revert PR; pure code, no data impact | |
| After task 2 (resolver) | Revert PR; pure function, no data impact | |
| After task 3 (client revisions) | `alembic downgrade -1` drops `client_config_revisions` + `clients.active_config_revision_id` + the new `call_sessions` columns | No runtime code depends on it yet |
| After task 4 (AgentConfigV2 + validation) | Revert PR; 1a's `AgentConfigV1` write path is untouched | |
| After task 5 (runtime + EL cutover) | Revert PR; `build_voice_context` and `_build_config_payload` revert to reading `Agent.*`/the 1a flat revision directly | Filesystem/DB sources were never deleted, same precedent as 1a's D6 |
| After task 6 (admin API + UI) | Revert PR; frontend-only impact, backend endpoints stay (additive, unused) | |
| After task 7 (prod rollout) | Re-run the standard resync endpoint with the PRIOR `STANDARD_VERSION` if a bad standard value shipped; `alembic downgrade` only if no client revisions have been created via the API since deploy | Same "additive, non-destructive" posture as 1a's task 7 |

## PR/Slice Boundary and Review Workload

| Task | Contents | Est. Lines | Risk |
|------|----------|-----------|------|
| 1 | Field-policy registry + standard module | ~250 | Low (additive, pure data) |
| 2 | Resolver + provenance | ~250 | Low (additive, pure function, heavily unit-tested) |
| 3 | Client revisions schema/migration/API | ~350 | Low (additive, mirrors 1a's shipped pattern) |
| 4 | AgentConfigV2 + write validation + grandfathering | ~350 | Medium (validation logic touches every write path) |
| 5 | Runtime + EL projection cutover + propagation | ~300 | High (behavioral cutover — the equivalence test gates this task) |
| 6 | Admin API effective-config + minimal UI | ~300 | Low (additive, frontend mostly) |
| 7 | Prod rollout + verification | ~50 (mostly docs/runbook) | Medium (production, no-SSH constraint, same as 1a) |

**Total**: ~1,850 changed lines across 7 reviewable units, each within or near the 400-line-per-PR target. Task 5 is the highest-risk unit (behavioral cutover gated on the equivalence test) and should not be combined with any other task in a single PR.

## Open Questions

- [ ] Should `language` (conversation) ever get a per-agent override path, and if so, is it a Qora-reviewed field-policy exception (per D16) or a self-service toggle gated by a client-level "allow multilingual agents" flag? Not blocking tasks 1–6; resolve before building any UI affordance for it.
- [ ] Exact cadence/trigger for noticing a grandfathered (`goal`-less) agent should be completed — purely visible-in-UI today; a reminder/nudge mechanism is explicitly deferred, not designed here.
- [ ] `tts_model` and `model` Qora-standard VALUES in this design (`eleven_v4_turbo`, `gpt-4.1-mini`) are the architect-specified production targets, not values confirmed by reading the current `Agent`/`Client` DB column defaults (which are `eleven_flash_v2_5` and `gpt-4o`, confirmed by code read). Before task 1 ships, confirm against the live production agent config (via the 1a admin API, no SSH) which value each currently-synced agent actually uses, so the standard being "set" here does not silently change production behavior for any agent whose resolved value would otherwise come from the standard.
