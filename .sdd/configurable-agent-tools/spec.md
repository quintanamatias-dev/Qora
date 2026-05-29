# Specs: configurable-agent-tools

Change: `configurable-agent-tools`
Phase: spec
Date: 2026-05-22

---

## 1. New Capability: `configurable-agent-tools`

Per-agent tool configuration via JSON schema; `capture_data` handler that validates
input and writes to `LeadProfileFact`; `tool_config` storage on the Agent model.

### Requirements

#### Requirement: Agent Stores Tool Config

The Agent model MUST support a `tool_config` JSON column (nullable). When `capture_data`
is in `tools_enabled`, `tool_config` MUST contain a valid OpenAI function-calling
`parameters` schema under the key `"capture_data"`. If the key is absent, the system
MUST reject calls to `capture_data` with a configuration error, not a runtime error.

##### Scenario: Agent created with capture_data schema

- GIVEN a new Agent with `tools_enabled=["capture_data"]`
- AND `tool_config={"capture_data": {"type": "object", "properties": {"marca": {"type": "string"}}, "required": ["lead_id", "marca"]}}`
- WHEN the agent is saved
- THEN the agent persists without error
- AND `tool_config` is retrievable as a parsed dict

##### Scenario: capture_data enabled but tool_config missing

- GIVEN an Agent with `tools_enabled=["capture_data"]`
- AND `tool_config` is NULL or does not contain a `"capture_data"` key
- WHEN the webhook attempts to build tool definitions for this agent
- THEN the system MUST log a configuration error and exclude `capture_data` from the tool list
- AND the call continues with the remaining tools (graceful degradation)

##### Scenario: tool_config present for other tools (ignored safely)

- GIVEN an Agent with `tool_config={"unknown_key": {...}}`
- AND `tools_enabled` does not include `capture_data`
- WHEN the agent is loaded
- THEN no error is raised; the extra key is silently ignored

---

#### Requirement: capture_data Handler Validates and Persists

The `capture_data` tool MUST validate all arguments declared `required` in the
agent's stored schema before writing. On success, it MUST write one `LeadProfileFact`
row per captured field using the key format `captured:{field_name}`. It MUST NOT
transition lead status. It MUST NOT write to deprecated `car_*` columns.

##### Scenario: Happy path — all required fields present

- GIVEN a live call for lead `L1` with agent config requiring `["lead_id","marca","modelo","anio"]`
- WHEN the LLM calls `capture_data(lead_id="L1", marca="Toyota", modelo="Corolla", anio=2020)`
- THEN one `LeadProfileFact` row is upserted per field (`captured:marca`, `captured:modelo`, `captured:anio`)
- AND the tool returns `{"status": "captured", "fields": ["marca", "modelo", "anio"]}`
- AND lead status is NOT changed

##### Scenario: Missing required field

- GIVEN the same agent config requiring `["lead_id","marca","modelo","anio"]`
- WHEN the LLM calls `capture_data(lead_id="L1", marca="Toyota")` (missing `modelo`, `anio`)
- THEN the tool returns `{"error": "missing_required_fields", "missing": ["modelo", "anio"]}`
- AND no `LeadProfileFact` rows are written (atomic — all or nothing per call)

##### Scenario: Lead not found

- GIVEN `lead_id="nonexistent"`
- WHEN `capture_data` is invoked
- THEN the tool returns `{"error": "lead_not_found"}`
- AND no facts are written

##### Scenario: Cross-tenant attempt blocked

- GIVEN lead `L1` belongs to client `A`
- WHEN `capture_data` is called in a session for client `B` with `lead_id="L1"`
- THEN the tool returns `{"error": "lead_not_found"}` (same response as not found — no leakage)

##### Scenario: Optional field omitted

- GIVEN agent config marks `notes` as optional (not in `required`)
- WHEN `capture_data` is called without `notes`
- THEN the call succeeds; no `captured:notes` fact is written

---

#### Requirement: Quintana Seguros Migration — Zero Behavioral Drift

After migration, Quintana Seguros MUST produce identical captured data using
`capture_data` with the car-fields schema. The `capture_data` schema SHOULD map
to the same fact keys previously written by `register_interest`.

##### Scenario: Schema parity after migration

- GIVEN Quintana Seguros agent migrated to `capture_data` with schema matching old car fields
- WHEN a call captures `{marca, modelo, anio, seguro_actual}`
- THEN `LeadProfileFact` rows for `captured:marca`, `captured:modelo`, `captured:anio`, `captured:seguro_actual` exist
- AND the data is equivalent to what `register_interest` previously wrote to `car_*` columns

---

### Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Agent with `capture_data` and valid `tool_config` saves without error |
| AC-2 | Missing required fields → error response, no DB writes |
| AC-3 | Cross-tenant lead access → `lead_not_found` (no leakage) |
| AC-4 | Each captured field produces exactly one active `LeadProfileFact` row with key `captured:{name}` |
| AC-5 | `capture_data` never transitions lead status |
| AC-6 | Missing `tool_config` → graceful degradation (tool excluded, call continues) |
| AC-7 | Quintana Seguros schema parity test passes |

---

## 2. Modified Capability: `agent-tool-dispatch`

Tool registry and dispatcher updated to resolve `capture_data` schema dynamically
from agent config.

### Current Behavior

`registry.py` imports all tool `TOOL_DEFINITION` constants statically at module load.
`build_tool_definitions(names)` filters the static dict by requested names.
`dispatcher.py` routes calls via a static `_TOOL_REGISTRY` dict with hardcoded handlers.
`QORA_TOOL_NAMES` in `schemas.py` is derived from the static `TOOL_DEFINITIONS` keys.

### MODIFIED Requirements

#### Requirement: Dynamic Schema Resolution for capture_data

(Previously: `TOOL_DEFINITIONS` was a static dict; all schemas were fixed at import time)

The registry MUST support a `build_tool_definitions(names, *, agent_tool_config=None)`
overload. When `capture_data` is in `names` and `agent_tool_config` contains a
`"capture_data"` key, the registry MUST build the function schema dynamically by
merging the stored `parameters` block into the base tool definition. If
`agent_tool_config` is `None` or missing the key, `capture_data` MUST be excluded
from the returned list (not raise).

##### Scenario: Dynamic schema injected at call time

- GIVEN agent has `tool_config={"capture_data": {"type": "object", "properties": {"marca": {...}}, "required": ["lead_id","marca"]}}`
- WHEN `build_tool_definitions(["capture_data", "get_lead_details"], agent_tool_config=agent.tool_config)` is called
- THEN the returned list includes a `capture_data` entry with the agent-specific `parameters` schema
- AND `get_lead_details` is included unchanged from its static definition

##### Scenario: No agent_tool_config supplied

- GIVEN `build_tool_definitions(["capture_data"], agent_tool_config=None)` is called
- THEN `capture_data` is excluded; result is an empty list (or None)
- AND no exception is raised

##### Scenario: QORA_TOOL_NAMES includes capture_data

- GIVEN the registry is updated to add `capture_data` to its static definitions
- WHEN `schemas.py` derives `QORA_TOOL_NAMES`
- THEN `capture_data` is a valid tool name in `AgentCreate.tools_enabled` validation

#### Requirement: Dispatcher Injects Agent Config into capture_data Calls

(Previously: `dispatch_tool` had no concept of per-agent config; tool args were
derived purely from the LLM's function call arguments)

`dispatch_tool` MUST accept an optional `agent_tool_config: dict | None` parameter.
When `tool_name == "capture_data"`, the dispatcher MUST pass `agent_tool_config` to
the `capture_data` handler for runtime schema validation. For all other tool names,
`agent_tool_config` MUST be ignored.

##### Scenario: capture_data dispatched with agent config

- GIVEN `dispatch_tool("capture_data", tool_args, ..., agent_tool_config={"capture_data": {...}})`
- WHEN called
- THEN the handler receives both `tool_args` and the agent-specific schema
- AND validates args against that schema before writing

##### Scenario: Deprecated tool names stripped on agent load

- GIVEN an Agent DB row with `tools_enabled=["register_interest","mark_not_interested","schedule_followup"]`
- WHEN the agent is loaded and those names are no longer in `QORA_TOOL_NAMES`
- THEN unknown names are stripped from the working list with a deprecation warning logged
- AND the agent continues operating with the remaining valid tools

#### Requirement: Legacy Tool Modules Removed from Dispatch Registry

(Previously: `_TOOL_REGISTRY` contained `register_interest`, `mark_not_interested`,
`schedule_followup`)

In Phase 2, `_TOOL_REGISTRY` MUST NOT contain `register_interest`, `mark_not_interested`,
or `schedule_followup`. Calls to these names MUST return `{"error": "tool_removed",
"detail": "..."}` rather than routing to a handler.

##### Scenario: Legacy tool called after Phase 2

- GIVEN Phase 2 is complete and an old agent still has `register_interest` in `tools_enabled`
- WHEN the LLM calls `register_interest` during a live call
- THEN dispatch returns `{"error": "tool_removed", "detail": "use capture_data"}`
- AND the error is surfaced to the LLM via the SSE stream without crashing the session

---

### Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | `build_tool_definitions` with `agent_tool_config` returns dynamic `capture_data` schema |
| AC-2 | `build_tool_definitions` without config excludes `capture_data`, no exception |
| AC-3 | `capture_data` present in `QORA_TOOL_NAMES`; passes `AgentCreate` validation |
| AC-4 | `dispatch_tool` signature accepts `agent_tool_config`; passed to handler |
| AC-5 | Deprecated tool names on Agent load → stripped + warning logged, no crash |
| AC-6 | Post-Phase 2: `register_interest`/`mark_not_interested`/`schedule_followup` calls return `tool_removed` error |

---

## 3. Modified Capability: `lead-status-lifecycle`

Status transitions (`interested`, `not_interested`, `follow_up`) become analysis-driven
only; tool-driven transitions removed.

### Current Behavior

Three tools perform lead status transitions mid-call:
- `register_interest` → transitions to `interested` via `transition_lead_status`
- `mark_not_interested` → transitions to `not_interested`
- `schedule_followup` → transitions to `follow_up` + creates `ScheduledCall`

Post-call analysis (`next_action_suggested` + `auto_schedule()`) runs AFTER the call
and can independently set status and schedule calls.

### ADDED Requirements

#### Requirement: Analysis Pipeline Drives All Terminal Status Transitions

The post-call analysis pipeline MUST be the sole mechanism for transitioning lead
status to `interested`, `not_interested`, or `follow_up` (Phase 2 onward). The
analysis runner MUST read `next_action_result.action` after all dimensions complete
and apply the following mapping:

| `next_action_result.action` | Lead status transition |
|---|---|
| `follow_up` | → `follow_up` |
| `schedule_call` | → `follow_up` |
| `close_lead` (outcome: do_not_contact, hostile, completed_negative) | → `not_interested` |
| `close_lead` (outcome: completed_positive) | → `interested` |
| `retry_call` | No status change |
| `human_review` | No status change |

The mapping MUST be applied only when `lead.status == "called"` (i.e., after a call
has occurred). The pipeline MUST NOT transition status for leads still in `new` or
terminal states (`interested`, `not_interested`).

##### Scenario: Positive outcome drives interested transition

- GIVEN a call completes with `next_action_result.action="close_lead"` and `outcome.classification="completed_positive"`
- WHEN the analysis pipeline applies the status mapping
- THEN lead status transitions to `interested`
- AND the transition is persisted via `transition_lead_status` (same state machine rules apply)

##### Scenario: Negative outcome drives not_interested transition

- GIVEN `next_action_result.action="close_lead"` and `outcome.classification="completed_negative"` (or `do_not_contact`, `hostile`)
- WHEN the mapping is applied
- THEN lead status transitions to `not_interested`

##### Scenario: Follow-up action drives follow_up transition

- GIVEN `next_action_result.action="follow_up"` or `"schedule_call"`
- WHEN the mapping is applied
- THEN lead status transitions to `follow_up`

##### Scenario: Retry or human review — no status change

- GIVEN `next_action_result.action="retry_call"` or `"human_review"`
- WHEN the mapping is applied
- THEN lead status remains `called`; no `transition_lead_status` call is made

##### Scenario: Already in terminal state — no double-transition

- GIVEN lead status is already `interested`
- WHEN the analysis pipeline attempts to apply the mapping
- THEN no transition is attempted; the pipeline logs a warning and continues

---

### REMOVED Requirements

#### Requirement: Tool-Driven Status Transitions

(Reason: `register_interest`, `mark_not_interested`, and `schedule_followup` are removed
in Phase 2. Status transitions they performed are now fully covered by the analysis
pipeline. Removing tool-driven transitions eliminates the race condition between
mid-call tool transitions and post-call analysis reassignment.)

---

### Acceptance Criteria

| # | Criterion |
|---|-----------|
| AC-1 | Analysis pipeline transitions status to `interested` when action=`close_lead` + positive outcome |
| AC-2 | Analysis pipeline transitions to `not_interested` when action=`close_lead` + negative/hostile/dnc outcome |
| AC-3 | Analysis pipeline transitions to `follow_up` when action=`follow_up` or `schedule_call` |
| AC-4 | `retry_call` and `human_review` leave status as `called` |
| AC-5 | Pipeline does not attempt transitions on leads not in `called` state |
| AC-6 | No mid-call tool (`register_interest`, `mark_not_interested`, `schedule_followup`) performs status transitions post-Phase 2 |
| AC-7 | `transition_lead_status` state machine rules still enforced (no bypassing) |

---

## Edge Cases (Cross-Cutting)

| Case | Spec Reference | Expected Behavior |
|------|---------------|-------------------|
| `capture_data` called before `get_lead_details` (lead not in context) | CAP-1, AC-2 | lead_id in args required; missing → error |
| Analysis runs but `next_action_result` is absent (old pipeline) | lifecycle AC-4 | No transition attempted; pipeline continues |
| Agent has both `capture_data` and `register_interest` in tools_enabled | dispatch AC-5 | `register_interest` stripped with warning |
| `tool_config` JSON is malformed (not valid JSON) | CAP-1, AC-6 | Agent load fails validation with clear error |
| Two calls overlap; both analysis pipelines try to transition | lifecycle AC-5 | State machine enforces idempotency; second transition rejected cleanly |
