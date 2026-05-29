# Design: Configurable Agent Tools

## Technical Approach

Replace the hardcoded insurance-specific tool set with a configurable `capture_data` tool whose OpenAI function-calling schema is stored per-agent as JSON. Remove `mark_not_interested` and `schedule_followup` (redundant with post-call analysis). Move `call_count` increment from `get_lead_details` to `initiation.py`. Generalize `get_lead_details` to exclude car-specific fields. All captured data writes to `LeadProfileFact` with a `captured:` namespace prefix. Three-phase rollout: add → remove → deprecate.

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Tool config storage | `tool_config` TEXT column on `agents` table (JSON) | Separate `agent_tool_configs` table; YAML file per agent | Single column matches existing flat pattern (`tools_enabled`, `extraction_config`). No joins needed. JSON Schema stored inline is small (<2KB). |
| Captured data destination | `LeadProfileFact` with `captured:{field}` fact_key prefix | New `lead_captured_data` table; JSON column on Lead | LeadProfileFact already supports append-and-supersede, source_call_id tracking, and temporal queries. Namespace prefix avoids collision with analysis-generated facts. |
| Tool schema format | OpenAI function-calling `parameters` subset (JSON Schema) | Custom DSL; Pydantic model per client | Direct pass-through to OpenAI API — zero transformation needed. Clients already understand JSON Schema from API docs. |
| Status transition removal | Post-call analysis drives ALL transitions via `next_action` engine | Keep tool transitions as backup | Analysis is more accurate (full transcript vs. agent snap judgment). Eliminates conflicting transition sources. Already proven via Issue #47. |
| call_count relocation | Move increment to `initiation.py` (alongside `transition_lead_status → called`) | Keep in get_lead_details; add duplicate in initiation | Initiation is the canonical "call started" event. Side-effects in a query tool violate least-surprise. Initiation already does the status transition. |
| Backward compat for removed tools | Auto-strip unknown tool names from `tools_enabled` on Agent load + deprecation warning log | Hard reject; migration script to rewrite all agents | Graceful degradation — existing agents don't crash. Warnings give visibility. |

## Data Flow

```
Agent Config (tool_config JSON)
    │
    ▼
build_voice_context() ──→ build_tool_definitions()
    │                         │
    │  inject capture_data    │  dynamic schema from tool_config
    │  schema into             │
    ▼                         ▼
OpenAI function-calling ──→ LLM generates tool_call
    │
    ▼
dispatch_tool("capture_data", args, agent_config)
    │
    ├─ validate args against stored JSON Schema
    │
    ▼
LeadProfileFact.upsert("captured:{field}", value, source_call_id)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `backend/app/tools/capture_data.py` | Create | Generic capture handler: validate args vs agent schema, write to LeadProfileFact |
| `backend/app/tools/registry.py` | Modify | Add `capture_data` entry; add `build_capture_data_definition(tool_config)` for dynamic schema |
| `backend/app/tools/dispatcher.py` | Modify | Route `capture_data` with agent config injection; pass `tool_config` from context |
| `backend/app/tenants/models.py` | Modify | Add `tool_config: Text` nullable column to Agent |
| `backend/app/agents/schemas.py` | Modify | Add `tool_config` to AgentCreate/AgentUpdate/AgentResponse; accept `capture_data` in QORA_TOOL_NAMES; auto-strip removed tools with warning |
| `backend/app/voice/context.py` | Modify | Pass `tool_config` to registry builder; store in VoiceSessionContext; remove car-specific fields from `_build_lead_profile_block` |
| `backend/app/voice/initiation.py` | Modify | Add `call_count` increment + `last_called_at` update (moved from get_lead_details) |
| `backend/app/tools/get_lead_details.py` | Modify | Remove `call_count++` side-effect; remove car-specific fields from response; return generic fields only |
| `backend/app/tools/register_interest.py` | Modify (Phase 1) | Add deprecation warning log; keep functional for backward compat |
| `backend/app/tools/mark_not_interested.py` | Deprecate (Phase 2) | Remove from default tools_enabled; keep module for rollback |
| `backend/app/tools/schedule_followup.py` | Deprecate (Phase 2) | Remove from default tools_enabled; keep module for rollback |

## Interfaces / Contracts

```python
# Agent.tool_config JSON schema (stored in agents.tool_config column)
# Example for Quintana Seguros (insurance):
{
  "capture_data": {
    "description": "Registrás el interés del lead y los datos del vehículo para cotización",
    "parameters": {
      "type": "object",
      "properties": {
        "car_make": {"type": "string", "description": "Marca del auto"},
        "car_model": {"type": "string", "description": "Modelo del auto"},
        "car_year": {"type": "integer", "description": "Año del auto"},
        "current_insurance": {"type": "string", "description": "Aseguradora actual"}
      },
      "required": ["car_make", "car_model", "car_year"]
    }
  }
}

# Example for a dentist:
{
  "capture_data": {
    "description": "Capture patient appointment details",
    "parameters": {
      "type": "object",
      "properties": {
        "treatment_type": {"type": "string"},
        "preferred_date": {"type": "string"},
        "has_insurance": {"type": "boolean"}
      },
      "required": ["treatment_type"]
    }
  }
}
```

```python
# capture_data handler signature
async def capture_data(
    session: AsyncSession,
    lead_id: str,
    tool_config: dict,       # agent's capture_data config
    captured_fields: dict,    # validated args from LLM
    source_call_id: str | None = None,
) -> dict:
    """Write each captured field as LeadProfileFact with 'captured:' prefix."""
```

```python
# Dynamic tool definition builder
def build_capture_data_definition(tool_config: dict) -> dict:
    """Build OpenAI function-calling schema from agent's tool_config."""
    cfg = tool_config.get("capture_data", {})
    return {
        "type": "function",
        "function": {
            "name": "capture_data",
            "description": cfg.get("description", "Capture lead information"),
            "parameters": cfg.get("parameters", {"type": "object", "properties": {}}),
        },
    }
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `capture_data` handler writes correct LeadProfileFact rows | pytest + async session mock |
| Unit | `build_capture_data_definition` generates valid OpenAI schema | Pure function tests with various configs |
| Unit | Auto-strip of removed tool names from `tools_enabled` | Schema validator tests |
| Integration | Full dispatch cycle: context build → tool call → DB write | Async DB session with test agent + tool_config |
| Integration | Quintana Seguros parity: capture_data with car schema = same LeadProfileFact output as register_interest | Comparison test with fixture data |
| E2E | Webhook receives capture_data tool call, dispatches, returns result via SSE | Test client against webhook endpoint |

## Migration / Rollout

**Phase 1 — Add (non-breaking):**
1. Add `tool_config` nullable TEXT column to `agents` table (migration)
2. Create `capture_data.py` handler + registry entry
3. Update dispatcher to route `capture_data` with agent config
4. Move `call_count++` from `get_lead_details` to `initiation.py`
5. Migrate Quintana Seguros: set `tool_config` with car fields schema, add `capture_data` to `tools_enabled`
6. `register_interest` stays in `tools_enabled` alongside `capture_data` (dual-run validation)

**Phase 2 — Remove (breaking for old tool names):**
1. Remove `register_interest`, `mark_not_interested`, `schedule_followup` from default `tools_enabled`
2. Auto-strip unknown tool names on Agent schema validation (graceful degradation)
3. Update agent seed data / Quintana config to use `capture_data` only

**Phase 3 — Deprecate (cleanup):**
1. Mark `car_make`, `car_model`, `car_year`, `current_insurance` columns as deprecated (nullable, no DROP)
2. Remove car-specific fields from `_build_lead_profile_block` in context.py
3. Remove car-specific template variables from initiation dynamic_variables

## Open Questions

- [ ] Should `tool_config` support multiple configurable tools beyond `capture_data` (e.g., per-client query tools)? — Deferred, design supports future extension via additional keys in the JSON.
- [ ] Should the CRM API expose LeadProfileFact captured data with a dedicated endpoint, or is the existing profile facts endpoint sufficient?
