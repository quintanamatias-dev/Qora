# Proposal: Configurable Agent Tools

## Intent

The current tool system hardcodes insurance-specific behavior into the platform core. Three of four default tools (`register_interest`, `mark_not_interested`, `schedule_followup`) duplicate post-call analysis logic and lock the platform to one business vertical. This change decouples the tool layer from any domain, making Qora viable for multiple tenants with different business types — without code changes per client.

## Scope

### In Scope
- Replace `register_interest` with a generic `capture_data` tool using per-agent configurable JSON schema
- Remove `mark_not_interested` and `schedule_followup` (post-call analysis fully covers both)
- Add `tool_config` storage to Agent model (JSON column or agent directory file)
- Move all lead status transitions to analysis-driven post-call pipeline
- Migrate Quintana Seguros config to `capture_data` with current car-fields schema (zero behavioral change)
- Soft-deprecate hardcoded `car_make`, `car_model`, `car_year`, `current_insurance` Lead columns
- Add `client_id` defense-in-depth filter to all CRM queries (tenant isolation hardening)

### Out of Scope
- Full manifest-based tool system (Approach B) — deferred for future client webhook integrations
- Auto-dialer engine — `schedule_followup` is removed, but the scheduling infrastructure stays as-is
- Removing `get_lead_details` entirely — scoped to generalization only in Phase 1
- Live "call in progress" dashboard status — deferred UX work

## Capabilities

> Contract for sdd-spec phase.

### New Capabilities
- `configurable-agent-tools`: Per-agent tool configuration via JSON schema; `capture_data` handler that validates input and writes to `LeadProfileFact`; tool config storage on Agent model

### Modified Capabilities
- `agent-tool-dispatch`: Tool registry and dispatcher updated to resolve `capture_data` schema dynamically from agent config
- `lead-status-lifecycle`: Status transitions (`interested`, `not_interested`, `follow_up`) become analysis-driven only; tool-driven transitions removed
- `lead-model`: `car_*` columns soft-deprecated; `tool_config` added to Agent model; `QORA_TOOL_NAMES` validation updated

## Approach

Approach D (Hybrid): minimal new abstraction. Infrastructure tools stay. Three domain-locked tools are removed. One configurable `capture_data` tool with per-agent OpenAI schema replaces `register_interest`. Post-call analysis already drives scheduling and status — we formalize that by removing the now-redundant agent-side tools. Phased in 3 stages so each step is independently deployable and rollback-safe.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `backend/app/tools/registry.py` | Modified | Support dynamic `capture_data` schema; update `QORA_TOOL_NAMES` |
| `backend/app/tools/dispatcher.py` | Modified | Route `capture_data` with agent config injection |
| `backend/app/tools/capture_data.py` | New | Generic capture tool; validates per-agent schema; writes to LeadProfileFact |
| `backend/app/tools/register_interest.py` | Removed (Phase 2) | Replaced by `capture_data`; kept as deprecated opt-in during Phase 1 |
| `backend/app/tools/mark_not_interested.py` | Removed (Phase 2) | Fully covered by analysis pipeline |
| `backend/app/tools/schedule_followup.py` | Removed (Phase 2) | Fully covered by `auto_schedule()` in analysis |
| `backend/app/tools/get_lead_details.py` | Modified | Remove car-specific fields; relocate `call_count` increment to initiation |
| `backend/app/agents/schemas.py` | Modified | Allow `capture_data` in `QORA_TOOL_NAMES`; deprecation warnings for removed tools |
| `backend/app/tenants/models.py` | Modified | Add `tool_config` JSON column to Agent; update default `tools_enabled` |
| `backend/app/leads/models.py` | Modified (Phase 3) | Soft-deprecate `car_*` columns (nullable, no removal) |
| `backend/app/analysis/universal/` | Modified | Add status transition logic driven by `next_action_suggested` |
| `backend/app/voice/context.py` | Modified | Remove car-specific template vars from lead profile block |
| `backend/app/prompts/loader.py` | Modified | Remove car field substitution variables |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LLM lower accuracy with generic `capture_data` vs named `register_interest` | Med | Rich per-client descriptions in schema + test with Quintana conversation patterns |
| CRM shows stale status during 1-3 min analysis delay | Med | "call_in_progress" transient status or UI polling indicator (deferred, accepted for now) |
| Existing agents with removed tools in `tools_enabled` break on load | Low | Auto-strip unknown tool names on Agent load + emit deprecation log |
| Quintana Seguros data migration for car columns → LeadProfileFact | Low | Keep columns nullable (no DROP); migration script in Phase 3 only |
| `get_lead_details` side-effect loss (`call_count` increment) | Low | Move increment to `initiation.py` (already transitions status to `called`) |
| Tool config schema validation bypassed at runtime | Low | Validate `capture_data` args against stored JSON Schema before write |

## Rollback Plan

**Phase 1 (add `capture_data` + tool_config):** Revert by toggling agent `tools_enabled` back to `register_interest`. No data loss — `LeadProfileFact` writes are additive. Remove `tool_config` column migration.

**Phase 2 (remove transition tools + wire analysis-driven status):** Revert by re-enabling `register_interest`, `mark_not_interested` in registry and rolling back analysis transition logic. Status transitions that happened via analysis during Phase 2 remain valid.

**Phase 3 (Lead model cleanup):** Columns are never dropped — only marked deprecated in code. Revert by re-exposing columns in serializers. Zero data risk.

## Dependencies

- Post-call analysis pipeline (`next_action_suggested`, `auto_schedule()`) must be operational — it is (confirmed in exploration)
- `LeadProfileFact` schema must support `captured:` namespace — it does (generic key-value, namespace-based)
- Issue #47 `next_action` decision engine must be live before Phase 2 completes

## Success Criteria

- [ ] A new non-insurance agent can be configured with a custom `capture_data` schema and capture domain data during calls without any code changes
- [ ] Quintana Seguros call flow produces identical captured data after migration (schema parity test)
- [ ] `mark_not_interested` and `schedule_followup` are removed from default tool set; post-call analysis drives all lead status transitions
- [ ] No cross-tenant lead data access is possible through any tool (defense-in-depth `client_id` filter on all queries)
- [ ] Existing agents with old tool names in `tools_enabled` degrade gracefully (auto-strip + warning, not crash)
- [ ] `car_make`, `car_model`, `car_year`, `current_insurance` columns on Lead model produce deprecation warnings when accessed
