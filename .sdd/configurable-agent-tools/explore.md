# Exploration: Configurable Agent Tools

## Current State

### Tool Architecture — Full Code Path Map

**8 tools defined**, 4 active by default, 3 disabled, 1 infrastructure:

| Tool | Module | Status | Purpose |
|------|--------|--------|---------|
| `get_lead_details` | `app/tools/get_lead_details.py` | Active (default) | Fetch lead record + increment call count |
| `register_interest` | `app/tools/register_interest.py` | Active (default) | Capture car data + transition → `interested` |
| `mark_not_interested` | `app/tools/mark_not_interested.py` | Active (default) | Transition → `not_interested` + save reason |
| `schedule_followup` | `app/tools/schedule_followup.py` | Active (default) | Transition → `follow_up` + create ScheduledCall |
| `get_lead_profile` | `app/tools/get_lead_profile.py` | Disabled | Return LeadProfileFact rows as Spanish text |
| `get_lead_history` | `app/tools/get_lead_history.py` | Disabled | Return LeadInterestHistory timeline |
| `get_lead_pain_points` | `app/tools/get_lead_pain_points.py` | Disabled | Return pain/service_issue profile facts |
| `load_skill` | `app/tools/skill_loader.py` | Infrastructure | Load agent skill file dynamically |

**Registration chain:**
1. Each tool module exports a `TOOL_DEFINITION` dict (OpenAI function-calling schema)
2. `app/tools/registry.py` imports all definitions → assembles `TOOL_DEFINITIONS` dict + `build_tool_definitions(names)` helper
3. `app/agents/schemas.py` imports `TOOL_DEFINITIONS` keys as `QORA_TOOL_NAMES` for validation
4. Agent DB column `tools_enabled` stores a JSON string of tool names (e.g., `'["get_lead_details","register_interest"]'`)
5. Default: `'["get_lead_details","register_interest","mark_not_interested","schedule_followup"]'`

**Dispatch chain (per-turn):**
1. `webhook.py` → parses `agent.tools_enabled` JSON → calls `build_tool_definitions(names)` → sends to OpenAI
2. LLM emits `ToolCallDelta` → `webhook.py` accumulates → calls `dispatch_tool()` from `app/tools/dispatcher.py`
3. `dispatcher.py` → routes `load_skill` separately (no DB), CRM tools via `_TOOL_REGISTRY` → handler function
4. Handler runs with `AsyncSession` → returns dict → webhook serializes to SSE

**Tenant isolation:**
- `dispatch_tool()` receives `client_id` from conversation context
- `_validate_lead_scope()` checks `lead.client_id != client_id` → rejects cross-tenant access
- This guard exists but is a RUNTIME check — a malicious tool_args `lead_id` from another tenant IS rejected

### The Insurance-Specific Problem

The Lead model has **hardcoded insurance columns**: `car_make`, `car_model`, `car_year`, `current_insurance`. These exist on the table itself:

```python
# app/leads/models.py
car_make: Mapped[str | None] = mapped_column(String, nullable=True)
car_model: Mapped[str | None] = mapped_column(String, nullable=True)
car_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
current_insurance: Mapped[str | None] = mapped_column(String, nullable=True)
```

These are referenced in:
- `register_interest.py` — requires `car_make`, `car_model`, `car_year` as mandatory params
- `get_lead_details.py` — returns all car fields
- `insurance_agent.py` — prompt template uses `{{car_make}}`, `{{car_model}}`, `{{car_year}}`
- `context.py` — builds lead profile block with car info
- `initiation.py` — sends car data as ElevenLabs dynamic variables
- `summarizer.py` — `data_corrections` pipeline can correct car fields
- `loader.py` — template variable substitution includes car fields

**Impact:** Every new client would need to either (a) use these car columns for unrelated data (terrible), (b) ignore them (wasted columns), or (c) use `extracted_facts` JSON blob for their domain data (no schema validation).

### Tool–Analysis Overlap

Post-call analysis already handles what several tools try to do during the call:

| Tool Action | Analysis Dimension | Overlap |
|-------------|-------------------|---------|
| `register_interest` → status `interested` | `interest_level` (0-100), `detected_interests` (catalog-validated) | **FULL** — analysis is richer and more accurate |
| `mark_not_interested` → status `not_interested` | `call_outcome.classification`, `next_action_suggested` (`close_lead`) | **FULL** — analysis uses rules engine + GPT fallback |
| `schedule_followup` → status `follow_up` + ScheduledCall | `next_action_suggested` (`schedule_call`, `follow_up`), `commitments` (callback commitments) | **FULL** — `auto_schedule()` already creates ScheduledCall from analysis |
| `get_lead_details` — fetch lead data | Lead profile injected in context at session start | **PARTIAL** — already in context, but tool allows mid-call refresh |

The `next_action` decision engine (Issue #47) runs after ALL other dimensions complete and uses a priority-ordered rules engine:
- P1: Hard stops (close_lead) — bad outcome, do_not_call
- P2: Max attempts (close_lead) — call_count >= threshold
- P3: Commitment-based (schedule_call/follow_up) — from commitments axis
- P4: No useful conversation (retry_call) — no_answer, technical_issue
- P5: Interest + outcome signal — threshold rules
- P6: GPT fallback

This engine ALREADY drives `auto_schedule()` which creates ScheduledCall records — exactly what `schedule_followup` does manually.

### Lead Status State Machine

```
new → called → interested (TERMINAL)
             → not_interested (TERMINAL)
             → follow_up → called (loop)
```

Currently, `interested` and `not_interested` are TERMINAL states — no transitions out. Tools (`register_interest`, `mark_not_interested`) push leads into these terminals during calls. Post-call analysis writes `interest_level`, `next_action`, `do_not_call` but does NOT transition status directly.

---

## Affected Areas

- `backend/app/tools/registry.py` — tool definition assembly (redesign for dynamic tools)
- `backend/app/tools/dispatcher.py` — routing (must support dynamic tool handlers)
- `backend/app/tools/register_interest.py` — hardcoded car fields (replace with configurable schema)
- `backend/app/tools/mark_not_interested.py` — redundant with analysis (candidate for removal)
- `backend/app/tools/schedule_followup.py` — redundant with auto_schedule (candidate for removal)
- `backend/app/tools/get_lead_details.py` — returns car-specific fields (needs generalization)
- `backend/app/tools/get_lead_profile.py` — already generic (reads LeadProfileFact)
- `backend/app/tools/get_lead_history.py` — reads LeadInterestHistory (already generic)
- `backend/app/tools/get_lead_pain_points.py` — reads profile facts (already generic)
- `backend/app/leads/models.py` — hardcoded `car_make`/`car_model`/`car_year` columns
- `backend/app/agents/schemas.py` — `QORA_TOOL_NAMES` validation (must allow dynamic names)
- `backend/app/tenants/models.py` — Agent `tools_enabled` default (insurance-specific)
- `backend/app/analysis/schema.py` — `PostCallAnalysis` descriptions reference insurance
- `backend/app/analysis/universal/data_corrections.py` — correctable fields registry (car-specific)
- `backend/app/voice/context.py` — builds lead profile with car-specific fields
- `backend/app/prompts/insurance_agent.py` — template is fully insurance-specific
- `backend/app/prompts/loader.py` — template variable substitution includes car fields

---

## Analysis: What Should Stay, Go, or Change

### KEEP as-is
- **`load_skill`** — Infrastructure tool. Client-agnostic, well-designed, secure.
- **`get_lead_profile`** — Already generic (reads LeadProfileFact by namespace). Client-agnostic.
- **`get_lead_pain_points`** — Already generic (reads profile facts). Client-agnostic.

### REMOVE (post-call analysis fully covers these)
- **`mark_not_interested`** — Post-call analysis determines `call_outcome.classification`, `next_action_suggested`, and `do_not_call`. Having the agent decide during the call is:
  - Less accurate (agent makes a snap judgment; analysis has the full transcript)
  - Premature (status becomes TERMINAL — no way back if the lead was just hesitant)
  - Redundant with the rules engine in `next_action`

- **`schedule_followup`** — `auto_schedule()` already creates ScheduledCall records from `next_action_suggested`. The tool duplicates this logic and creates scheduling infrastructure without a dialer engine. The `commitments` axis in analysis detects callback commitments, and `next_action` decides timing.

### REDESIGN
- **`register_interest`** → become a **generic `capture_data` tool** with configurable schema per client/agent. The concept is right (agent captures data during call), but the implementation is locked to car insurance.

- **`get_lead_details`** → either remove (profile already injected in context) or generalize to return only client-relevant fields via a configurable response schema.

### The Status Transition Question

**Recommendation: Remove agent-driven status transitions entirely. Let post-call analysis drive all status changes.**

| Agent-Driven (current) | Analysis-Driven (proposed) |
|---|---|
| Snap judgment during conversation | Full-transcript retrospective with rules engine |
| TERMINAL states are irreversible | Analysis can re-score on next call |
| Agent might misread hesitation as rejection | Rules engine has interest threshold + attempt counting |
| Inconsistent: tool sets `interested` but analysis sets `interest_level=30` | Single source of truth for lead lifecycle |

**Tradeoff:** Removing live status transitions means the CRM won't show "interested" until the call ends and analysis completes (1-3 min delay). For async business workflows, this is fine. For a live dashboard expecting instant status updates, we'd need a "call in progress" indicator instead.

**Migration note:** The state machine (`new → called → interested/not_interested/follow_up`) should evolve to be driven by `next_action_suggested` post-analysis:
- `follow_up` → analysis says `follow_up` or `schedule_call`
- `interested` → analysis `interest_level` > threshold + positive outcome
- `not_interested` → analysis `close_lead` with hard rejection
- `called` → set at initiation (already happens in `initiation.py`)

---

## Approaches: Configurable Tool System

### Approach A: Generic `capture_data` Tool with Per-Client Schema

Replace `register_interest` with a single `capture_data` tool. Each client/agent defines a JSON schema for what data to capture.

**Per-agent configuration (in `registry.yaml` or agent config):**
```yaml
tools:
  capture_data:
    description: "Capturá los datos del lead para cotización"
    schema:
      type: object
      properties:
        car_make: { type: string, description: "Marca del auto" }
        car_model: { type: string, description: "Modelo del auto" }
        car_year: { type: integer, description: "Año del auto" }
      required: [car_make, car_model, car_year]
```

**A restaurant client would define:**
```yaml
tools:
  capture_data:
    description: "Capture reservation details"
    schema:
      type: object
      properties:
        party_size: { type: integer }
        preferred_date: { type: string }
        dietary_restrictions: { type: string }
      required: [party_size, preferred_date]
```

**Storage:** All captured data writes to `LeadProfileFact` (namespace: `captured:`) or a new `LeadCapturedData` JSON column. No more hardcoded Lead columns per domain.

- **Pros:** Single tool, infinite flexibility, no code changes per client, schema validates input
- **Cons:** Generic tool description may confuse the LLM; need good per-client prompt engineering; complex schema validation at runtime
- **Effort:** Medium

### Approach B: Client-Defined Tool Manifests

Each client defines their tools as YAML/JSON manifests in their agent directory:
```
clients/{client_id}/agents/{agent_slug}/tools/
├── capture-auto-data.tool.yaml
├── check-coverage.tool.yaml
└── tools-registry.yaml
```

Each manifest declares: name, description, OpenAI schema, handler type (built-in or webhook), storage target.

**Built-in handlers:**
- `save_to_profile_facts` — write key-value pairs to LeadProfileFact
- `transition_status` — move lead through state machine
- `save_to_json` — write to lead.extracted_facts or a new JSON column

**Custom handlers:**
- `webhook` — POST to client's external API with captured data

- **Pros:** Maximum flexibility, clients can define arbitrary tools, extensible handler system
- **Cons:** High complexity, tool registration becomes dynamic (can't validate at schema level), security surface grows with webhook handlers
- **Effort:** High

### Approach C: Tool Templates with Parameter Injection

Keep a small set of built-in tool "templates" but make their parameters configurable:

```python
# Built-in templates
TOOL_TEMPLATES = {
    "capture_data": {  # Replaces register_interest
        "handler": "save_to_profile_facts",
        "config_required": ["description", "schema"],
    },
    "load_skill": {  # Already exists
        "handler": "load_skill_handler",
        "config_required": [],
    },
    "query_data": {  # Replaces get_lead_details
        "handler": "read_profile_facts",
        "config_required": ["namespaces"],
    },
}
```

Per-agent config specifies which templates to enable and with what parameters:
```yaml
tools:
  - template: capture_data
    name: register_auto_interest
    description: "Registrá el interés del lead en el seguro"
    schema: { ... car fields ... }
  - template: capture_data
    name: capture_reservation
    description: "Capturá los datos de la reserva"
    schema: { ... restaurant fields ... }
```

- **Pros:** Controlled set of behaviors, easy to audit, template validation is straightforward
- **Cons:** New handler types require code changes, less flexible than full manifests
- **Effort:** Medium

### Approach D: Hybrid — Templates + Generic `capture_data`

Combine: keep `load_skill` and `get_lead_profile`/`get_lead_pain_points` as built-in tools. Add a configurable `capture_data` tool (Approach A). Remove the rest.

The tool system becomes:
1. **Infrastructure tools** (always available, not configurable): `load_skill`
2. **Query tools** (opt-in, already generic): `get_lead_profile`, `get_lead_pain_points`
3. **Capture tool** (configurable per client): `capture_data` with per-agent schema
4. **Future extensibility**: Add more templates or webhook tools later

- **Pros:** Smallest change surface, immediate multi-tenant value, backward compatible
- **Cons:** Doesn't solve all future needs (e.g., client-specific API integrations)
- **Effort:** Low-Medium

---

## Recommendation

**Approach D (Hybrid)** is the recommended path. Here's why:

1. **Immediate payoff:** Removes the 3 insurance-locked tools, replaces with 1 configurable `capture_data` tool. Every new client works on day one.

2. **Minimal architecture risk:** No new handler abstraction, no webhook security concerns, no dynamic tool registration complexity. The only new concept is "configurable OpenAI schema per agent."

3. **Compatible with existing analysis:** Post-call analysis continues unchanged. The `capture_data` tool writes to `LeadProfileFact` (already generic), and analysis reads from transcript (doesn't depend on tool output).

4. **Clear migration path:** Quintana Seguros gets a `capture_data` config matching current car fields. Behavior is identical. New clients define their own schemas.

5. **Status transitions move to post-analysis:** Remove `register_interest`'s status transition, `mark_not_interested`, and `schedule_followup`. The `next_action` engine + `auto_schedule()` handle everything.

6. **Future extensibility:** Approach B's full manifest system can be built later if clients need custom API integrations. The `capture_data` template pattern is forward-compatible.

### Implementation Sketch

**Phase 1 — Decouple tools from insurance:**
- Add `tool_config` JSON column to Agent model (or a YAML file in agent dir)
- Create `capture_data` handler that reads schema from config, validates input, writes to LeadProfileFact
- Migrate Quintana Seguros to `capture_data` with car fields schema
- Remove `register_interest`, `mark_not_interested`, `schedule_followup` from defaults
- Keep them available as opt-in for backward compat during migration

**Phase 2 — Status transitions via analysis:**
- Remove tool-driven `transition_lead_status()` calls
- Add status derivation logic to `_merge_facts_into_lead()` based on `next_action_suggested`
- Update state machine to support analysis-driven transitions

**Phase 3 — Lead model cleanup:**
- Deprecate `car_make`, `car_model`, `car_year`, `current_insurance` columns
- Move data to `LeadProfileFact` with `captured:` namespace
- Keep columns as nullable for backward compat (soft deprecation)

---

## Multi-Tenant Data Isolation Assessment

**Current state:**
- `dispatch_tool()` validates `lead.client_id == client_id` — cross-tenant writes are rejected ✅
- Tools receive `client_id` from webhook context (resolved from URL path) — not user-supplied ✅
- `LeadProfileFact` has `lead_id` FK → Lead → `client_id` — tenant scoping inherited ✅

**Gaps:**
- No query-level tenant filter in `get_lead_details`, `get_lead_profile`, etc. — they fetch by `lead_id` only, relying on the dispatcher's pre-check
- If a future tool bypasses the dispatcher, tenant isolation breaks
- **Recommendation:** Add `client_id` filter to ALL lead queries (defense in depth), or enforce at repository layer

---

## Compatibility with Existing Analysis

The post-call analysis pipeline has 12+ dimensions. Configurable tools interact cleanly:

| Analysis Dimension | Configurable Tool Interaction |
|---|---|
| `interest_level` | No tool needed — analysis scores from transcript |
| `next_action_suggested` | Replaces `schedule_followup` and `mark_not_interested` |
| `data_corrections` | `capture_data` output becomes source data; corrections pipeline updates it |
| `detected_interests` | No tool needed — catalog-validated from transcript |
| `commitments` | No tool needed — extracted from transcript |
| `profile_facts` | `capture_data` writes to same store (LeadProfileFact); analysis can refine |
| `misc_notes` | No tool needed — sliding-window from transcript |
| `call_outcome` | No tool needed — semantic classification from transcript |

The only interaction point is `capture_data` → `LeadProfileFact` ← `profile_facts` pipeline. Both write to the same store. The profile_facts pipeline uses supersede semantics (old value gets `superseded_at` set), so `capture_data` writes during the call will be preserved alongside analysis-extracted facts. No conflict.

---

## Risks

1. **LLM tool-call accuracy with generic schemas:** A generic `capture_data` tool with a flexible schema may produce lower-quality tool calls than a specifically named `register_interest`. Mitigation: Use detailed per-client tool descriptions and test with each client's conversation patterns.

2. **Migration complexity for Quintana Seguros:** Existing leads have `car_make`/`car_model`/`car_year` on the Lead model. Moving to LeadProfileFact requires data migration and updating all read paths. Mitigation: Phase the migration; keep columns as fallback during transition.

3. **Status transition timing gap:** Removing live status transitions means CRM status updates lag by 1-3 minutes (analysis completion time). Mitigation: Add a "call_in_progress" transient status or real-time call status indicators.

4. **`schedule_followup` removal while scheduler is active:** Quintana Seguros has `scheduler_enabled=True`. Removing the tool while `auto_schedule()` exists is safe, but operators accustomed to agent-confirmed scheduling may notice behavioral change. Mitigation: Communicate the shift; `auto_schedule()` already runs after every call.

5. **Backward compatibility:** Removing tools from `QORA_TOOL_NAMES` will break existing agents with those tools in `tools_enabled`. Mitigation: Deprecate tools (keep definitions, add warnings) before removing. Or auto-strip removed tools from `tools_enabled` on load.

6. **`get_lead_details` has side effects:** It increments `call_count` and sets `last_called_at`. If removed, this logic needs to move to initiation or analysis. Already partially handled: `initiation.py` transitions status to `called`.

---

## Ready for Proposal

**Yes.** The investigation is complete. The current tool system is mapped, the analysis overlap is quantified, the multi-tenant isolation is assessed, and four approaches are compared with a clear recommendation (Approach D: Hybrid).

The change touches the tool subsystem, lead model, analysis pipeline integration, and agent configuration — it's a significant architectural evolution but can be phased incrementally with zero breaking changes at each step.

**Next step:** `sdd-propose` to define scope, phases, rollback strategy, and acceptance criteria.
